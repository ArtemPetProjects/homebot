# PURPOSE: тесты ящика сообщений пользователя к агенту.
import tempfile
import unittest
from pathlib import Path

from homebot.inbox import Inbox


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Inbox(Path(self.tmp.name), clock=lambda: 1000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_read(self):
        record = self.inbox.add("Идея на прогулке", 42)
        unread = self.inbox.unread()
        self.assertEqual(len(unread), 1)
        self.assertEqual(unread[0]["text"], "Идея на прогулке")
        self.inbox.mark_read(record["id"])
        self.assertEqual(self.inbox.unread(), [])

    def test_survives_reload(self):
        self.inbox.add("Сообщение", 42)
        reloaded = Inbox(Path(self.tmp.name), clock=lambda: 1000.0)
        self.assertEqual(len(reloaded.unread()), 1)


if __name__ == "__main__":
    unittest.main()
