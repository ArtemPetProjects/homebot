# PURPOSE: локальный реестр подписей устройств домашней сети.
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .network import Device, _normalize_mac


@dataclass(frozen=True)
class DeviceInfo:
    ip: str
    mac: str
    label: str
    source: str
    updated_at: float
    connected: bool = False
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "label": self.label,
            "source": self.source,
            "updated_at": self.updated_at,
            "connected": self.connected,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceInfo":
        return cls(
            ip=str(data.get("ip", "")),
            mac=str(data.get("mac", "")),
            label=str(data.get("label", "")),
            source=str(data.get("source", "discovered")),
            updated_at=float(data.get("updated_at", 0)),
            connected=bool(data.get("connected", False)),
            last_seen=float(data.get("last_seen", 0)),
        )


class DeviceRegistry:
    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(state_dir) / "devices.json"
        self.clock = clock
        self._lock = threading.RLock()
        self._rows = self._read()
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        # Список из админки роутера A1 FT-35, снимок пользователя от 23.11.2026 13:41.
        defaults = [
            ("192.168.1.1", "", "Роутер", True),
            ("192.168.1.2", "78:53:33:4a:40:64", "Android-TV", True),
            ("192.168.1.4", "3c:0b:4f:c8:21:ee", "Алиса (Yandex Station Mini)", True),
            ("192.168.1.8", "86:0b:e1:94:a9:a6", "POCO X7 Pro", True),
            ("192.168.1.13", "94:4d:e8:06:c4:5a", "VelesCorp", True),
            ("192.168.1.15", "a6:99:0f:e6:b6:eb", "Redmi Note 11S", True),
            ("192.168.1.17", "f2:84:0b:fa:e9:40", "POCO X8 Pro Max", True),
            ("", "60:3d:61:65:49:4a", "Устройство 60:3D", False),
            ("", "04:5f:a6:e5:30:94", "Устройство 04:5F", False),
            ("", "d2:b3:85:e5:26:c0", "POCO X7 Pro (офлайн)", False),
            ("", "76:23:fa:41:35:4a", "POCO X8 Pro Max (офлайн)", False),
            ("", "de:ef:1d:c1:48:53", "Redmi Note 11S (офлайн)", False),
            ("", "ac:ba:c0:b4:a2:86", "Устройство AC:BA", False),
        ]
        now = self.clock()
        changed = False
        for ip, mac, label, connected in defaults:
            known_mac = _normalize_mac(mac) if mac else ""
            if any(
                DeviceInfo.from_dict(row).ip == ip or
                (known_mac and DeviceInfo.from_dict(row).mac == known_mac)
                for row in self._rows.values()
            ):
                continue
            key = known_mac or ("ip:" + ip if ip else "mac:unknown")
            self._rows[key] = DeviceInfo(
                ip=ip,
                mac=known_mac,
                label=label,
                source="config",
                updated_at=0,
                connected=connected,
                last_seen=now if connected else 0.0,
            ).to_dict()
            changed = True
        if changed:
            self._write()

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, self.path)

    def known(self, ip_or_mac: str) -> DeviceInfo | None:
        key = _normalize_mac(ip_or_mac)
        with self._lock:
            for data in self._rows.values():
                info = DeviceInfo.from_dict(data)
                if info.mac and info.mac == key:
                    return info
                if info.ip == ip_or_mac:
                    return info
            return None

    def remember(
        self,
        ip: str,
        mac: str,
        label: str,
        source: str,
        connected: bool = True,
        last_seen: float | None = None,
    ) -> DeviceInfo:
        key = _normalize_mac(mac) or f"ip:{ip}"
        info = DeviceInfo(
            ip=ip,
            mac=key,
            label=label,
            source=source,
            updated_at=self.clock(),
            connected=connected,
            last_seen=self.clock() if last_seen is None else last_seen,
        )
        with self._lock:
            existing = self._rows.get(key)
            if existing and DeviceInfo.from_dict(existing).source == "user" and source != "user":
                return DeviceInfo.from_dict(existing)
            # Одна запись на IP: старая запись с другим MAC не должна затенять новую подпись.
            stale = [row_key for row_key, row in self._rows.items()
                     if row_key != key and DeviceInfo.from_dict(row).ip == ip]
            for row_key in stale:
                del self._rows[row_key]
            self._rows[key] = info.to_dict()
            self._write()
            return info

    def all_devices(self) -> list[DeviceInfo]:
        with self._lock:
            return [DeviceInfo.from_dict(row) for row in self._rows.values()]

    @staticmethod
    def _auto_label(device: Device) -> str:
        prefix = device.mac.replace("-", ":").upper()[:8]
        vendors = {
            "5C:94:62": "Xiaomi",
            "78:53:33": "Xiaomi",
            "FC:F5:C4": "Xiaomi",
            "A4:83:E7": "Xiaomi",
            "E4:5F:01": "Espressif",
            "A0:CE:C8": "Espressif",
            "3C:71:BF": "Amazon",
            "B8:27:EB": "Raspberry Pi",
            "DC:A6:32": "Raspberry Pi",
        }
        vendor = next((name for mac_prefix, name in vendors.items() if prefix.startswith(mac_prefix)), None)
        return f"Устройство {vendor}" if vendor else f"Устройство {device.ip.rsplit('.', 1)[-1]}"

    def with_labels(self, devices: list[Device]) -> list[Device]:
        result = []
        for device in devices:
            info = self.known(device.mac) or self.known(device.ip)
            if info is None:
                # Неизвестное устройство подписываем сами — пользователь не должен искать IP.
                info = self.remember(
                    device.ip, device.mac, self._auto_label(device), "discovered"
                )
            result.append(
                Device(
                    ip=device.ip,
                    mac=device.mac,
                    hostname=device.hostname,
                    alive=device.alive,
                    known=info is not None,
                    label=info.label if info else "",
                    source=info.source if info else "discovered",
                    connected=info.connected if info else device.connected,
                    last_seen=info.last_seen if info else device.last_seen,
                )
            )
        return result

    def observe(self, devices: list[Device], now: float | None = None) -> None:
        """Отметить найденные устройства как подключённые и обновить last_seen."""
        moment = self.clock() if now is None else now
        seen = set()
        with self._lock:
            for device in devices:
                key = _normalize_mac(device.mac) or f"ip:{device.ip}"
                seen.add(key)
                row = self._rows.get(key)
                if row is None:
                    continue
                row["connected"] = True
                row["last_seen"] = moment
                if not row.get("ip") and device.ip:
                    row["ip"] = device.ip
            for key, row in self._rows.items():
                if key not in seen:
                    row["connected"] = False
            self._write()

    def unknowns(self, devices: list[Device]) -> list[Device]:
        return [device for device in self.with_labels(devices) if not device.known]
