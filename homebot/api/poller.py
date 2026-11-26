# PURPOSE: опрос Telegram, фильтрация чужого чата и сохранение смещения.
import logging
import threading
from typing import Any, Callable

from homebot.application.use_cases import HomeBotUseCase
from homebot.config import Config
from homebot.infrastructure.store import Store
from homebot.infrastructure.telegram import TelegramTransport

logger = logging.getLogger("homebot.poller")


class Poller:
    def __init__(
        self,
        service: HomeBotUseCase,
        transport: TelegramTransport,
        store: Store,
        config: Config,
        stop_event: threading.Event,
        enabled: Callable[[], bool] | None = None,
    ):
        self.enabled = enabled if enabled is not None else (lambda: True)
        self.service = service
        self.transport = transport
        self.store = store
        self.config = config
        self.stop_event = stop_event

    def process_updates(self, updates: list[dict[str, Any]]) -> int | None:
        new_offset: int | None = None
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                # Telegram вернёт обновления с id строго больше offset.
                candidate = int(update_id) + 1
                new_offset = candidate if new_offset is None else max(new_offset, candidate)

            callback = update.get("callback_query")
            if callback is not None:
                message = callback.get("message") or {}
                chat = message.get("chat") or {}
                if chat.get("id") == self.config.chat_id:
                    self.service.handle_callback(callback)
                continue

            message = update.get("message")
            if message is not None:
                chat = message.get("chat") or {}
                if chat.get("id") == self.config.chat_id:
                    self.service.handle_command(message)
        return new_offset

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                # Недоставленные ответы повторяются, пока процесс жив, а не только на старте.
                self.service.drain_outbox()
            except Exception as exc:
                logger.warning("Ошибка повтора outbox: %s", type(exc).__name__)
            if not self.config.send_enabled or not self.enabled():
                # В dry-run и в режиме ожидания не обращаемся к Telegram.
                self.stop_event.wait(self.config.poll_interval)
                continue
            try:
                offset = self.store.load_offset()
                updates = self.transport.get_updates(offset, timeout=10)
                new_offset = self.process_updates(updates)
                if new_offset is not None:
                    self.store.save_offset(new_offset)
                self.service.expire_due()
                if not updates:
                    self.stop_event.wait(self.config.poll_interval)
            except Exception as exc:
                logger.warning("Ошибка опроса Telegram: %s", type(exc).__name__)
                self.stop_event.wait(min(5.0, self.config.poll_interval * 5))
