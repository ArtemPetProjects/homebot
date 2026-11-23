# PURPOSE: тесты загрузки конфигурации HomeBot.
import tempfile
import unittest
from pathlib import Path

from homebot.config import generate_api_key, load_config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".env"
        self.values = {
            "TELEGRAM_BOT_TOKEN": "123:token",
            "TELEGRAM_CHAT_ID": "12345",
            "LOCAL_API_KEY": "local-key",
            "LOCAL_HOST": "127.0.0.1",
            "LOCAL_PORT": "8765",
            "SEND_ENABLED": "0",
            "POLL_INTERVAL_SECONDS": "1",
            "ASK_TTL_MINUTES": "30",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, **overrides):
        values = dict(self.values)
        values.update(overrides)
        self.path.write_text(
            "\n".join(f"{k}={v}" for k, v in values.items()) + "\n",
            encoding="utf-8",
        )
        return self.path

    def test_load_config_reads_all_keys(self):
        config = load_config(self._write())
        self.assertEqual(config.chat_id, 12345)
        self.assertEqual(config.port, 8765)
        self.assertFalse(config.send_enabled)
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.ask_ttl_minutes, 30)
        self.assertEqual(config.base_url, "https://api.telegram.org")

    def test_rejects_non_loopback_host(self):
        with self.assertRaises(ValueError):
            load_config(self._write(LOCAL_HOST="host.invalid"))

    def test_rejects_lan_bind(self):
        for host in ("0.0.0.0", "192.168.1.10", "::"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                load_config(self._write(LOCAL_HOST=host))

    def test_rejects_empty_api_key(self):
        with self.assertRaises(ValueError):
            load_config(self._write(LOCAL_API_KEY=""))

    def test_generate_api_key_length_at_least_32(self):
        self.assertGreaterEqual(len(generate_api_key()), 32)


if __name__ == "__main__":
    unittest.main()
