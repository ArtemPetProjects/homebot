# PURPOSE: тесты сервиса уведомлений, запросов и ответов.
import tempfile
import unittest
from pathlib import Path

from homebot.config import Config
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
        self.transport = FakeTelegramTransport()
        self.service = HomeBotService(_config(False), self.store, self.transport, self.clock)
        self.enabled = HomeBotService(
            _config(True), self.store, self.transport, self.clock
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
