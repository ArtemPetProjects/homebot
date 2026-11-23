# PURPOSE: чтение списка устройств из админки роутера A1 FT-35.
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .router_crypto import aes_cbc_decrypt, aes_cbc_encrypt

KEY = b"jiuzhou99jiuzhou"

# Имена из админки роутера записываются через дефис; пользователю удобнее читать с пробелами.
PRETTY_NAMES = {
    "Yandex Station Midi A7XK": "Алиса (Yandex Station Mini)",
}


def pretty_name(name: str) -> str:
    name = name.replace("-", " ").strip()
    return PRETTY_NAMES.get(name, name)


@dataclass(frozen=True)
class RouterDevice:
    name: str
    ip: str
    mac: str
    online: bool
    online_seconds: int


class RouterClient:
    def __init__(self, config: Config, opener: Callable | None = None):
        self.config = config
        self.opener = opener or urllib.request.urlopen
        self.cookie = ""

    def _call(self, command: str, payload: dict | None, cookie: str = "") -> dict[str, Any]:
        body = {
            "cmdType": command,
            "parameter": aes_cbc_encrypt(json.dumps(payload or {}), KEY, KEY),
        }
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = "token=" + cookie
        request = urllib.request.Request(
            self.config.router_url.rstrip("/") + "/method-json",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with self.opener(request, timeout=8) as response:
            parsed = json.loads(response.read().decode("utf-8", errors="replace"))
        if not parsed.get("result"):
            raise RuntimeError(str(parsed.get("resultReason", "router error")))
        return json.loads(aes_cbc_decrypt(str(parsed["parameter"]), KEY, KEY))

    def login(self) -> None:
        data = self._call(
            "LOGIN.SET",
            {"loginUsername": self.config.router_login, "loginPasswd": self.config.router_password},
        )
        self.cookie = str(data.get("cookie", ""))
        if not self.cookie:
            raise RuntimeError("no router cookie")

    def devices(self) -> list[RouterDevice]:
        if not self.cookie:
            self.login()
        data = self._call("LAN_HOST.GET", None, self.cookie)
        result = []
        for host in data.get("lanHostList", []):
            name = str(host.get("lanHostOnlineHostName") or "N/A")
            if name == "N/A":
                name = ""
            else:
                name = pretty_name(name)
            try:
                seconds = int(host.get("lanHostOnlineTime") or 0)
            except (TypeError, ValueError):
                seconds = 0
            result.append(
                RouterDevice(
                    name=name,
                    ip=str(host.get("lanHostIpv4Address") or ""),
                    mac=str(host.get("lanHostMac") or ""),
                    online=bool(host.get("lanHostOnlineState")),
                    online_seconds=seconds,
                )
            )
        return result
