# PURPOSE: тесты опроса Telegram, фильтра чата и смещения обновлений.
import tempfile
import threading
import time
import unittest
from pathlib import Path

from homebot.config import Config
from homebot.models import Ask
from homebot.poller import Poller
from homebot.service import HomeBotService
from homebot.store import Store
from homebot.telegram import FakeTelegramTransport


class PollerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name), clock=lambda: 1000.0)
        self.transport = FakeTelegramTransport()
        self.config = Config(
            bot_token="123:TOKEN",
            chat_id=42,
            api_key="key",
            host="127.0.0.1",
            port=8765,
            send_enabled=True,
            poll_interval=0.01,
            ask_ttl_minutes=30,
        )
        self.service = HomeBotService(
            self.config, self.store, self.transport, lambda: 1000.0
        )
        self.stop = threading.Event()
        self.poller = Poller(
            self.service, self.transport, self.store, self.config, self.stop
        )

    def tearDown(self):
        self.stop.set()
        self.tmp.cleanup()

    def _message(self, update_id, chat_id, text):
        return {
            "update_id": update_id,
            "message": {"message_id": 1, "chat": {"id": chat_id}, "text": text},
        }

    def test_process_updates_saves_offset(self):
        result = self.poller.process_updates([self._message(10, 42, "/ping")])
        self.assertEqual(result, 11)
        self.store.save_offset(result)
        self.assertEqual(self.store.load_offset(), 11)

    def test_ignores_foreign_chat(self):
        self.poller.process_updates([self._message(11, 999, "/status")])
        self.assertEqual(self.transport.sent, [])

    def test_callback_dispatched_to_service(self):
        self.service.ask(Ask("q1", "Продолжить?", ("Да", "Нет")))
        data = self.transport.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        update = {
            "update_id": 12,
            "callback_query": {
                "id": "cb1",
                "data": data,
                "message": {"message_id": 1, "chat": {"id": 42}},
            },
        }
        self.poller.process_updates([update])
        self.assertEqual(len(self.transport.answered), 1)
        self.assertEqual(self.service.answers_since(0)["answers"][0]["option"], "Да")

    def test_command_status_replies(self):
        self.poller.process_updates([self._message(13, 42, "/status")])
        self.assertEqual(len(self.transport.sent), 1)
        self.assertIn("Отправка", self.transport.sent[0]["text"])

    def test_run_retries_undelivered_outbox_while_running(self):
        markup = {"keyboard": [[{"text": "Устройства"}]], "resize_keyboard": True}
        self.store.append_outbox(
            {
                "event_id": "reply-retry",
                "kind": "reply",
                "chat_id": 77,
                "text": "Ответ после сбоя",
                "reply_markup": markup,
                "ts": "2026-11-25T00:00:00",
            },
            dry=False,
        )

        def stopper():
            time.sleep(0.1)
            self.stop.set()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        self.poller.run()
        thread.join(timeout=2)
        self.assertTrue(any(item["chat_id"] == 77 for item in self.transport.sent))
        self.assertEqual(self.store.undelivered(), [])

    def test_run_stops_on_event(self):
        def stopper():
            time.sleep(0.05)
            self.stop.set()

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        self.poller.run()
        thread.join(timeout=2)
        self.assertTrue(self.stop.is_set())


if __name__ == "__main__":
    unittest.main()
