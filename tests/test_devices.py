# PURPOSE: тесты локального реестра устройств.
import tempfile
import unittest
from pathlib import Path

from homebot.devices import Device, DeviceRegistry


class DevicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.registry = DeviceRegistry(self.state, clock=lambda: 1000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_defaults_seeded(self):
        router = self.registry.known("192.168.1.1")
        self.assertEqual(router.label, "Роутер")
        self.assertEqual(router.source, "config")
        tv = self.registry.known("192.168.1.2")
        self.assertEqual(tv.label, "Телевизор")
        self.assertIn("не подтверждено", self.registry.known("192.168.1.13").label)

    def test_user_label_overrides_seeded_config(self):
        self.registry.remember("192.168.1.1", "aa:bb:cc:dd:ee:ff", "Мой роутер", "user")
        self.assertEqual(self.registry.known("192.168.1.1").label, "Мой роутер")

    def test_remember_and_reload(self):
        self.registry.remember("192.168.1.9", "aa:bb:cc:dd:ee:ff", "Телефон", "user")
        reloaded = DeviceRegistry(self.state, clock=lambda: 1000.0)
        info = reloaded.known("192.168.1.9")
        self.assertEqual(info.label, "Телефон")
        self.assertEqual(info.source, "user")

    def test_label_follows_mac_after_ip_change(self):
        self.registry.remember("192.168.1.9", "aa:bb:cc:dd:ee:ff", "Телефон", "user")
        self.registry.remember("192.168.1.10", "aa:bb:cc:dd:ee:ff", "Телефон", "user")
        self.assertIsNone(self.registry.known("192.168.1.9"))
        self.assertEqual(self.registry.known("192.168.1.10").label, "Телефон")

    def test_unknown_devices_marked(self):
        device = Device(ip="192.168.1.50", mac="11:22:33:44:55:66", hostname=None)
        self.assertEqual(self.registry.unknowns([device]), [device])

    def test_user_label_overrides_config(self):
        self.registry.remember("192.168.1.2", "aa:bb:cc:dd:ee:ff", "TV", "config")
        self.registry.remember("192.168.1.2", "aa:bb:cc:dd:ee:ff", "Мой телевизор", "user")
        info = self.registry.known("aa:bb:cc:dd:ee:ff")
        self.assertEqual(info.label, "Мой телевизор")
        self.assertEqual(info.source, "user")


if __name__ == "__main__":
    unittest.main()
