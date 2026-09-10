"""Asynchronous Non-Blocking Event Journal for Live Island Forensic Replay."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JournalEntry:
    timestamp: float
    trigger_reason: str
    event_id: str
    family: str
    old_value: str
    new_value: str
    numeric_trend: str
    event_bias: str
    rule_version: str
    provenance: str
    hero_decision: str
    coalesced: bool
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LiveIslandJournal:
    """Thread-safe bounded in-memory ring buffer capturing event history for replay/audit."""

    def __init__(self, maxlen: int = 1_000) -> None:
        self.maxlen = maxlen
        self._buffer: deque[JournalEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(
        self,
        trigger_reason: str,
        event_id: str,
        family: str,
        old_value: str,
        new_value: str,
        numeric_trend: str,
        event_bias: str,
        rule_version: str = "1.0.0",
        provenance: str = "ORACLE_LIVE_ISLAND",
        hero_decision: str = "UNCHANGED",
        coalesced: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = JournalEntry(
            timestamp=time.time(),
            trigger_reason=trigger_reason,
            event_id=event_id,
            family=family,
            old_value=old_value,
            new_value=new_value,
            numeric_trend=numeric_trend,
            event_bias=event_bias,
            rule_version=rule_version,
            provenance=provenance,
            hero_decision=hero_decision,
            coalesced=coalesced,
            details=details or {},
        )
        with self._lock:
            self._buffer.append(entry)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._buffer)
        return [e.to_dict() for e in entries[-limit:]]

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
