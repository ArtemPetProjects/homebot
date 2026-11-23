# PURPOSE: локальный ящик сообщений от пользователя к агенту.
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


class Inbox:
    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(state_dir) / "agent_inbox.jsonl"
        self.clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                result.append(data)
        return result

    def _write(self, rows: list[dict[str, Any]]) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def add(self, text: str, chat_id: int) -> dict[str, Any]:
        record = {
            "id": f"inbox-{int(self.clock() * 1000)}",
            "text": text,
            "chat_id": chat_id,
            "ts": self.clock(),
            "read": False,
        }
        with self._lock:
            rows = self._read()
            rows.append(record)
            self._write(rows)
        return record

    def unread(self) -> list[dict[str, Any]]:
        with self._lock:
            return [row for row in self._read() if not row.get("read")]

    def mark_read(self, message_id: str) -> None:
        with self._lock:
            rows = self._read()
            for row in rows:
                if row.get("id") == message_id:
                    row["read"] = True
            self._write(rows)
