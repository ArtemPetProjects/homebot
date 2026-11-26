# PURPOSE: порты (interfaces) между application и adapters. Инфраструктура реализует их, прикладной слой зависит только от контрактов.
from typing import Any, Protocol

from homebot.domain.devices import Device, DeviceInfo
from homebot.domain.models import Answer, PendingAsk


class MessageGateway(Protocol):
    """Отправка сообщений и ответов на нажатия кнопок (адаптер Telegram)."""

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None: ...

    def edit_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any]
    ) -> None: ...


class DeviceScanner(Protocol):
    """Обзор устройств домашней сети (адаптер ARP/ping)."""

    def scan(self, subnet: str, timeout: float = 0.12) -> list[Device]: ...


class RouterGateway(Protocol):
    """Получение списка устройств из админки роутера."""

    def devices(self) -> list[Any]: ...


class InboxGateway(Protocol):
    """Ящик сообщений пользователя для агента."""

    def add(self, text: str, chat_id: int) -> dict[str, Any]: ...


class DeviceGateway(Protocol):
    """Реестр подписей устройств (доменный репозиторий)."""

    def known(self, ip_or_mac: str) -> DeviceInfo | None: ...

    def remember(
        self,
        ip: str,
        mac: str,
        label: str,
        source: str,
        connected: bool = True,
        last_seen: float | None = None,
    ) -> DeviceInfo: ...

    def all_devices(self) -> list[DeviceInfo]: ...

    def with_labels(self, devices: list[Device]) -> list[Device]: ...

    def observe(self, devices: list[Device], now: float | None = None) -> None: ...


class StateStore(Protocol):
    """Хранилище состояния и очередей (адаптер файлового хранилища)."""

    def has_delivered_task(self, task_id: str) -> bool: ...

    def append_outbox(self, record: dict[str, Any], dry: bool) -> None: ...

    def mark_delivered(self, event_id: str) -> None: ...

    def undelivered(self) -> list[dict[str, Any]]: ...

    def bump_outbox_attempts(self, event_id: str) -> None: ...

    def get_pending(self, id: str) -> PendingAsk | None: ...

    def save_pending(self, pending: PendingAsk) -> None: ...

    def all_pending(self) -> list[PendingAsk]: ...

    def find_pending_by_token(self, token: str) -> PendingAsk | None: ...

    def mark_answered(self, id: str) -> None: ...

    def mark_expired(self, id: str) -> Answer: ...

    def next_seq(self) -> int: ...

    def add_answer(self, answer: Answer) -> None: ...

    def answers_since(self, since: int) -> list[Answer]: ...

    def counts(self) -> dict[str, int]: ...
