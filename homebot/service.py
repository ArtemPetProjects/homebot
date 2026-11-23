# PURPOSE: сервис уведомлений, запросов подтверждения и обработки ответов.
import hashlib
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

from .config import Config
from .models import Answer, Ask, Event, PendingAsk
from .store import Store
from .telegram import (
    TelegramTransport,
    build_inline_keyboard,
    format_notification,
    parse_callback_data,
)

logger = logging.getLogger("homebot.service")


class HomeBotService:
    def __init__(
        self,
        config: Config,
        store: Store,
        transport: TelegramTransport,
        clock: Callable[[], float],
    ):
        self.config = config
        self.store = store
        self.transport = transport
        self.clock = clock
        self._lock = threading.RLock()
        self._seen_task_ids: set[str] = set()
        self._seen_callbacks: set[str] = set()

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds")

    def notify(self, event: Event) -> dict[str, Any]:
        event.validate()
        with self._lock:
            if event.task_id in self._seen_task_ids or self.store.has_delivered_task(
                event.task_id
            ):
                return {"ok": True, "queued": 0, "delivered": False}
            self._seen_task_ids.add(event.task_id)
            text = format_notification(event)
            record = {
                "event_id": uuid.uuid4().hex,
                "kind": "notify",
                "task_id": event.task_id,
                "text": text,
                "ts": self._timestamp(),
            }
            if not self.config.send_enabled:
                self.store.append_outbox(record, dry=True)
                return {"ok": True, "queued": 1, "delivered": False}
            try:
                self.transport.send_message(self.config.chat_id, text)
                self.store.append_outbox(record, dry=False)
                self.store.mark_delivered(record["event_id"])
                return {"ok": True, "queued": 1, "delivered": True}
            except Exception as exc:
                # Секреты в исключении не логируем — только тип ошибки.
                logger.warning("Не удалось отправить уведомление: %s", type(exc).__name__)
                self.store.append_outbox(record, dry=False)
                return {"ok": True, "queued": 1, "delivered": False}

    def ask(self, request: Ask) -> dict[str, Any]:
        request.validate()
        with self._lock:
            current = self.store.get_pending(request.id)
            if current and not current.answered and not current.expired:
                return {"ok": False, "error": "Запрос с таким id уже активен"}
            created = self.clock()
            raw = f"{request.id}|{created}".encode("utf-8")
            token = hashlib.sha256(raw).hexdigest()[:8]
            pending = PendingAsk(
                id=request.id,
                text=request.text,
                options=request.options,
                created_at=created,
                token=token,
            )
            self.store.save_pending(pending)
            record = {
                "event_id": uuid.uuid4().hex,
                "kind": "ask",
                "id": request.id,
                "text": request.text,
                "options": list(request.options),
                "ts": self._timestamp(),
            }
            if not self.config.send_enabled:
                self.store.append_outbox(record, dry=True)
                self.store.add_answer(
                    Answer(
                        id=request.id,
                        option="__undelivered__",
                        seq=self.store.next_seq(),
                        ts=self._timestamp(),
                        reason="dry_run",
                    )
                )
                return {"ok": True, "delivered": False, "id": request.id}
            keyboard = build_inline_keyboard(pending)
            try:
                result = self.transport.send_message(
                    self.config.chat_id, request.text, reply_markup=keyboard
                )
            except Exception as exc:
                logger.warning("Не удалось отправить запрос: %s", type(exc).__name__)
                self.store.append_outbox(record, dry=False)
                return {"ok": True, "delivered": False, "id": request.id}
            pending.message_id = result.get("message_id")
            pending.chat_id = self.config.chat_id
            self.store.save_pending(pending)
            self.store.append_outbox(record, dry=False)
            self.store.mark_delivered(record["event_id"])
            return {"ok": True, "delivered": True, "id": request.id}

    def answers_since(self, since: int) -> dict[str, Any]:
        with self._lock:
            return {"answers": [a.to_dict() for a in self.store.answers_since(since)]}

    def status(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {"ok": True}
            result.update(self.store.counts())
            result["send_enabled"] = self.config.send_enabled
            return result

    def expire_due(self) -> None:
        ttl = self.config.ask_ttl_minutes * 60
        now = self.clock()
        with self._lock:
            for pending in self.store.all_pending():
                if pending.answered or pending.expired:
                    continue
                if now - pending.created_at < ttl:
                    continue
                if pending.chat_id and pending.message_id:
                    try:
                        self.transport.edit_reply_markup(
                            pending.chat_id, pending.message_id, {"inline_keyboard": []}
                        )
                    except Exception as exc:
                        logger.warning(
                            "Не удалось убрать кнопки: %s", type(exc).__name__
                        )
                self.store.mark_expired(pending.id)

    def handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id", ""))
        data = str(callback.get("data", ""))
        parsed = parse_callback_data(data)
        with self._lock:
            if not parsed or not callback_id or callback_id in self._seen_callbacks:
                return
            self._seen_callbacks.add(callback_id)
            token, index = parsed
            pending = self.store.find_pending_by_token(token)
            if pending is None or pending.answered or pending.expired:
                self.transport.answer_callback_query(callback_id, "запрос истёк")
                return
            if not 0 <= index < len(pending.options):
                self.transport.answer_callback_query(callback_id, "неверный вариант")
                return
            option = pending.options[index]
            self.store.add_answer(
                Answer(
                    id=pending.id,
                    option=option,
                    seq=self.store.next_seq(),
                    ts=self._timestamp(),
                )
            )
            self.store.mark_answered(pending.id)
            self.transport.answer_callback_query(callback_id)
            message = callback.get("message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            message_id = message.get("message_id") or pending.message_id
            if chat_id == self.config.chat_id and message_id:
                try:
                    self.transport.edit_reply_markup(
                        chat_id, message_id, {"inline_keyboard": []}
                    )
                except Exception as exc:
                    logger.warning("Не удалось убрать кнопки: %s", type(exc).__name__)

    def handle_command(self, message: dict[str, Any]) -> None:
        parts = str(message.get("text", "")).split()
        if not parts:
            return
        command = parts[0].split("@")[0]
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        # Команды принимаем только из настроенного чата.
        if chat_id != self.config.chat_id:
            return
        if command == "/start":
            reply = "Home bot готов. /help — список команд."
        elif command == "/help":
            reply = "/status — состояние, /ping — проверка связи."
        elif command == "/ping":
            reply = "pong"
        elif command == "/status":
            status = self.status()
            reply = (
                f"Отправка: {'вкл' if status['send_enabled'] else 'выкл'}\n"
                f"Ожидают: {status['pending']}, отвечены: {status['answered']}, "
                f"просрочены: {status['expired']}"
            )
        else:
            return
        self.transport.send_message(chat_id, reply)

    def drain_outbox(self) -> None:
        with self._lock:
            for record in self.store.undelivered():
                if not self.config.send_enabled:
                    return
                event_id = str(record.get("event_id", ""))
                if int(record.get("attempts", 0)) >= 3:
                    continue
                try:
                    self.transport.send_message(
                        self.config.chat_id, str(record.get("text", ""))
                    )
                    self.store.mark_delivered(event_id)
                except Exception as exc:
                    logger.warning(
                        "Не удалось отправить из outbox: %s", type(exc).__name__
                    )
                    self.store.bump_outbox_attempts(event_id)
