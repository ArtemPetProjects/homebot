# PURPOSE: прочитать новые сообщения агенту, не перезаписывая ящик целиком.
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homebot.inbox import Inbox  # noqa: E402

state = ROOT / "state"
cursor_path = state / "agent_inbox_cursor.json"
try:
    seen = set(json.loads(cursor_path.read_text(encoding="utf-8")).get("seen_ids", []))
except (OSError, ValueError, json.JSONDecodeError):
    seen = set()

messages = [item for item in Inbox(state).unread() if item.get("id") not in seen]
for message in messages:
    print(
        json.dumps(
            {
                "id": message.get("id"),
                "text": message.get("text", "").encode("unicode_escape").decode("ascii"),
                "ts": message.get("ts"),
            },
            ensure_ascii=True,
        )
    )

if messages:
    seen.update(str(item["id"]) for item in messages)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cursor_path.with_name(cursor_path.name + ".tmp")
    tmp.write_text(json.dumps({"seen_ids": sorted(seen)}) + "\n", encoding="utf-8")
    tmp.replace(cursor_path)
else:
    print("NO_NEW_MESSAGES")
