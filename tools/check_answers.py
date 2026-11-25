# PURPOSE: прочитать только новые ответы из HomeBot, включая данные до вопроса.
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homebot.config import load_config  # noqa: E402
from homebot.models import user_answers  # noqa: E402

cfg = load_config(ROOT / ".env")
cursor_path = ROOT / "state" / "agent_cursor.json"
try:
    last_seq = int(json.loads(cursor_path.read_text(encoding="utf-8")).get("last_seq", 0))
except (OSError, ValueError, json.JSONDecodeError):
    last_seq = 0

api_host = "127.0.0.1" if cfg.host == "0.0.0.0" else cfg.host
request = urllib.request.Request(
    f"http://{api_host}:{cfg.port}/answers?since={last_seq}",
    headers={"X-HomeBot-Key": cfg.api_key},
    method="GET",
)
with urllib.request.urlopen(request, timeout=10) as response:
    answers = json.loads(response.read().decode("utf-8")).get("answers", [])

visible = user_answers(answers)
for answer in visible:
    print(
        json.dumps(
            {
                "id": answer.get("id"),
                "seq": answer.get("seq"),
                "option": answer.get("option", "").encode("unicode_escape").decode("ascii"),
                "ts": answer.get("ts"),
                "reason": answer.get("reason"),
            },
            ensure_ascii=True,
        )
    )

if answers:
    # Курсор продвигаем по всем ответам, включая служебные, чтобы они не копились.
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(
        json.dumps({"last_seq": max(int(a["seq"]) for a in answers)}) + "\n",
        encoding="utf-8",
    )
if not visible:
    print("NO_NEW_ANSWERS")
