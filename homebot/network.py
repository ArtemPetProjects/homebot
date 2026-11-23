# PURPOSE: чтение таблицы ARP для списка устройств домашней сети.
import re
from dataclasses import dataclass
from typing import Callable

ARP_LINE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})\s+(\w+)"
)


@dataclass(frozen=True)
class Device:
    ip: str
    mac: str
    hostname: str | None
    alive: bool = True
    known: bool = False
    label: str = ""
    source: str = "discovered"


def _in_subnet(ip: str, subnet: str) -> bool:
    prefix = subnet.rsplit("/", 1)[0].rsplit(".", 1)[0] + "."
    return ip.startswith(prefix)


def _normalize_mac(mac: str) -> str:
    return mac.replace("-", ":").lower()


def scan_network(
    subnet: str,
    arp_provider: Callable[[], str] | None = None,
    resolver: Callable[[str], str | None] | None = None,
    timeout: float = 0.2,
) -> list[Device]:
    if arp_provider is None:
        import subprocess

        def arp_provider():  # noqa: F811
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=10, check=False
            )
            return result.stdout

    if resolver is None:
        import socket

        def resolver(ip: str) -> str | None:  # noqa: F811
            try:
                return socket.gethostbyaddr(ip)[0]
            except (OSError, UnicodeError):
                return None

    devices = []
    seen = set()
    for line in arp_provider().splitlines():
        match = ARP_LINE.match(line)
        if not match:
            continue
        ip, mac, kind = match.groups()
        if not _in_subnet(ip, subnet) or kind.lower() == "invalid":
            continue
        if ip in seen:
            continue
        seen.add(ip)
        try:
            hostname = resolver(ip)
        except Exception:
            hostname = None
        if hostname and hostname.lower() == ip:
            hostname = None
        devices.append(
            Device(ip=ip, mac=mac, hostname=hostname, alive=True, known=False)
        )
    return devices
