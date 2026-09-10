"""Bounded atomic append-only AEGIS decision audit ledger."""

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

from .models import AegisDecision


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "logs" / "aegis_decisions.json"
_LOCK = Lock()


class AegisLedgerError(RuntimeError):
    pass


class AegisDecisionLedger:
    def __init__(self, path=DEFAULT_PATH, max_records=1000):
        self.path = Path(path); self.max_records = int(max_records)

    def load(self):
        if not self.path.exists(): return {"schema_version": 1, "decisions": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("schema_version") != 1 or not isinstance(value.get("decisions"), list): raise ValueError
            return value
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise AegisLedgerError("AEGIS decision ledger is unavailable or corrupt") from error

    def append(self, decision: AegisDecision):
        with _LOCK:
            document = self.load(); rows = document["decisions"]
            if any(row.get("decision_id") == decision.decision_id for row in rows): return False
            rows.append(decision.to_dict())
            if len(rows) > self.max_records: document["decisions"] = rows[-self.max_records:]
            self._write(document); return True

    def history(self, limit=25):
        bounded = max(1, min(int(limit), 100))
        return list(reversed(self.load()["decisions"][-bounded:]))

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
