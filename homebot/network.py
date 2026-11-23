# PURPOSE: чтение ARP и активный ping-обзор устройств домашней сети.
import ipaddress
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
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


def _normalize_mac(mac: str) -> str:
    return mac.replace("-", ":").lower()


def _is_unicast_mac(mac: str) -> bool:
    first = mac.replace(":", "-").split("-")[0]
    try:
        return not (int(first, 16) & 1)
    except ValueError:
        return False


def _usable_ip(ip: str, network) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        address in network
        and not address.is_multicast
        and address != network.broadcast_address
        and str(address) != "255.255.255.255"
    )


def _hidden_subprocess_kwargs() -> dict:
    # Без этого каждый ping из pythonw показывает мигающее окно консоли.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {"creationflags": 0x08000000, "startupinfo": startup}


def ping_probe(ip: str, timeout: float = 0.2) -> bool:
    """Проверить доступность адреса одним ICMP-пакетом, без изменения сети."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(max(1, int(timeout * 1000))), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def scan_network(
    subnet: str,
    arp_provider: Callable[[], str] | None = None,
    resolver: Callable[[str], str | None] | None = None,
    timeout: float = 0.12,
    probe: Callable[[str], bool] | None = None,
) -> list[Device]:
    if arp_provider is None:

        def arp_provider():  # noqa: F811
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=10, check=False,
                **_hidden_subprocess_kwargs(),
            )
            return result.stdout

    if resolver is None:
        import socket

        def resolver(ip: str) -> str | None:  # noqa: F811
            try:
                return socket.gethostbyaddr(ip)[0]
            except (OSError, UnicodeError):
                return None

    network = ipaddress.ip_network(subnet, strict=False)

    def parse_arp() -> dict[str, str]:
        rows: dict[str, str] = {}
        for line in arp_provider().splitlines():
            match = ARP_LINE.match(line)
            if not match:
                continue
            ip, mac, kind = match.groups()
            if _usable_ip(ip, network) and _is_unicast_mac(mac) and kind.lower() != "invalid":
                rows[ip] = mac
        return rows

    arp_rows = parse_arp()
    alive = set(arp_rows)
    if probe is not None:
        hosts = [str(host) for host in network.hosts()]
        with ThreadPoolExecutor(max_workers=96) as pool:
            results = list(pool.map(probe, hosts))
        for ip, reachable in zip(hosts, results):
            if reachable and _usable_ip(ip, network):
                alive.add(ip)
        # Ping наполняет ARP-кэш — перечитываем его, чтобы узнать MAC новых устройств.
        arp_rows = parse_arp()

    devices = []
    for ip in sorted(alive, key=lambda value: tuple(int(part) for part in value.split("."))):
        try:
            hostname = resolver(ip)
        except Exception:
            hostname = None
        if hostname and hostname.lower() == ip:
            hostname = None
        devices.append(
            Device(
                ip=ip,
                mac=arp_rows.get(ip, ""),
                hostname=hostname,
                alive=True,
                known=False,
            )
        )
    return devices
