# PURPOSE: резервный режим: телефон работает, только когда ПК выключен.
import json
import logging
import threading
import urllib.request

logger = logging.getLogger("homebot.supervisor")


def _request(url: str, api_key: str, payload=None):
    headers = {"X-HomeBot-Key": api_key}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def pc_alive(pc_url: str, api_key: str) -> bool:
    try:
        result = _request(pc_url.rstrip("/") + "/health", api_key)
        return bool(result.get("ok"))
    except Exception:
        return False


def sync_inbox(pc_url: str, api_key: str, service) -> int:
    messages = service.inbox.unread()
    if not messages:
        return 0
    try:
        result = _request(
            pc_url.rstrip("/") + "/inbox/import",
            api_key,
            {"messages": [{"text": m["text"], "chat_id": m.get("chat_id")} for m in messages]},
        )
    except Exception as exc:
        logger.warning("Не удалось передать ящик на ПК: %s", type(exc).__name__)
        return 0
    for message in messages:
        service.inbox.mark_read(message["id"])
    return int(result.get("imported", 0))


def run_supervisor(config, service, stop_event: threading.Event, state: dict, interval: float = 5.0) -> None:
    pc_url = config.standby_pc_url
    while not stop_event.is_set():
        alive = pc_alive(pc_url, config.api_key)
        if alive and state.get("active"):
            state["active"] = False
            count = sync_inbox(pc_url, config.api_key, service)
            logger.info("ПК снова в сети: телефон уходит в резерв, передано сообщений=%s", count)
        elif not alive and not state.get("active"):
            state["active"] = True
            logger.info("ПК не отвечает: телефон берёт опрос Telegram на себя")
        stop_event.wait(interval)
