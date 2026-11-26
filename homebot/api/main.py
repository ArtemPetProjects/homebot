# PURPOSE: сборка и запуск локального процесса home bot.
import argparse
import logging
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bridge import make_server
from homebot.application.use_cases import HomeBotUseCase
from homebot.config import Config, load_config
from homebot.infrastructure.network import NetworkDeviceScanner
from homebot.infrastructure.store import Store
from homebot.infrastructure.telegram import (
    FakeTelegramTransport,
    HttpTelegramTransport,
    TelegramTransport,
)

from .poller import Poller
from .supervisor import run_supervisor

logger = logging.getLogger("homebot")


@dataclass
class Runtime:
    config: Config
    store: Store
    transport: TelegramTransport
    service: HomeBotUseCase
    server: Any
    poller: Poller
    stop_event: threading.Event

    def shutdown(self) -> None:
        # shutdown() блокируется до выхода serve_forever, поэтому нельзя в том же потоке.
        self.stop_event.set()
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.server.server_close()


def make_stop_handler(runtime: Runtime):
    def handler(signum, frame) -> None:
        logger.info("Получен сигнал остановки")
        runtime.stop_event.set()
        # Сигнальный хендлер выполняется в главном потоке внутри serve_forever;
        # прямой вызов shutdown() привёл бы к взаимной блокировке.
        threading.Thread(target=runtime.server.shutdown, daemon=True).start()

    return handler


def build_runtime(
    config: Config,
    state_dir: Path | None = None,
    transport: TelegramTransport | None = None,
    port: int | None = None,
) -> Runtime:
    project_root = Path(__file__).resolve().parent.parent
    state = state_dir if state_dir is not None else project_root / "state"
    clock = time.time
    store = Store(state, clock=clock)
    if transport is None:
        # В dry-run не создаём сетевой транспорт вообще.
        transport = (
            FakeTelegramTransport()
            if not config.send_enabled
            else HttpTelegramTransport(config)
        )
    # Композиция: конкретные адаптеры впрыскиваются в use case только здесь.
    service = HomeBotUseCase(
        config, store, transport, clock, device_scanner=NetworkDeviceScanner()
    )
    # Недоставленные события повторяются при старте, но только при включённой отправке.
    if config.send_enabled:
        service.drain_outbox()
    stop_event = threading.Event()
    poller = Poller(service, transport, store, config, stop_event)
    server = make_server(config, service, port=port)
    return Runtime(config, store, transport, service, server, poller, stop_event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальный бот уведомлений агента")
    parser.add_argument("--env", default=None, help="Путь к файлу .env")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    env_path = Path(args.env) if args.env else Path(__file__).resolve().parent.parent / ".env"
    config = load_config(env_path)
    runtime = build_runtime(config)

    handle_stop = make_stop_handler(runtime)
    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    standby_state = {"active": False}
    if config.standby_pc_url:
        runtime.poller = Poller(
            runtime.service,
            runtime.transport,
            runtime.store,
            config,
            runtime.stop_event,
            enabled=lambda: standby_state["active"],
        )
    poller_thread = threading.Thread(target=runtime.poller.run, daemon=True)
    poller_thread.start()
    supervisor_thread = None
    if config.standby_pc_url:
        supervisor_thread = threading.Thread(
            target=run_supervisor,
            args=(config, runtime.service, runtime.stop_event, standby_state),
            daemon=True,
        )
        supervisor_thread.start()
    logger.info(
        "Home bot запущен: %s:%s, отправка %s",
        config.host,
        config.port,
        "вкл" if config.send_enabled else "выкл",
    )
    try:
        runtime.server.serve_forever(poll_interval=0.5)
    finally:
        runtime.stop_event.set()
        runtime.server.server_close()
        poller_thread.join(timeout=5)
        if supervisor_thread is not None:
            supervisor_thread.join(timeout=5)
        logger.info("Home bot остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
