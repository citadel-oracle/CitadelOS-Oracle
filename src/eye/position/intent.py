"""Immutable, idempotent execution intents for Analyzer-only paper routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Optional

from src.eye.kernel.domain import ExecutionIntent
from src.strategy_lab.storage import ImmutableStream


class ExecutionIntentService:
    """Create recorded intents only; this service never calls a broker."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.events = ImmutableStream(self.root / "execution_intents.jsonl", max_bytes=10 * 1024 * 1024, max_files=1)
        self._lock = Lock()

    @staticmethod
    def intent_id(*, strategy_id: str, cycle_id: str, security_id: str, side: str) -> str:
        payload = f"{strategy_id}:{cycle_id}:{security_id}:{side.upper()}"
        return "EYEI:" + hashlib.sha256(payload.encode()).hexdigest()[:32]

    def create(self, *, strategy_id: str, cycle_id: str, security_id: str, side: str, quantity: int, entry_policy: str, timestamp: float, reason: str, protective_risk: Mapping[str, Any]) -> ExecutionIntent:
        if side.upper() != "BUY":
            raise ValueError("EYE execution intent permits BUY option entries only")
        if quantity <= 0 or not security_id:
            raise ValueError("EYE execution intent requires exact security ID and positive quantity")
        intent = ExecutionIntent(
            intent_id=self.intent_id(strategy_id=strategy_id, cycle_id=cycle_id, security_id=security_id, side=side),
            strategy_id=strategy_id, cycle_id=cycle_id, security_id=security_id, side="BUY", quantity=int(quantity),
            entry_policy=entry_policy, timestamp=float(timestamp), reason=reason, protective_risk=dict(protective_risk),
        )
        with self._lock:
            existing = [row for row in self.events.read() if row.get("payload", {}).get("intent_id") == intent.intent_id]
            if not existing:
                self.events.append("EYE_EXECUTION_INTENT", asdict(intent), recorded_at=str(timestamp), idempotency_key=intent.intent_id)
        return intent

    def list(self) -> list[dict[str, Any]]:
        return [dict(row.get("payload") or {}) for row in self.events.read()]
