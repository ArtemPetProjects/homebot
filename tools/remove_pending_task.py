# PURPOSE: удалить активную задачу/вопрос из pending.json по	id или префиксу.
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "pending.json"

if len(sys.argv) < 2:
    print("usage: remove_pending_task.py PREFIX_OR_ID [PREFIX_OR_ID ...]")
    raise SystemExit(2)

prefixes = sys.argv[1:]
data = json.loads(STATE.read_text(encoding="utf-8"))
removed = []
for key in list(data):
    if any(key == p or key.startswith(p) for p in prefixes):
        del data[key]
        removed.append(key)
STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("REMOVED:", removed)
print("REMAINING:", [k for k in data if "CRYPTO" in k])
