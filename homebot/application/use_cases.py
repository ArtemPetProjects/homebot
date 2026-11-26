# PURPOSE: прикладной use case: уведомления, запросы подтверждения и обработка ответов.
import hashlib
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

from homebot.config import Config
from homebot.domain.devices import Device, DeviceRegistry
from homebot.domain.models import Answer, Ask, Event, PendingAsk
from homebot.infrastructure.inbox import Inbox
from homebot.infrastructure.network import raw_ping, scan_network
from homebot.infrastructure.router import RouterClient
from homebot.infrastructure.store import Store
from homebot.infrastructure.telegram import (
    TelegramTransport,
    build_inline_keyboard,
    build_main_keyboard,
    format_notification,
    parse_callback_data,
)

from .ports import DeviceScanner

logger = logging.getLogger("homebot.service")


class HomeBotUseCase:
    def __init__(
        self,
        config: Config,
        store: Store,
        transport: TelegramTransport,
        clock: Callable[[], float],
        devices: DeviceRegistry | None = None,
        arp_provider: Callable[[], str] | None = None,
        resolver: Callable[[str], str | None] | None = None,
        probe_provider: Callable[[str], bool] | None = None,
        inbox: Inbox | None = None,
        router_client=None,
        device_scanner: DeviceScanner | None = None,
    ):
        self.config = config
        self.store = store
        self.transport = transport
        self.clock = clock
        self.devices = devices if devices is not None else DeviceRegistry(store.state_dir)
        self.arp_provider = arp_provider
        self.resolver = resolver
        self.probe_provider = probe_provider
        self.inbox = inbox if inbox is not None else Inbox(store.state_dir)
        self.router_client = router_client
        self.device_scanner = device_scanner
        self._awaiting_text: set[int] = set()
        self._lock = threading.RLock()
        self._seen_task_ids: set[str] = set()
        self._seen_callbacks: set[str] = set()
        self._devices_cache: tuple[float, list] | None = None

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
                source=request.source,
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

    def handoff(self, body: dict[str, Any]) -> dict[str, Any]:
        task_id = str(body.get("task_id", ""))
        summary = str(body.get("summary", ""))
        question = str(body.get("question", ""))
        raw_options = body.get("options")
        options = tuple(str(item) for item in raw_options) if isinstance(raw_options, list) else ()
        if not task_id or not summary or not question:
            raise ValueError("task_id, summary и question обязательны")
        ask_id = "handoff:" + task_id
        current = self.store.get_pending(ask_id)
        if current and not current.answered and not current.expired:
            return {"ok": True, "ask_id": ask_id, "duplicate": True}
        self.notify(Event(kind="waiting", text=summary + "\nЖду решения.", task_id=task_id))
        self.ask(Ask(id=ask_id, text=question, options=options, source="agent"))
        return {"ok": True, "ask_id": ask_id}

    def import_inbox(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        imported = 0
        with self._lock:
            for message in messages:
                text = str(message.get("text", ""))
                if not text:
                    continue
                self.inbox.add(text, int(message.get("chat_id", self.config.chat_id)))
                imported += 1
        return {"ok": True, "imported": imported}

    def answers_since(self, since: int) -> dict[str, Any]:
        with self._lock:
            return {"answers": [a.to_dict() for a in self.store.answers_since(since)]}

    def status(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {"ok": True}
            result.update(self.store.counts())
            result["send_enabled"] = self.config.send_enabled
            return result

    def _send_reply(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None:
        # Ответ команды сохраняется в outbox: при разовом сбое его сможет повторить поллер.
        record: dict[str, Any] = {
            "event_id": uuid.uuid4().hex,
            "kind": "reply",
            "chat_id": chat_id,
            "text": text,
            "ts": self._timestamp(),
        }
        if reply_markup is not None:
            record["reply_markup"] = reply_markup
        if not self.config.send_enabled:
            self.store.append_outbox(record, dry=True)
            return
        try:
            self.transport.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as exc:
            # Секреты в исключении не логируем — только тип ошибки.
            logger.warning("Не удалось отправить ответ: %s", type(exc).__name__)
            self.store.append_outbox(record, dry=False)
            return
        self.store.append_outbox(record, dry=False)
        self.store.mark_delivered(record["event_id"])

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
            # Пользователь должен видеть в чате, что его выбор принят.
            reply_chat = (message.get("chat") or {}).get("id")
            if reply_chat != self.config.chat_id:
                reply_chat = self.config.chat_id
            self._send_reply(
                reply_chat,
                f"Принято: {option}\nНачинаю работать по вашему выбору.",
                build_main_keyboard(),
            )
            chat_id = (message.get("chat") or {}).get("id")
            message_id = message.get("message_id") or pending.message_id
            if chat_id == self.config.chat_id and message_id:
                try:
                    self.transport.edit_reply_markup(
                        chat_id, message_id, {"inline_keyboard": []}
                    )
                except Exception as exc:
                    logger.warning("Не удалось убрать кнопки: %s", type(exc).__name__)

    def handle_message(self, message: dict[str, Any]) -> None:
        text = str(message.get("text", "")).strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id != self.config.chat_id or not text:
            return
        if text == "Отправить агенту":
            self._awaiting_text.add(chat_id)
            reply = "Напишите сообщение — я сразу покажу его здесь и сохраню для агента."
        elif chat_id in self._awaiting_text:
            record = self.inbox.add(text, chat_id)
            self._awaiting_text.discard(chat_id)
            reply = f"Записано для агента: {text}\n(id: {record['id']})"
        else:
            return
        self._send_reply(chat_id, reply, build_main_keyboard())

    def handle_command(self, message: dict[str, Any]) -> None:
        text = str(message.get("text", "")).strip()
        parts = text.split()
        if not parts:
            return
        aliases = {
            "Устройства": "/devices",
            "Что дальше": "/nextdown",
            "Статус": "/status",
            "Помощь": "/help",
        }
        if text in aliases:
            command = aliases[text]
        else:
            command = aliases.get(parts[0].split("@")[0], parts[0].split("@")[0])
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        # Команды принимаем только из настроенного чата.
        if chat_id != self.config.chat_id:
            return
        if command == "/start":
            reply = "Home bot готов. Кнопки ниже — доступные действия."
        elif command == "/help":
            reply = "/devices — устройства сети, /nextdown — вопрос агента, /status — состояние, /ping — связь."
        elif command == "/info":
            reply = (
                "Команды бота:\n"
                "/devices — устройства домашней сети\n"
                "/label <ip> <имя> — подписать устройство\n"
                "/nextdown — последний вопрос агента\n"
                "/status — состояние\n"
                "/help — краткий список\n"
                "/ping — проверка связи"
            )
        elif command == "/ping":
            reply = "pong"
        elif command == "/status":
            status = self.status()
            reply = (
                f"Отправка: {'вкл' if status['send_enabled'] else 'выкл'}\n"
                f"Ожидают: {status['pending']}, отвечены: {status['answered']}, "
                f"просрочены: {status['expired']}"
            )
        elif command == "/label" and len(parts) >= 3:
            ip = parts[1]
            label = " ".join(parts[2:])
            cached = {device.ip: device.mac for device in self._scan_devices()}
            self.devices.remember(ip, cached.get(ip, ""), label, "user")
            reply = f"Подпись сохранена: {ip} — {label}"
        elif command == "/devices":
            import datetime

            scan_error = None
            try:
                scanned = self._scan_devices()
            except Exception as exc:
                # Даже при недоступном сканере пользователь должен получить ответ.
                logger.warning("Сканирование устройств недоступно: %s", type(exc).__name__)
                scanned = []
                scan_error = "Сканирование на этом устройстве недоступно"
            rows = []
            seen = set()
            label_keys = set()

            def label_key(value: str) -> str:
                value = value.lower().replace("(офлайн)", "").replace("(онлайн)", "")
                return "".join(ch for ch in value if ch.isalnum())

            def display_identifier(value: str) -> str:
                # Роутер не отдаёт IP для офлайн-устройств; сырой MAC пользователю не показываем.
                return "без IP" if value.count(":") >= 2 else value

            for device in scanned:
                # Онлайн-устройства с IP идут первыми — их подпись и адрес приоритетнее.
                key = label_key(device.label)
                if key and key in label_keys:
                    continue
                identifier = device.ip or device.mac or "?"
                known = self.devices.known(device.ip) or self.devices.known(device.mac)
                rows.append(
                    (
                        display_identifier(identifier),
                        device.label or device.hostname or "Без имени",
                        device.connected,
                        device.last_seen,
                        known.first_seen if known else 0.0,
                    )
                )
                seen.add(identifier)
                if device.mac:
                    seen.add(device.mac)
                if key:
                    label_keys.add(key)
            # Устройства, которых сейчас нет в сети, берём из реестра роутера.
            for info in self.devices.all_devices():
                identifier = info.ip or info.mac or "?"
                if identifier in seen or (info.ip and info.ip in seen) or (info.mac and info.mac in seen):
                    continue
                # Одно и то же устройство может быть в реестре и с IP, и с MAC — не дублируем.
                if info.label and label_key(info.label) in label_keys:
                    continue
                rows.append(
                    (
                        display_identifier(identifier),
                        info.label or "Без имени",
                        info.connected,
                        info.last_seen,
                        info.first_seen,
                    )
                )
                if info.label:
                    label_keys.add(label_key(info.label))
            lines = ["Устройства домашней сети:"]
            if scan_error:
                lines.append(scan_error)
            if not rows:
                lines.append("Устройства не найдены")
            for identifier, label, connected, last_seen, first_seen in rows:
                lines.append(f"{identifier} — {label}")
                if connected:
                    lines.append("онлайн")
                elif last_seen:
                    moment = datetime.datetime.fromtimestamp(last_seen).strftime("%d.%m.%Y %H:%M")
                    lines.append(f"оффлайн с: {moment}")
                elif first_seen:
                    moment = datetime.datetime.fromtimestamp(first_seen).strftime("%d.%m.%Y %H:%M")
                    lines.append(f"зафиксировано: {moment}")
                else:
                    lines.append("оффлайн, время последнего подключения неизвестно")
            self._send_reply(chat_id, "\n".join(lines), build_main_keyboard())
            return
        elif command == "/nextdown":
            active = [
                pending
                for pending in self.store.all_pending()
                if pending.source == "agent" and not pending.answered and not pending.expired
            ]
            if not active:
                reply = "Нет ожидающих вопросов агента."
            else:
                latest = max(active, key=lambda item: item.created_at)
                self._send_reply(chat_id, latest.text, build_inline_keyboard(latest))
                return
        elif not command.startswith("/"):
            self.handle_message(message)
            return
        else:
            return
        self._send_reply(chat_id, reply, build_main_keyboard())

    def _scan_devices(self) -> list:
        now = self.clock()
        if self._devices_cache and now - self._devices_cache[0] < 30:
            return self._devices_cache[1]
        router_devices = []
        if self.config.router_login and self.config.router_password:
            client = self.router_client or RouterClient(self.config)
            try:
                router_devices = client.devices()
            except Exception as exc:
                logger.warning("Не удалось получить устройства роутера: %s", type(exc).__name__)
        if router_devices:
            for item in router_devices:
                known = self.devices.known(item.mac) or self.devices.known(item.ip)
                label = (
                    item.name
                    or (f"Устройство {item.ip.rsplit('.', 1)[-1]}" if item.ip else "")
                    or (known.label if known and known.label else "Без имени")
                )
                if item.online:
                    last_seen = now
                elif item.online_seconds:
                    # Роутер хранит время последнего подключения, а не время опроса.
                    last_seen = now - item.online_seconds
                elif known and known.last_seen and known.last_seen < now - 60:
                    last_seen = known.last_seen
                else:
                    last_seen = 0.0
                self.devices.remember(
                    item.ip, item.mac, label, "router",
                    connected=item.online, last_seen=last_seen,
                )
            devices = [
                Device(
                    ip=info.ip,
                    mac=info.mac,
                    hostname=None,
                    alive=info.connected,
                    known=True,
                    label=info.label,
                    source=info.source,
                    connected=info.connected,
                    last_seen=info.last_seen,
                )
                for info in self.devices.all_devices()
            ]
        else:
            if self.device_scanner is not None:
                scanned = self.device_scanner.scan(self.config.network_subnet, timeout=0.12)
            else:
                scanned = scan_network(
                    self.config.network_subnet,
                    arp_provider=self.arp_provider,
                    resolver=self.resolver,
                    timeout=0.12,
                    probe=self.probe_provider
                    if self.probe_provider is not None
                    else (None if self.arp_provider is not None else raw_ping),
                )
            devices = self.devices.with_labels(scanned)
            self.devices.observe(devices, now)
            devices = self.devices.with_labels(devices)
        # Онлайн-устройства с адресом первыми: их подпись выигрывает при дедупликации.
        devices.sort(key=lambda item: (not item.connected, not item.ip, item.label))
        self._devices_cache = (now, devices)
        return devices

    def drain_outbox(self) -> None:
        with self._lock:
            for record in self.store.undelivered():
                if not self.config.send_enabled:
                    return
                event_id = str(record.get("event_id", ""))
                if int(record.get("attempts", 0)) >= 3:
                    continue
                try:
                    # Ответы уходят в тот чат и с той клавиатурой, с которой были созданы.
                    self.transport.send_message(
                        record.get("chat_id", self.config.chat_id),
                        str(record.get("text", "")),
                        reply_markup=record.get("reply_markup"),
                    )
                    self.store.mark_delivered(event_id)
                except Exception as exc:
                    logger.warning(
                        "Не удалось отправить из outbox: %s", type(exc).__name__
                    )
                    self.store.bump_outbox_attempts(event_id)


# Обратно совместимое имя для внешних вызывающих модулей.
HomeBotService = HomeBotUseCase
