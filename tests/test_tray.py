# PURPOSE: тесты трей-контроллера HomeBot без обращений к Win32.
import threading
import unittest
from types import SimpleNamespace

import homebot.tray as tray_module
from homebot.config import Config
from homebot.tray import WM_STATUS, FakeTrayApi, TrayController


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

    def test_run_tray_uses_injected_api(self):
        api = FakeTrayApi()
        closed = []
        poller_started = []
        fake_server = SimpleNamespace(
            shutdown=lambda: None,
            server_close=lambda: closed.append(True),
            serve_forever=lambda poll_interval=0.5: None,
        )
        fake_runtime = SimpleNamespace(
            stop_event=threading.Event(),
            server=fake_server,
            poller=SimpleNamespace(run=lambda: poller_started.append(True)),
            service=SimpleNamespace(status=lambda: {"send_enabled": False, "pending": 0}),
        )
        original = tray_module.build_runtime
        tray_module.build_runtime = lambda config: fake_runtime
        try:
            config = Config(
                bot_token="123:TOKEN",
                chat_id=42,
                api_key="key",
                host="127.0.0.1",
                port=8765,
                send_enabled=False,
                poll_interval=1.0,
                ask_ttl_minutes=30,
            )
            result = tray_module.run_tray(config, api=api)
        finally:
            tray_module.build_runtime = original
        self.assertEqual(result, 0)
        self.assertEqual(api.icons, ["HomeBot"])
        self.assertEqual(closed, [True])
        self.assertEqual(poller_started, [True])

    def test_right_click_opens_menu(self):
        api = FakeTrayApi()
        controller = TrayController(_runtime(), api)
        controller.handle_icon_message(WM_STATUS, 0x0205)
        self.assertEqual(api.menus, [True])

    def test_left_click_shows_status(self):
        api = FakeTrayApi()
        controller = TrayController(_runtime(send_enabled=False, pending=1), api)
        controller.handle_icon_message(WM_STATUS, 0x0201)
        self.assertEqual(len(api.messages), 1)
        self.assertIn("выкл", api.messages[0][0])

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
