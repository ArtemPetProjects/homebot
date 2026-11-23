# PURPOSE: транспорт Telegram, короткие callback-токены и маскирование секретов.
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from .config import Config
from .models import Event, PendingAsk

logger = logging.getLogger("homebot.telegram")

TRUNCATE_MARKER = "… (обрезано)"
MAX_ATTEMPTS = 3


class TelegramTransport(Protocol):
    def get_me(self) -> dict[str, Any]: ...

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]: ...

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None: ...

    def edit_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any]
    ) -> None: ...


def truncate_text(text: str, limit: int = 4096) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATE_MARKER)] + TRUNCATE_MARKER


def make_callback_data(pending: PendingAsk, index: int) -> str:
    # В кнопку кладётся только короткий токен: лимит callback_data — 64 байта.
    raw = f"{pending.id}|{pending.created_at}".encode("utf-8")
    token = hashlib.sha256(raw).hexdigest()[:8]
    return f"a:{token}:{index}"


def parse_callback_data(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "a" or len(parts[1]) != 8:
        return None
    try:
        index = int(parts[2])
    except ValueError:
        return None
    return parts[1], index


def build_inline_keyboard(pending: PendingAsk) -> dict[str, Any]:
    rows = []
    for index, option in enumerate(pending.options):
        rows.append(
            [{"text": option, "callback_data": make_callback_data(pending, index)}]
        )
    return {"inline_keyboard": rows}


def format_notification(event: Event) -> str:
    labels = {
        "started": "▶️ Начато",
        "done": "✅ Готово",
        "waiting": "⏳ Ждёт ответа",
        "info": "ℹ️ Инфо",
    }
    label = labels.get(event.kind, event.kind)
    return f"{label}: {event.text}\nЗадача: {event.task_id} [{event.kind}]"


class HttpTelegramTransport:
    def __init__(
        self,
        config: Config,
        sleeper: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] | None = None,
    ):
        self.config = config
        self.sleeper = sleeper
        self.opener = opener or urllib.request.urlopen

    def _call(
        self,
        method: str,
        payload: dict[str, Any],
        request_timeout: int = 15,
    ) -> Any:
        # В лог идёт только имя метода: URL содержит токен и никогда не печатается.
        url = f"{self.config.base_url}/bot{self.config.bot_token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        for attempt in range(MAX_ATTEMPTS):
            logger.info("Bot API: %s", method)
            try:
                response = self.opener(request, timeout=request_timeout)
                body = json.loads(response.read().decode("utf-8"))
                if not body.get("ok"):
                    raise RuntimeError(f"Bot API {method}: ответ без ok")
                return body.get("result")
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == MAX_ATTEMPTS - 1:
                    logger.warning("Bot API %s: HTTP %s", method, exc.code)
                    raise
                try:
                    error_body = json.loads(exc.read().decode("utf-8"))
                    delay = error_body.get("parameters", {}).get("retry_after", 1)
                except (ValueError, AttributeError):
                    delay = 1
                self.sleeper(delay)
        raise RuntimeError(f"Bot API {method}: исчерпаны попытки")

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe", {})

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": truncate_text(text)}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, request_timeout=timeout + 5)

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = truncate_text(text, 200)
        self._call("answerCallbackQuery", payload)

    def edit_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any]
    ) -> None:
        self._call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            },
        )


class FakeTelegramTransport:
    def __init__(self):
        self.sent: list[dict[str, Any]] = []
        self.answered: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self._updates: list[dict[str, Any]] = []
        self._errors: list[Exception] = []

    def get_me(self) -> dict[str, Any]:
        return {"username": "fake_bot"}

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.sent.append(
            {"chat_id": chat_id, "text": truncate_text(text), "reply_markup": reply_markup}
        )
        return {"message_id": len(self.sent)}

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        if self._errors:
            raise self._errors.pop(0)
        updates = self._updates
        self._updates = []
        return updates

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answered.append({"callback_query_id": callback_query_id, "text": text})

    def edit_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any]
    ) -> None:
        self.edited.append(
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        )

    def queue_update(self, update: dict[str, Any]) -> None:
        self._updates.append(update)

    def queue_error(self, error: Exception) -> None:
        self._errors.append(error)
