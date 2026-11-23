# PURPOSE: типы событий, запросов и ответов home bot.
from dataclasses import dataclass
from typing import Any

EVENT_KINDS = ("started", "done", "waiting", "info")


@dataclass(frozen=True)
class Event:
    kind: str
    text: str
    task_id: str

    def validate(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"Неизвестный kind: {self.kind}")
        if not self.text or not self.task_id:
            raise ValueError("text и task_id обязательны")


@dataclass(frozen=True)
class Ask:
    id: str
    text: str
    options: tuple[str, ...]

    def validate(self) -> None:
        if not self.id or not self.text:
            raise ValueError("id и text обязательны")
        if not 2 <= len(self.options) <= 8:
            raise ValueError("Нужно от 2 до 8 вариантов ответа")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Варианты ответа должны быть уникальными")
        if any(len(option) > 64 for option in self.options):
            raise ValueError("Текст варианта ответа длиннее 64 символов")


@dataclass(frozen=True)
class Answer:
    id: str
    option: str
    seq: int
    ts: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "option": self.option,
            "seq": self.seq,
            "ts": self.ts,
        }
        if self.reason is not None:
            data["reason"] = self.reason
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Answer":
        return cls(
            id=data["id"],
            option=data["option"],
            seq=int(data["seq"]),
            ts=data["ts"],
            reason=data.get("reason"),
        )


@dataclass
class PendingAsk:
    id: str
    text: str
    options: tuple[str, ...]
    created_at: float
    token: str
    message_id: int | None = None
    chat_id: int | None = None
    answered: bool = False
    expired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "options": list(self.options),
            "created_at": self.created_at,
            "token": self.token,
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "answered": self.answered,
            "expired": self.expired,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PendingAsk":
        return cls(
            id=data["id"],
            text=data["text"],
            options=tuple(data["options"]),
            created_at=float(data["created_at"]),
            token=data["token"],
            message_id=data.get("message_id"),
            chat_id=data.get("chat_id"),
            answered=bool(data.get("answered", False)),
            expired=bool(data.get("expired", False)),
        )
