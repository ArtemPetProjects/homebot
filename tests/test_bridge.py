# PURPOSE: тесты локального HTTP-bridge с авторизацией.
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from homebot.bridge import make_server
from homebot.config import Config
from homebot.models import Ask
from homebot.service import HomeBotService
from homebot.store import Store
from homebot.telegram import FakeTelegramTransport


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(
            bot_token="123:TOKEN",
            chat_id=42,
            api_key="test-key",
            host="127.0.0.1",
            port=8765,
            send_enabled=False,
            poll_interval=1.0,
            ask_ttl_minutes=30,
        )
        store = Store(Path(self.tmp.name), clock=lambda: 1000.0)
        self.service = HomeBotService(
            self.config, store, FakeTelegramTransport(), lambda: 1000.0
        )
        self.server = make_server(self.config, self.service, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _request(self, method, path, body=None, headers=None, key="test-key", raw=None):
        headers = dict(headers or {})
        if key is not None:
            headers["X-HomeBot-Key"] = key
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_missing_key_returns_401(self):
        status, body = self._request("GET", "/health", key=None)
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])

    def test_wrong_key_returns_401(self):
        status, _ = self._request("GET", "/health", key="wrong")
        self.assertEqual(status, 401)

    def test_health_returns_flags_only(self):
        status, body = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn("send_enabled", body)
        self.assertNotIn("bot_token", body)
        self.assertNotIn("api_key", body)

    def test_notify_success_path(self):
        status, body = self._request(
            "POST", "/notify", {"kind": "info", "text": "привет", "task_id": "t1"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["delivered"])

    def test_rejects_body_over_64kb(self):
        status, _ = self._request(
            "POST",
            "/notify",
            {"kind": "info", "text": "x" * 70000, "task_id": "t2"},
        )
        self.assertEqual(status, 413)

    def test_rejects_wrong_content_type(self):
        status, _ = self._request(
            "POST",
            "/notify",
            raw=b"not json",
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)

    def test_invalid_event_returns_400(self):
        status, _ = self._request(
            "POST", "/notify", {"kind": "bogus", "text": "x", "task_id": "t3"}
        )
        self.assertEqual(status, 400)

    def test_answers_since_returns_answers(self):
        self.service.ask(Ask("q1", "Продолжить?", ("Да", "Нет")))
        status, body = self._request("GET", "/answers?since=0")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["answers"]), 1)
        self.assertEqual(body["answers"][0]["option"], "__undelivered__")


if __name__ == "__main__":
    unittest.main()
