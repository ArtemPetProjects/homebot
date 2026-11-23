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

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "label": self.label,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceInfo":
        return cls(
            ip=str(data.get("ip", "")),
            mac=str(data.get("mac", "")),
            label=str(data.get("label", "")),
            source=str(data.get("source", "discovered")),
            updated_at=float(data.get("updated_at", 0)),
        )


class DeviceRegistry:
    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(state_dir) / "devices.json"
        self.clock = clock
        self._lock = threading.RLock()
        self._rows = self._read()

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

    def remember(self, ip: str, mac: str, label: str, source: str) -> DeviceInfo:
        key = _normalize_mac(mac) or f"ip:{ip}"
        info = DeviceInfo(ip=ip, mac=key, label=label, source=source, updated_at=self.clock())
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

    def with_labels(self, devices: list[Device]) -> list[Device]:
        result = []
        for device in devices:
            info = self.known(device.mac) or self.known(device.ip)
            result.append(
                Device(
                    ip=device.ip,
                    mac=device.mac,
                    hostname=device.hostname,
                    alive=device.alive,
                    known=info is not None,
                    label=info.label if info else "",
                    source=info.source if info else "discovered",
                )
            )
        return result

    def unknowns(self, devices: list[Device]) -> list[Device]:
        return [device for device in self.with_labels(devices) if not device.known]
