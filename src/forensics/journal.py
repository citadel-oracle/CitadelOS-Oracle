"""Tamper-evident append-only JSONL evidence journal.

The journal is deliberately independent from trading state. A write failure is
reported to its caller and must never alter a production decision.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


GENESIS_HASH = "0" * 64


class EvidenceJournalError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class EvidenceJournal:
    """Append immutable records linked by SHA-256 hashes.

    File locking protects concurrent writers in the backend process. Records are
    never updated or truncated by this class.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path="logs/decision_evidence.jsonl", clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def append(self, event_type, payload, *, candle_id=None, event_at=None, idempotency_key=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = str(event_at or self.clock().isoformat())
        body = {
            "schema_version": self.SCHEMA_VERSION,
            "event_type": str(event_type),
            "event_at": timestamp,
            "candle_id": str(candle_id) if candle_id is not None else None,
            "idempotency_key": str(idempotency_key) if idempotency_key is not None else None,
            "payload": deepcopy(dict(payload)),
        }
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                rows = self._read_handle(handle)
                if body["idempotency_key"] and any(row.get("idempotency_key") == body["idempotency_key"] for row in rows):
                    return deepcopy(next(row for row in rows if row.get("idempotency_key") == body["idempotency_key"])), False
                previous_hash = rows[-1]["record_hash"] if rows else GENESIS_HASH
                record_id = hashlib.sha256(_canonical(body).encode()).hexdigest()[:32]
                unsigned = {**body, "record_id": record_id, "previous_hash": previous_hash}
                record = {**unsigned, "record_hash": hashlib.sha256(_canonical(unsigned).encode()).hexdigest()}
                handle.seek(0, os.SEEK_END)
                handle.write(_canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return deepcopy(record), True
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                raise EvidenceJournalError("forensic evidence append failed") from error
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def records(self, *, event_type=None, candle_id=None):
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                rows = self._read_handle(handle)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise EvidenceJournalError("forensic evidence journal is unavailable") from error
        return [
            deepcopy(row) for row in rows
            if (event_type is None or row.get("event_type") == event_type)
            and (candle_id is None or row.get("candle_id") == candle_id)
        ]

    def latest(self, *, event_type=None, candle_id=None):
        rows = self.records(event_type=event_type, candle_id=candle_id)
        return rows[-1] if rows else None

    def verify(self):
        rows = self.records()
        previous_hash = GENESIS_HASH
        for index, row in enumerate(rows):
            if row.get("previous_hash") != previous_hash:
                return {"valid": False, "records": len(rows), "failed_index": index, "reason": "CHAIN_LINK_MISMATCH"}
            unsigned = {key: value for key, value in row.items() if key != "record_hash"}
            expected = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
            if row.get("record_hash") != expected:
                return {"valid": False, "records": len(rows), "failed_index": index, "reason": "RECORD_HASH_MISMATCH"}
            previous_hash = row["record_hash"]
        return {"valid": True, "records": len(rows), "head_hash": previous_hash, "reason": "VERIFIED"}

    @staticmethod
    def _read_handle(handle):
        handle.seek(0)
        rows = []
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema_version") != EvidenceJournal.SCHEMA_VERSION:
                raise ValueError("unsupported evidence schema")
            rows.append(row)
        return rows
