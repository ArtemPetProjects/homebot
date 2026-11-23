# PURPOSE: тесты транспорта Telegram и безопасного форматирования.
import io
import json
import logging
import unittest
import urllib.error

from homebot.config import Config
from homebot.models import Event, PendingAsk
from homebot.telegram import (
    FakeTelegramTransport,
    HttpTelegramTransport,
    build_inline_keyboard,
    format_notification,
    make_callback_data,
    parse_callback_data,
    truncate_text,
)


def _config():
    return Config(
        bot_token="123:SECRET_TOKEN",
        chat_id=42,
        api_key="local-key",
        host="127.0.0.1",
        port=8765,
        send_enabled=True,
        poll_interval=1.0,
        ask_ttl_minutes=30,
    )


def _pending():
    return PendingAsk(
        id=" long-task-id " * 12,
        text="Подтвердить?",
        options=("Да, продолжить", "Нет, остановить"),
        created_at=1234.5,
        token="a:abcd1234:0",
    )


class _Response:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data


class TelegramTest(unittest.TestCase):
    def test_truncate_text_appends_marker(self):
        result = truncate_text("x" * 5000)
        self.assertEqual(len(result), 4096)
        self.assertTrue(result.endswith("… (обрезано)"))

    def test_callback_data_under_64_bytes(self):
        data = make_callback_data(_pending(), 1)
        self.assertLessEqual(len(data.encode("utf-8")), 64)

    def test_callback_data_roundtrip(self):
        pending = _pending()
        data = make_callback_data(pending, 1)
        parsed = parse_callback_data(data)
        self.assertIsNotNone(parsed)
        token, index = parsed
        self.assertEqual(token, data.split(":")[1])
        self.assertEqual(index, 1)
        self.assertIsNone(parse_callback_data("b:abcd1234:1"))
        self.assertIsNone(parse_callback_data("a:abcd1234:x"))

    def test_build_inline_keyboard_has_one_row_per_option(self):
        keyboard = build_inline_keyboard(_pending())
        rows = keyboard["inline_keyboard"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([row[0]["text"] for row in rows], ["Да, продолжить", "Нет, остановить"])
        for row in rows:
            self.assertLessEqual(len(row[0]["callback_data"].encode("utf-8")), 64)

    def test_format_notification_contains_kind_and_text(self):
        text = format_notification(Event(kind="started", text="Сборка", task_id="t1"))
        self.assertIn("Сборка", text)
        self.assertIn("started", text)

    def test_logs_never_contain_token(self):
        transport = HttpTelegramTransport(
            _config(), opener=lambda request, timeout=None: _Response({"ok": True, "result": {}})
        )
        with self.assertLogs("homebot.telegram", level="INFO") as captured:
            transport.send_message(42, "привет")
        self.assertNotIn("SECRET_TOKEN", "\n".join(captured.output))

    def test_retry_after_honored(self):
        sleeps = []
        calls = []

        def opener(request, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                body = b'{"ok":false,"parameters":{"retry_after":2}}'
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, io.BytesIO(body))
            return _Response({"ok": True, "result": {"message_id": 7}})

        transport = HttpTelegramTransport(_config(), sleeper=sleeps.append, opener=opener)
        result = transport.send_message(42, "тест")
        self.assertEqual(sleeps, [2])
        self.assertEqual(result["message_id"], 7)

    def test_fake_transport_records_calls(self):
        fake = FakeTelegramTransport()
        fake.queue_update({"update_id": 1})
        fake.send_message(42, "текст")
        self.assertEqual(fake.sent[0]["text"], "текст")
        self.assertEqual(len(fake.get_updates(None, 1)), 1)


if __name__ == "__main__":
    unittest.main()
