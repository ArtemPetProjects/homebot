# PURPOSE: тесты трей-контроллера HomeBot без обращений к Win32.
import threading
import unittest
from types import SimpleNamespace

from homebot.tray import FakeTrayApi, TrayController


class _Server:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


def _runtime(send_enabled=True, pending=2):
    return SimpleNamespace(
        stop_event=threading.Event(),
        server=_Server(),
        service=SimpleNamespace(
            status=lambda: {
                "ok": True,
                "send_enabled": send_enabled,
                "pending": pending,
            }
        ),
    )


class TrayTest(unittest.TestCase):
    def test_start_adds_icon(self):
        api = FakeTrayApi()
        controller = TrayController(_runtime(), api)
        controller.start()
        self.assertEqual(api.icons, ["HomeBot"])

    def test_status_text(self):
        api = FakeTrayApi()
        controller = TrayController(_runtime(send_enabled=True, pending=3), api)
        text = controller.status_text()
        self.assertIn("вкл", text)
        self.assertIn("Ожидают: 3", text)

    def test_exit_stops_runtime(self):
        api = FakeTrayApi()
        runtime = _runtime()
        controller = TrayController(runtime, api)
        controller.exit()
        self.assertTrue(runtime.stop_event.is_set())
        self.assertEqual(api.removed, [True])
        deadline = 2
        while runtime.server.shutdown_calls == 0 and deadline > 0:
            import time

            time.sleep(0.01)
            deadline -= 0.01
        self.assertEqual(runtime.server.shutdown_calls, 1)


if __name__ == "__main__":
    unittest.main()
