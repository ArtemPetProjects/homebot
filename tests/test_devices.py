# PURPOSE: тесты локального реестра устройств.
import tempfile
import unittest
from pathlib import Path

from homebot.domain.devices import Device, DeviceRegistry


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
        self.assertEqual(tv.label, "Android-TV")
        self.assertEqual(self.registry.known("192.168.1.13").label, "VelesCorp")
        alice = self.registry.known("192.168.1.4")
        self.assertEqual(alice.label, "Алиса (Yandex Station Mini)")

    def test_empty_mac_does_not_match_offline_row(self):
        self.assertIsNone(self.registry.known(""))
        device = Device(ip="192.168.1.4", mac="", hostname=None)
        labeled = self.registry.with_labels([device])[0]
        self.assertEqual(labeled.label, "Алиса (Yandex Station Mini)")

    def test_seed_migrates_old_auto_label(self):
        self.registry.remember("192.168.1.4", "", "Устройство 4", "discovered")
        reloaded = DeviceRegistry(self.state, clock=lambda: 1000.0)
        self.assertEqual(
            reloaded.known("192.168.1.4").label,
            "Алиса (Yandex Station Mini)",
        )

    def test_user_label_overrides_seeded_config(self):
        self.registry.remember("192.168.1.1", "aa:bb:cc:dd:ee:ff", "Мой роутер", "user")
        self.assertEqual(self.registry.known("192.168.1.1").label, "Мой роутер")

    def test_remember_sets_first_seen_for_offline_device_without_last_seen(self):
        info = self.registry.remember(
            "192.168.1.99", "aa:bb:cc:00:11:22", "Новое устройство", "router",
            connected=False, last_seen=0.0,
        )
        self.assertEqual(info.first_seen, 1000.0)

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

    def test_unknown_devices_get_auto_label(self):
        device = Device(ip="192.168.1.50", mac="11:22:33:44:55:66", hostname=None)
        labeled = self.registry.with_labels([device])
        self.assertEqual(self.registry.unknowns([device]), [])
        self.assertEqual(labeled[0].label, "Устройство 50")
        self.assertEqual(labeled[0].known, True)

    def test_user_label_overrides_config(self):
        self.registry.remember("192.168.1.2", "aa:bb:cc:dd:ee:ff", "TV", "config")
        self.registry.remember("192.168.1.2", "aa:bb:cc:dd:ee:ff", "Мой телевизор", "user")
        info = self.registry.known("aa:bb:cc:dd:ee:ff")
        self.assertEqual(info.label, "Мой телевизор")
        self.assertEqual(info.source, "user")


if __name__ == "__main__":
    unittest.main()
