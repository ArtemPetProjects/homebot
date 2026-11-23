# PURPOSE: тесты сканера локальной сети с подменёнными источниками данных.
import unittest

from homebot.network import scan_network

ARP_WITH_BROADCAST = """Interface: 192.168.1.13 --- 0x8
  192.168.1.1           5c-94-62-12-bc-39     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.2             01-00-5e-00-00-02     static
  192.168.1.42          aa-bb-cc-dd-ee-01     dynamic
"""

ARP = """Interface: 192.168.1.13 --- 0x8
  Internet Address      Physical Address      Type
  192.168.1.1           00-11-22-33-44-55     dynamic
  192.168.1.2           aa-bb-cc-dd-ee-ff     dynamic
  192.168.2.5           11-22-33-44-55-66     dynamic
  not-an-ip             ff-ff-ff-ff-ff-ff     dynamic
"""


class NetworkTest(unittest.TestCase):
    def test_parses_arp_output(self):
        devices = scan_network(
            "192.168.1.0/24",
            arp_provider=lambda: ARP,
            resolver=lambda ip: "tv" if ip == "192.168.1.2" else None,
        )
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].ip, "192.168.1.1")
        self.assertEqual(devices[0].mac, "00-11-22-33-44-55")
        self.assertEqual(devices[1].hostname, "tv")
        self.assertFalse(devices[1].known)
        self.assertTrue(devices[1].alive)

    def test_filters_broadcast_and_multicast(self):
        devices = scan_network(
            "192.168.1.0/24",
            arp_provider=lambda: ARP_WITH_BROADCAST,
            resolver=lambda ip: None,
        )
        ips = [device.ip for device in devices]
        self.assertEqual(ips, ["192.168.1.1", "192.168.1.42"])

    def test_probe_collects_alive_host(self):
        devices = scan_network(
            "192.168.1.0/24",
            arp_provider=lambda: ARP_WITH_BROADCAST,
            resolver=lambda ip: None,
            probe=lambda ip: ip == "192.168.1.60",
        )
        ips = [device.ip for device in devices]
        self.assertIn("192.168.1.60", ips)

    def test_unreachable_hosts_excluded(self):
        devices = scan_network(
            "192.168.1.0/24", arp_provider=lambda: "", resolver=lambda ip: None
        )
        self.assertEqual(devices, [])

    def test_resolver_failure_is_tolerated(self):
        def bad_resolver(ip):
            raise OSError("no reverse dns")

        devices = scan_network(
            "192.168.1.0/24",
            arp_provider=lambda: ARP,
            resolver=bad_resolver,
        )
        self.assertEqual(len(devices), 2)
        self.assertIsNone(devices[0].hostname)


if __name__ == "__main__":
    unittest.main()
