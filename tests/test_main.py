# PURPOSE: тесты безопасной остановки процесса.
import threading
import time
import unittest
from types import SimpleNamespace

from homebot.main import make_stop_handler


class _Server:
    def __init__(self):
        self.calls = 0

    def shutdown(self):
        self.calls += 1


class MainTest(unittest.TestCase):
    def test_stop_handler_returns_without_blocking(self):
        server = _Server()
        runtime = SimpleNamespace(stop_event=threading.Event(), server=server)
        handler = make_stop_handler(runtime)
        started = time.time()
        handler(15, None)
        self.assertLess(time.time() - started, 0.5)
        self.assertTrue(runtime.stop_event.is_set())
        deadline = time.time() + 2
        while server.calls == 0 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.calls, 1)


if __name__ == "__main__":
    unittest.main()
