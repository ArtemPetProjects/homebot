# PURPOSE: тесты сервиса уведомлений, запросов и ответов.
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from homebot.config import Config
from homebot.devices import DeviceRegistry
from homebot.inbox import Inbox
from homebot.router import RouterDevice

ARP_SAMPLE = """Interface: 192.168.1.13 --- 0x8
  Internet Address      Physical Address      Type
  192.168.1.1           00-11-22-33-44-55     dynamic
  192.168.1.77          aa-bb-cc-dd-ee-ff     dynamic
"""
from homebot.models import Ask, Event
from homebot.service import HomeBotService
from homebot.store import Store
from homebot.telegram import FakeTelegramTransport


def _config(send_enabled: bool) -> Config:
    return Config(
        bot_token="123:TOKEN",
        chat_id=42,
        api_key="key",
        host="127.0.0.1",
        port=8765,
        send_enabled=send_enabled,
        poll_interval=1.0,
        ask_ttl_minutes=30,
    )


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.now = [1000.0]
        self.clock = lambda: self.now[0]
        self.store = Store(self.state, clock=self.clock)
        self.registry = DeviceRegistry(self.state, clock=self.clock)
        self.inbox = Inbox(self.state, clock=self.clock)
        self.transport = FakeTelegramTransport()
        providers = {"arp_provider": lambda: ARP_SAMPLE, "resolver": lambda ip: None}
        self.service = HomeBotService(
            _config(False), self.store, self.transport, self.clock,
            devices=self.registry, inbox=self.inbox, **providers
        )
        self.enabled = HomeBotService(
            _config(True), self.store, self.transport, self.clock,
            devices=self.registry, inbox=self.inbox, **providers
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _ask_and_data(self, ask_id):
        self.enabled.ask(Ask(ask_id, "Продолжить?", ("Да", "Нет")))
        markup = self.transport.sent[-1]["reply_markup"]
        return markup["inline_keyboard"][0][0]["callback_data"]

    def test_notify_dryrun_writes_outbox_and_returns_delivered_false(self):
        result = self.service.notify(Event("info", "привет", "t1"))
        self.assertEqual(result, {"ok": True, "queued": 1, "delivered": False})
        self.assertEqual(self.transport.sent, [])
        self.assertIn("t1", (self.state / "outbox-dryrun.jsonl").read_text(encoding="utf-8"))

    def test_notify_sends_when_enabled(self):
        result = self.enabled.notify(Event("started", "сборка", "t2"))
        self.assertTrue(result["delivered"])
        self.assertEqual(len(self.transport.sent), 1)
        self.assertIn("сборка", self.transport.sent[0]["text"])

    def test_ask_dryrun_creates_undelivered_answer(self):
        result = self.service.ask(Ask("q1", "Продолжить?", ("Да", "Нет")))
        self.assertFalse(result["delivered"])
        answers = self.service.answers_since(0)["answers"]
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["option"], "__undelivered__")

    def test_expire_writes_timeout_answer(self):
        self.service.ask(Ask("q1", "Продолжить?", ("Да", "Нет")))
        self.assertEqual(len(self.store.all_pending()), 1)
        self.now[0] += 31 * 60
        self.service.expire_due()
        answers = self.service.answers_since(0)["answers"]
        self.assertTrue(any(a["option"] == "__timeout__" for a in answers))
        self.assertTrue(self.store.get_pending("q1").expired)

    def test_late_callback_is_rejected(self):
        data = self._ask_and_data("q1")
        self.now[0] += 31 * 60
        self.enabled.expire_due()
        self.enabled.handle_callback(
            {"id": "cb-late", "data": data, "message": {"message_id": 1, "chat": {"id": 42}}}
        )
        answers = self.enabled.answers_since(0)["answers"]
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["option"], "__timeout__")
        self.assertIn("истёк", self.transport.answered[-1]["text"])

    def test_old_callback_token_invalid_after_id_reuse(self):
        old_data = self._ask_and_data("q1")
        self.now[0] += 31 * 60
        self.enabled.expire_due()
        new_data = self._ask_and_data("q1")
        self.assertNotEqual(old_data, new_data)
        self.enabled.handle_callback(
            {"id": "cb-old", "data": old_data, "message": {"message_id": 1, "chat": {"id": 42}}}
        )
        options = [a["option"] for a in self.enabled.answers_since(0)["answers"]]
        self.assertEqual(options, ["__timeout__"])

    def test_duplicate_task_id_is_not_sent_twice(self):
        self.enabled.notify(Event("info", "первое", "same"))
        self.enabled.notify(Event("info", "второе", "same"))
        self.assertEqual(len(self.transport.sent), 1)

    def test_ask_send_failure_goes_to_outbox(self):
        class Failing:
            def send_message(self, *args, **kwargs):
                raise RuntimeError("network down")

        failing = HomeBotService(
            _config(True), self.store, Failing(), self.clock
        )
        result = failing.ask(Ask("q-fail", "Продолжить?", ("Да", "Нет")))
        self.assertTrue(result["ok"])
        self.assertFalse(result["delivered"])
        self.assertIn("q-fail", (self.state / "outbox.jsonl").read_text(encoding="utf-8"))

    def test_drain_outbox_retries_and_marks_delivered(self):
        self.store.append_outbox(
            {"event_id": "e1", "kind": "notify", "task_id": "t9", "text": "хвост"},
            dry=False,
        )
        self.enabled.drain_outbox()
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.store.undelivered(), [])

    def test_drain_outbox_stops_after_three_attempts(self):
        self.store.append_outbox(
            {
                "event_id": "e2",
                "kind": "notify",
                "task_id": "t10",
                "text": "хвост",
                "attempts": 3,
            },
            dry=False,
        )
        self.enabled.drain_outbox()
        self.assertEqual(self.transport.sent, [])

    def test_delivered_task_id_is_not_duplicated_after_restart(self):
        self.store.append_outbox(
            {
                "event_id": "e3",
                "kind": "notify",
                "task_id": "dup",
                "text": "уже отправлено",
                "delivered_at": "2026-11-24T00:00:00",
            },
            dry=False,
        )
        fresh = HomeBotService(_config(True), self.store, self.transport, self.clock)
        result = fresh.notify(Event("info", "ещё раз", "dup"))
        self.assertEqual(result["queued"], 0)
        self.assertEqual(self.transport.sent, [])

    def test_handoff_sends_notify_and_ask(self):
        result = self.enabled.handoff(
            {
                "summary": "Готово",
                "question": "Что дальше?",
                "options": ["Продолжить", "Пауза"],
                "task_id": "h1",
            }
        )
        self.assertEqual(result["ask_id"], "handoff:h1")
        self.assertGreaterEqual(len(self.transport.sent), 2)
        self.assertEqual(self.transport.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["text"], "Продолжить")
        pending = self.store.get_pending("handoff:h1")
        self.assertEqual(pending.source, "agent")

    def test_handoff_idempotent(self):
        body = {
            "summary": "Готово",
            "question": "Что дальше?",
            "options": ["Продолжить", "Пауза"],
            "task_id": "h2",
        }
        first = self.enabled.handoff(body)
        count = len(self.transport.sent)
        second = self.enabled.handoff(body)
        self.assertEqual(second["ask_id"], first["ask_id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.transport.sent), count)

    def test_keyboard_attached_to_replies(self):
        self.enabled.handle_command({"text": "/ping", "chat": {"id": 42}})
        markup = self.transport.sent[-1]["reply_markup"]
        labels = [button["text"] for button in markup["keyboard"][0]]
        self.assertEqual(labels, ["Устройства", "Что дальше", "Статус", "Помощь"])

    def test_nextdown_ignores_device_asks(self):
        self.enabled.ask(
            Ask("agent-q", "Жду решения: что делать дальше?", ("Продолжить", "Пауза"))
        )
        self.enabled.ask(
            Ask("device-q", "Что это за устройство?", ("Да", "Нет"), source="device")
        )
        before = len(self.transport.sent)
        self.enabled.handle_command({"text": "/nextdown", "chat": {"id": 42}})
        self.assertEqual(len(self.transport.sent), before + 1)
        self.assertIn("Жду решения", self.transport.sent[-1]["text"])

    def test_label_command_updates_registry(self):
        self.registry.remember("192.168.1.50", "aa:bb:cc:dd:ee:ff", "", "discovered")
        self.enabled.handle_command({"text": "/label 192.168.1.50 Xbox", "chat": {"id": 42}})
        self.assertEqual(self.registry.known("192.168.1.50").label, "Xbox")

    def test_devices_shows_connection_status(self):
        self.enabled.handle_command({"text": "/devices", "chat": {"id": 42}})
        text = self.transport.sent[0]["text"]
        self.assertIn("онлайн", text)
        self.assertIn("оффлайн", text)
        self.assertIn("оффлайн с:", text)

    def test_devices_does_not_ask_user_to_label(self):
        self.enabled.handle_command({"text": "/devices", "chat": {"id": 42}})
        self.now[0] += 5
        self.enabled.handle_command({"text": "/devices", "chat": {"id": 42}})
        active = [
            pending for pending in self.store.all_pending()
            if pending.source == "device" and not pending.answered and not pending.expired
        ]
        self.assertEqual(active, [])
        self.assertEqual(self.registry.known("192.168.1.77").label, "Устройство 77")

    def test_send_to_agent_button_and_text(self):
        self.enabled.handle_command({"text": "Отправить агенту", "chat": {"id": 42}})
        self.assertIn("Напишите сообщение", self.transport.sent[-1]["text"])
        self.enabled.handle_message({"text": "Идея на прогулке", "chat": {"id": 42}})
        self.assertIn("Записано для агента", self.transport.sent[-1]["text"])
        unread = self.inbox.unread()
        self.assertEqual(len(unread), 1)
        self.assertEqual(unread[0]["text"], "Идея на прогулке")

    def test_devices_from_router_replace_manual_scan(self):
        class FakeRouter:
            def devices(self):
                return [
                    RouterDevice("Android TV", "192.168.1.2", "78:53:33:4a:40:64", True, 100),
                    RouterDevice("POCO X8 Pro Max", "192.168.1.17", "f2:84:0b:fa:e9:40", False, 300),
                ]

        cfg = _config(True)
        object.__setattr__(cfg, "router_login", "admin")
        object.__setattr__(cfg, "router_password", "pw")
        service = HomeBotService(
            cfg, self.store, self.transport, self.clock,
            devices=self.registry, inbox=self.inbox, router_client=FakeRouter(),
        )
        service.handle_command({"text": "/devices", "chat": {"id": 42}})
        text = self.transport.sent[-1]["text"]
        self.assertIn("192.168.1.2 — Android TV", text)
        self.assertIn("192.168.1.17 — POCO X8 Pro Max", text)
        self.assertIn("оффлайн с:", text)

    def test_devices_shows_first_seen_when_last_seen_unknown(self):
        class FakeRouter:
            def devices(self):
                return [
                    RouterDevice("Yandex Bulb", "192.168.1.99", "aa:bb:cc:00:11:22", False, 0),
                ]

        cfg = _config(True)
        object.__setattr__(cfg, "router_login", "admin")
        object.__setattr__(cfg, "router_password", "pw")
        service = HomeBotService(
            cfg, self.store, self.transport, self.clock,
            devices=self.registry, inbox=self.inbox, router_client=FakeRouter(),
        )
        service.handle_command({"text": "/devices", "chat": {"id": 42}})
        text = self.transport.sent[-1]["text"]
        self.assertIn("зафиксировано: 01.01.1970 03:16", text)

    def test_devices_no_duplicate_labels_and_no_raw_mac(self):
        class FakeRouter:
            def devices(self):
                return [
                    RouterDevice("POCO X8 Pro Max", "192.168.1.17", "f2:84:0b:fa:e9:40", False, 300),
                    RouterDevice("POCO X8 Pro Max", "", "76:23:fa:41:35:4a", False, 0),
                    RouterDevice("", "", "ac:ba:c0:b4:a2:86", False, 0),
                ]

        cfg = _config(True)
        object.__setattr__(cfg, "router_login", "admin")
        object.__setattr__(cfg, "router_password", "pw")
        service = HomeBotService(
            cfg, self.store, self.transport, self.clock,
            devices=self.registry, inbox=self.inbox, router_client=FakeRouter(),
        )
        service.handle_command({"text": "/devices", "chat": {"id": 42}})
        text = self.transport.sent[-1]["text"]
        self.assertEqual(text.count("POCO X8 Pro Max"), 1)
        self.assertNotIn("76:23:fa:41:35:4a", text)
        self.assertNotIn("ac:ba:c0:b4:a2:86", text)
        self.assertIn("без IP", text)

    def test_keyboard_has_send_to_agent_button(self):
        self.enabled.handle_command({"text": "/ping", "chat": {"id": 42}})
        markup = self.transport.sent[-1]["reply_markup"]
        self.assertIn("Отправить агенту", [b["text"] for b in markup["keyboard"][1]])

    def test_button_whats_next_is_recognized(self):
        self.enabled.handle_command({"text": "Что дальше", "chat": {"id": 42}})
        self.assertEqual(len(self.transport.sent), 1)
        self.assertIn("Нет ожидающих", self.transport.sent[0]["text"])

    def test_devices_uses_injected_arp_provider(self):
        self.enabled.handle_command({"text": "/devices", "chat": {"id": 42}})
        text = self.transport.sent[0]["text"]
        self.assertIn("192.168.1.77", text)
        self.assertIn("Устройство", text)

    def test_devices_replies_when_scan_fails(self):
        with mock.patch.object(
            self.enabled, "_scan_devices", side_effect=RuntimeError("сканер недоступен")
        ):
            self.enabled.handle_command({"text": "/devices", "chat": {"id": 42}})
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.transport.sent[0]["chat_id"], 42)
        self.assertIn(
            "Сканирование на этом устройстве недоступно", self.transport.sent[0]["text"]
        )
        self.assertIsNotNone(self.transport.sent[0]["reply_markup"])

    def test_reply_record_keeps_chat_id_and_keyboard(self):
        self.enabled.handle_command({"text": "/ping", "chat": {"id": 42}})
        lines = (self.state / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "reply")
        self.assertEqual(records[0]["chat_id"], 42)
        self.assertEqual(records[0]["reply_markup"]["keyboard"][0][0]["text"], "Устройства")
        self.assertTrue(records[0]["delivered_at"])

    def test_reply_send_failure_queues_for_retry(self):
        class Failing:
            def send_message(self, *args, **kwargs):
                raise RuntimeError("network down")

        failing = HomeBotService(_config(True), self.store, Failing(), self.clock)
        failing.handle_command({"text": "/status", "chat": {"id": 42}})
        pending = self.store.undelivered()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], "reply")
        self.assertEqual(pending[0]["chat_id"], 42)
        self.assertIn("Отправка", pending[0]["text"])

    def test_drain_outbox_uses_saved_chat_id_and_markup(self):
        markup = {"keyboard": [[{"text": "Устройства"}]], "resize_keyboard": True}
        self.store.append_outbox(
            {
                "event_id": "reply-77",
                "kind": "reply",
                "chat_id": 77,
                "text": "хвост ответа",
                "reply_markup": markup,
                "ts": "2026-11-25T00:00:00",
            },
            dry=False,
        )
        self.enabled.drain_outbox()
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.transport.sent[0]["chat_id"], 77)
        self.assertEqual(self.transport.sent[0]["reply_markup"], markup)
        self.assertEqual(self.store.undelivered(), [])

    def test_callback_sends_confirmation_in_chat(self):
        data = self._ask_and_data("q1")
        before = len(self.transport.sent)
        self.enabled.handle_callback(
            {"id": "cb-confirm", "data": data, "message": {"message_id": 1, "chat": {"id": 42}}}
        )
        self.assertEqual(len(self.transport.sent), before + 1)
        text = self.transport.sent[-1]["text"]
        self.assertIn("Принято", text)
        self.assertIn("Да", text)

    def test_answer_seq_is_monotonic(self):
        first = self._ask_and_data("q1")
        self.enabled.handle_callback(
            {"id": "cb1", "data": first, "message": {"message_id": 1, "chat": {"id": 42}}}
        )
        second = self._ask_and_data("q2")
        self.enabled.handle_callback(
            {"id": "cb2", "data": second, "message": {"message_id": 2, "chat": {"id": 42}}}
        )
        answers = self.enabled.answers_since(0)["answers"]
        self.assertEqual([a["seq"] for a in answers], [1, 2])


if __name__ == "__main__":
    unittest.main()
