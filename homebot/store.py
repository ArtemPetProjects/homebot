# PURPOSE: атомарное локальное хранилище состояния бота.
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .models import Answer, PendingAsk


class Store:
    def __init__(self, state_dir: Path, clock: Callable[[], float]):
        self.state_dir = state_dir
        self.clock = clock
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._answers = state_dir / "answers.jsonl"
        self._pending = state_dir / "pending.json"
        self._offset = state_dir / "telegram_offset.json"
        self._outbox = state_dir / "outbox.jsonl"
        self._dry_outbox = state_dir / "outbox-dryrun.jsonl"
        self._seq = 0
        for record in self._read_lines(self._answers):
            self._seq = max(self._seq, int(record.get("seq", 0)))

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _read_lines(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        result = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                result.append(data)
        return result

    def _write_lines(self, path: Path, rows: list[dict[str, Any]]) -> None:
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        self._atomic_write(path, text)

    def next_seq(self) -> int:
        with self._lock:
            return self._seq + 1

    def add_answer(self, answer: Answer) -> None:
        with self._lock:
            rows = self._read_lines(self._answers)
            rows.append(answer.to_dict())
            self._write_lines(self._answers, rows)
            self._seq = max(self._seq, answer.seq)

    def answers_since(self, since: int) -> list[Answer]:
        with self._lock:
            rows = self._read_lines(self._answers)
            return [
                Answer.from_dict(row)
                for row in rows
                if int(row.get("seq", 0)) > since
            ]

    def _read_pending(self) -> dict[str, dict[str, Any]]:
        if not self._pending.exists():
            return {}
        try:
            data = json.loads(self._pending.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_pending(self, rows: dict[str, dict[str, Any]]) -> None:
        self._atomic_write(
            self._pending,
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        )

    def save_pending(self, pending: PendingAsk) -> None:
        with self._lock:
            rows = self._read_pending()
            rows[pending.id] = pending.to_dict()
            self._write_pending(rows)

    def get_pending(self, id: str) -> PendingAsk | None:
        with self._lock:
            data = self._read_pending().get(id)
            return PendingAsk.from_dict(data) if data else None

    def find_pending_by_token(self, token: str) -> PendingAsk | None:
        with self._lock:
            for data in self._read_pending().values():
                if data.get("token") == token:
                    return PendingAsk.from_dict(data)
            return None

    def mark_answered(self, id: str) -> None:
        with self._lock:
            rows = self._read_pending()
            if id in rows:
                rows[id]["answered"] = True
                self._write_pending(rows)

    def mark_expired(self, id: str) -> Answer:
        with self._lock:
            rows = self._read_pending()
            if id in rows:
                rows[id]["expired"] = True
                self._write_pending(rows)
            ts = datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds")
            answer = Answer(
                id=id,
                option="__timeout__",
                seq=self.next_seq(),
                ts=ts,
                reason="ttl",
            )
            self.add_answer(answer)
            return answer

    def append_outbox(self, record: dict[str, Any], dry: bool) -> None:
        with self._lock:
            path = self._dry_outbox if dry else self._outbox
            rows = self._read_lines(path)
            rows.append(record)
            self._write_lines(path, rows)

    def undelivered(self) -> list[dict[str, Any]]:
        with self._lock:
            return [row for row in self._read_lines(self._outbox) if not row.get("delivered_at")]

    def mark_delivered(self, event_id: str) -> None:
        with self._lock:
            rows = self._read_lines(self._outbox)
            for row in rows:
                if row.get("event_id") == event_id:
                    row["delivered_at"] = datetime.fromtimestamp(
                        self.clock()
                    ).isoformat(timespec="seconds")
            self._write_lines(self._outbox, rows)

    def load_offset(self) -> int | None:
        with self._lock:
            if not self._offset.exists():
                return None
            try:
                data = json.loads(self._offset.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
            value = data.get("offset") if isinstance(data, dict) else None
            return int(value) if value is not None else None

    def save_offset(self, offset: int) -> None:
        with self._lock:
            self._atomic_write(
                self._offset,
                json.dumps({"offset": int(offset)}) + "\n",
            )

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = list(self._read_pending().values())
            return {
                "pending": sum(
                    1 for row in rows if not row.get("answered") and not row.get("expired")
                ),
                "answered": sum(1 for row in rows if row.get("answered")),
                "expired": sum(1 for row in rows if row.get("expired")),
            }
