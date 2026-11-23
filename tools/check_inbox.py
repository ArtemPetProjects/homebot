# PURPOSE: прочитать и отметить прочитанными сообщения пользователя агенту.
import json
import sys
from pathlib import Path

ROOT = Path(r"E:\Projects\HomeBot")
sys.path.insert(0, str(ROOT))

from homebot.inbox import Inbox  # noqa: E402

inbox = Inbox(ROOT / "state")
messages = inbox.unread()
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
    inbox.mark_read(message["id"])
if not messages:
    print("NO_NEW_MESSAGES")
