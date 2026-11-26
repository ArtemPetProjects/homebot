# PURPOSE: тесты резервного режима телефона.
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import homebot.api.supervisor as supervisor


class FakeStop:
    def __init__(self, ticks):
        self.ticks = ticks
        self.count = 0
        self.is_set_value = False

    def is_set(self):
        return self.is_set_value

    def wait(self, interval):
        self.count += 1
        if self.count >= self.ticks:
            self.is_set_value = True


class SupervisorTest(unittest.TestCase):
    def test_phone_takes_over_when_pc_off(self):
        state = {"active": False}
        stop = FakeStop(4)
        config = SimpleNamespace(standby_pc_url="http://192.168.1.13:8765", api_key="k")
        service = SimpleNamespace(inbox=SimpleNamespace(unread=lambda: []))
        with patch.object(supervisor, "pc_alive", side_effect=[True, False, False, True]):
            with patch.object(supervisor, "sync_inbox", return_value=0):
                supervisor.run_supervisor(config, service, stop, state, interval=0)
        self.assertFalse(state["active"])

    def test_phone_stays_standby_while_pc_on(self):
        state = {"active": False}
        stop = FakeStop(2)
        config = SimpleNamespace(standby_pc_url="http://192.168.1.13:8765", api_key="k")
        service = SimpleNamespace(inbox=SimpleNamespace(unread=lambda: []))
        with patch.object(supervisor, "pc_alive", return_value=True):
            supervisor.run_supervisor(config, service, stop, state, interval=0)
        self.assertFalse(state["active"])


if __name__ == "__main__":
    unittest.main()
