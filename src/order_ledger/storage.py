"""One atomic, append-only, corruption-aware order/fill document."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "logs" / "order_fill_ledger.json"


class LedgerUnavailable(RuntimeError): pass
class LedgerCorrupt(LedgerUnavailable): pass


class OrderFillStore:
    VERSION = 1

    def __init__(self, path=DEFAULT_PATH, max_terminal_orders=5000):
        self.path = Path(path)
        self.max_terminal_orders = int(max_terminal_orders)
        self.lock = Lock()

    @classmethod
    def empty(cls):
        return {"schema_version": cls.VERSION, "intents": [], "events": [], "fills": [], "fill_applications": [], "cost_schedules": []}

    def load(self):
        if not self.path.exists(): return self.empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("schema_version") != self.VERSION or any(not isinstance(value.get(key), list) for key in ("intents", "events", "fills", "cost_schedules")):
                raise ValueError("invalid ledger schema")
            value.setdefault("fill_applications", [])
            if not isinstance(value["fill_applications"], list): raise ValueError("invalid fill application schema")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise LedgerCorrupt("order/fill ledger is corrupt or schema-invalid") from error

    def update(self, operation):
        with self.lock:
            document = self.load()
            changed, result = operation(document)
            if changed:
                self._bound_terminal_history(document)
                self._write(document)
            return result

    def _bound_terminal_history(self, document):
        terminal = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED"}
        latest = {}
        for event in document["events"]:
            latest[event.get("intent_id")] = event.get("to_state")
        terminal_ids = [row["intent_id"] for row in document["intents"] if latest.get(row["intent_id"]) in terminal]
        excess = max(0, len(terminal_ids) - self.max_terminal_orders)
        if not excess: return
        remove = set(terminal_ids[:excess])
        document["intents"] = [row for row in document["intents"] if row["intent_id"] not in remove]
        document["events"] = [row for row in document["events"] if row["intent_id"] not in remove]
        document["fills"] = [row for row in document["fills"] if row["intent_id"] not in remove]
        document["fill_applications"] = [row for row in document["fill_applications"] if row["intent_id"] not in remove]

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
