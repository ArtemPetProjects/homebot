# PURPOSE: сквозная проверка работы бота без обращений к Telegram.
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from homebot.bridge import make_server
from homebot.config import Config
from homebot.service import HomeBotService
from homebot.store import Store
from homebot.telegram import FakeTelegramTransport


class E2EDryRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
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
        self.transport = FakeTelegramTransport()
        store = Store(self.state, clock=lambda: 1000.0)
        service = HomeBotService(self.config, store, self.transport, lambda: 1000.0)
        self.server = make_server(self.config, service, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-HomeBot-Key": "test-key"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_build_runtime_uses_fake_in_dryrun(self):
        from homebot.main import build_runtime

        runtime = build_runtime(self.config, state_dir=self.state)
        try:
            self.assertIsInstance(runtime.transport, FakeTelegramTransport)
            self.assertFalse(runtime.config.send_enabled)
            self.assertEqual(runtime.service.status()["send_enabled"], False)
        finally:
            runtime.stop_event.set()
            runtime.server.server_close()

    def test_dryrun_end_to_end(self):
        notify = self._request(
            "POST", "/notify", {"kind": "done", "text": "готово", "task_id": "t1"}
        )
        self.assertTrue(notify["ok"])
        self.assertFalse(notify["delivered"])

        ask = self._request(
            "POST",
            "/ask",
            {"id": "q1", "text": "Продолжить?", "options": ["Да", "Нет"]},
        )
        self.assertTrue(ask["ok"])
        self.assertFalse(ask["delivered"])

        answers = self._request("GET", "/answers?since=0")
        self.assertEqual(answers["answers"][0]["option"], "__undelivered__")

        self.assertEqual(self.transport.sent, [])
        dry = (self.state / "outbox-dryrun.jsonl").read_text(encoding="utf-8")
        self.assertIn("готово", dry)
        self.assertIn("Продолжить?", dry)


if __name__ == "__main__":
    unittest.main()
