# PURPOSE: загрузка и проверка конфигурации из локального .env.
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Config:
    bot_token: str
    chat_id: int
    api_key: str
    host: str
    port: int
    send_enabled: bool
    poll_interval: float
    ask_ttl_minutes: int
    base_url: str = "https://api.telegram.org"
    network_subnet: str = "192.168.1.0/24"

    def validate(self) -> None:
        # Порт открыт только на локальную петлю: это главная защита от доступа из сети.
        if self.host not in ("127.0.0.1", "localhost"):
            raise ValueError("LOCAL_HOST должен быть 127.0.0.1 или localhost")
        if not 1 <= self.port <= 65535:
            raise ValueError("LOCAL_PORT вне диапазона 1..65535")
        if self.chat_id <= 0:
            raise ValueError("TELEGRAM_CHAT_ID должен быть положительным числом")
        if not self.api_key:
            raise ValueError("LOCAL_API_KEY не задан")
        if self.send_enabled and not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN пуст, а отправка включена")
        if self.poll_interval <= 0 or self.ask_ttl_minutes <= 0:
            raise ValueError("Интервал опроса и TTL должны быть положительными")


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def load_config(env_path: Path, environ: Mapping[str, str] | None = None) -> Config:
    values: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    if environ is not None:
        for key in (
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "LOCAL_API_KEY",
            "LOCAL_HOST",
            "LOCAL_PORT",
            "SEND_ENABLED",
            "POLL_INTERVAL_SECONDS",
            "ASK_TTL_MINUTES",
        ):
            if key in environ:
                values[key] = str(environ[key])

    def number(key: str, default: str) -> int:
        try:
            return int(values.get(key, default))
        except ValueError as exc:
            raise ValueError(f"{key} должен быть числом") from exc

    config = Config(
        bot_token=values.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=number("TELEGRAM_CHAT_ID", "0"),
        api_key=values.get("LOCAL_API_KEY", ""),
        host=values.get("LOCAL_HOST", "127.0.0.1"),
        port=number("LOCAL_PORT", "8765"),
        send_enabled=values.get("SEND_ENABLED", "0") == "1",
        poll_interval=float(values.get("POLL_INTERVAL_SECONDS", "1")),
        ask_ttl_minutes=number("ASK_TTL_MINUTES", "30"),
        network_subnet=values.get("NETWORK_SUBNET", "192.168.1.0/24"),
    )
    config.validate()
    return config


def from_environment() -> Config:
    return load_config(Path(__file__).resolve().parent.parent / ".env", os.environ)
