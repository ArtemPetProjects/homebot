# PURPOSE: локальный HTTP-bridge: только loopback, обязательный ключ, JSON.
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from .config import Config
from .models import Ask, Event
from .service import HomeBotService

MAX_BODY_BYTES = 65536


class BodyTooLarge(Exception):
    pass


class WrongContentType(Exception):
    pass


def validate_auth(headers: Mapping[str, str], api_key: str) -> bool:
    supplied = None
    for key, value in headers.items():
        if key.lower() == "x-homebot-key":
            supplied = value
    if not supplied:
        return False
    # Константное время сравнения: не даём утечь ключ по времени ответа.
    return hmac.compare_digest(str(supplied), api_key)


def read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int = MAX_BODY_BYTES) -> dict | None:
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except ValueError:
        return None
    if length > max_bytes:
        raise BodyTooLarge()
    content_type = handler.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        raise WrongContentType()
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def make_server(
    config: Config, service: HomeBotService, port: int | None = None
) -> ThreadingHTTPServer:
    api_key = config.api_key

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            # URL может содержать чувствительные параметры — в лог не пишем ничего.
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if validate_auth(self.headers, api_key):
                return True
            self._send(401, {"ok": False, "error": "Нет или неверный ключ доступа"})
            return False

        def do_GET(self) -> None:
            if not self._authorized():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                status = service.status()
                self._send(
                    200,
                    {
                        "ok": True,
                        "send_enabled": status["send_enabled"],
                        "pending": status["pending"],
                    },
                )
                return
            if parsed.path == "/status":
                self._send(200, service.status())
                return
            if parsed.path == "/answers":
                since_raw = parse_qs(parsed.query).get("since", ["0"])[0]
                try:
                    since = int(since_raw)
                except ValueError:
                    self._send(400, {"ok": False, "error": "since должен быть числом"})
                    return
                self._send(200, service.answers_since(since))
                return
            self._send(404, {"ok": False, "error": "Неизвестный маршрут"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            parsed = urlparse(self.path)
            if parsed.path not in ("/notify", "/ask"):
                self._send(404, {"ok": False, "error": "Неизвестный маршрут"})
                return
            try:
                body = read_json_body(self)
            except BodyTooLarge:
                self._send(413, {"ok": False, "error": "Тело слишком большое"})
                return
            except WrongContentType:
                self._send(415, {"ok": False, "error": "Нужен Content-Type: application/json"})
                return
            if body is None:
                self._send(400, {"ok": False, "error": "Некорректный JSON"})
                return
            try:
                if parsed.path == "/notify":
                    event = Event(
                        kind=str(body.get("kind", "")),
                        text=str(body.get("text", "")),
                        task_id=str(body.get("task_id", "")),
                    )
                    event.validate()
                    self._send(200, service.notify(event))
                else:
                    options = body.get("options")
                    request = Ask(
                        id=str(body.get("id", "")),
                        text=str(body.get("text", "")),
                        options=tuple(str(item) for item in options) if isinstance(options, list) else (),
                    )
                    request.validate()
                    self._send(200, service.ask(request))
            except ValueError as exc:
                self._send(400, {"ok": False, "error": str(exc)})

    host = config.host
    bind_port = config.port if port is None else port
    server = ThreadingHTTPServer((host, bind_port), Handler)
    server.daemon_threads = True
    return server
