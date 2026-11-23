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
from .config import Config, load_config
from .poller import Poller
from .service import HomeBotService
from .store import Store
from .telegram import FakeTelegramTransport, HttpTelegramTransport, TelegramTransport

logger = logging.getLogger("homebot")


@dataclass
class Runtime:
    config: Config
    store: Store
    transport: TelegramTransport
    service: HomeBotService
    server: Any
    poller: Poller
    stop_event: threading.Event

    def shutdown(self) -> None:
        self.stop_event.set()
        self.server.shutdown()
        self.server.server_close()


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
    service = HomeBotService(config, store, transport, clock)
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

    def handle_stop(signum, frame) -> None:
        logger.info("Получен сигнал остановки")
        runtime.stop_event.set()
        runtime.server.shutdown()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    poller_thread = threading.Thread(target=runtime.poller.run, daemon=True)
    poller_thread.start()
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
        logger.info("Home bot остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
