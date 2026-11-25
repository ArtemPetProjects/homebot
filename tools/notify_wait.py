# PURPOSE: отправить в Telegram итог и вопрос с вариантами при остановке/ожидании.
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homebot.config import load_config  # noqa: E402

if len(sys.argv) < 4:
    print("usage: notify_wait.py TASK_ID TEXT OPTION1 [OPTION2 ...]")
    raise SystemExit(2)

task_id, text, *options = sys.argv[1:]
cfg = load_config(ROOT / ".env")
headers = {"X-HomeBot-Key": cfg.api_key, "Content-Type": "application/json"}
api_host = "127.0.0.1" if cfg.host == "0.0.0.0" else cfg.host
base = f"http://{api_host}:{cfg.port}"


def call(path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


stamp = str(int(time.time()))
print(call("/notify", {"kind": "waiting", "task_id": task_id, "text": text}))
print(
    call(
        "/ask",
        {
            "id": f"wait-{task_id}-{stamp}",
            "text": "Что делаем дальше?",
            "options": options[:8],
        },
    )
)
