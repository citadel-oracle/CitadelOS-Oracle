"""Durable Session Event Store & Event-Sourced Active Story Subsystem (P0.3B Live-Hardened).

Maintains a durable append-only session event store holding 100% of factual
canonical events for the active IST session, with atomic write commit ordering,
idempotent deduplication, collision integrity checking, and explicit persistence health telemetry.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from src.oracle_sol.contracts import ActiveMarketStory, MarketEvent
from src.oracle_sol.provenance_guard import ProvenanceGuard

IST = ZoneInfo("Asia/Kolkata")


class EventSourcedMarketMemory:
    """Event-sourced session memory with durable disk-backed persistence and restart recovery."""

    def __init__(
        self,
        raw_buffer_capacity: int = 50,
        storage_dir: Optional[str] = None,
    ) -> None:
        self.raw_buffer_capacity = raw_buffer_capacity
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._raw_events: deque[MarketEvent] = deque(maxlen=raw_buffer_capacity)
        self._durable_session_events: List[MarketEvent] = []
        self._persisted_event_hashes: Dict[str, str] = {}
        self._pending_unpersisted_events: List[MarketEvent] = []
        self._lock = threading.RLock()
        self._session_date: str = datetime.now(IST).strftime("%Y-%m-%d")
        self._story_revision: int = 0

        self.event_store_status = "OK"
        self.last_successful_write_utc: Optional[str] = None
        self.last_persistence_error: Optional[str] = None

        now_utc = datetime.now(timezone.utc).isoformat()
        self._active_story = ActiveMarketStory(
            story_revision=0,
            session_date=self._session_date,
            established_at_utc=now_utc,
            last_event_id="none",
            total_events_processed=0,
            session_open_summary="Session uninitialized.",
            structure_evolution_summary="Awaiting market opening events.",
            flow_regime_summary="No flow events recorded.",
            positioning_summary="No strike positioning events recorded.",
            retained_event_refs=[],
            provenance_hash="",
        )

        # Attempt auto-hydration from current session date on disk
        self._hydrate_persisted_session_events(self._session_date)

    def _get_session_events_file(self, session_date: str) -> Path:
        return self.storage_dir / f"sol_session_events_{session_date}.jsonl"

    def _hydrate_persisted_session_events(self, session_date: str) -> bool:
        """Hydrate memory from persisted session events file with strict collision checking."""
        event_file = self._get_session_events_file(session_date)
        if not event_file.exists():
            return False

        restored_events: List[MarketEvent] = []
        seen_hashes: Dict[str, str] = {}
        try:
            with open(event_file, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f):
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        evt_id = d["event_id"]
                        prov_hash = d.get("provenance_hash", "")

                        if evt_id in seen_hashes:
                            if seen_hashes[evt_id] != prov_hash:
                                raise ValueError(
                                    f"Hydration integrity violation at line {line_idx+1}: "
                                    f"duplicate event_id '{evt_id}' with conflicting hash."
                                )
                            # Idempotent duplicate: skip re-adding
                            continue

                        evt = MarketEvent(
                            event_id=evt_id,
                            session_date=d.get("session_date", session_date),
                            timestamp_utc=d["timestamp_utc"],
                            timestamp_ist=d["timestamp_ist"],
                            event_type=d["event_type"],
                            instrument=d["instrument"],
                            summary=d["summary"],
                            security_id=d.get("security_id"),
                            strike=d.get("strike"),
                            expiry=d.get("expiry"),
                            before_state=d.get("before_state"),
                            after_state=d.get("after_state"),
                            supporting_values=d.get("supporting_values", {}),
                            provenance_hash=prov_hash,
                        )
                        restored_events.append(evt)
                        seen_hashes[evt_id] = prov_hash

            if restored_events:
                with self._lock:
                    self._session_date = session_date
                    self._raw_events.clear()
                    self._durable_session_events.clear()
                    self._persisted_event_hashes.clear()
                    for evt in restored_events:
                        self._raw_events.append(evt)
                        self._durable_session_events.append(evt)
                        self._persisted_event_hashes[evt.event_id] = evt.provenance_hash
                        self._update_active_story(evt)
                    self.event_store_status = "OK"
                return True
        except Exception as exc:
            self.event_store_status = "DEGRADED"
            self.last_persistence_error = f"Event hydration error: {str(exc)}"
            if isinstance(exc, ValueError) and "Hydration integrity violation" in str(exc):
                raise exc
        return False

    def append(self, event: MarketEvent) -> None:
        """Append a new discrete market event with ATOMIC commit ordering (disk write before state update)."""
        with self._lock:
            # 1. Validate collision / idempotency
            if event.event_id in self._persisted_event_hashes:
                existing_hash = self._persisted_event_hashes[event.event_id]
                if existing_hash == event.provenance_hash:
                    # Idempotent duplicate: skip cleanly
                    return
                else:
                    raise ValueError(
                        f"Persistence integrity violation: event_id '{event.event_id}' already persisted with different hash."
                    )

            # 2. Perform durable disk append FIRST
            session_date = event.session_date or self._session_date or "ACTIVE"
            event_file = self._get_session_events_file(session_date)
            try:
                with open(event_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), sort_keys=True, default=str) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                self.last_successful_write_utc = datetime.now(timezone.utc).isoformat()
                self.event_store_status = "OK"
            except Exception as exc:
                self.event_store_status = "ERROR"
                self.last_persistence_error = f"Event persist error: {str(exc)}"
                self._pending_unpersisted_events.append(event)
                raise IOError(f"Failed to persist event {event.event_id} to durable store: {str(exc)}") from exc

            # 3. Only on FS success, update in-memory indexes and active story
            self._raw_events.append(event)
            self._durable_session_events.append(event)
            self._persisted_event_hashes[event.event_id] = event.provenance_hash
            self._update_active_story(event)

    def append_batch(self, events: List[MarketEvent]) -> None:
        with self._lock:
            for evt in events:
                self.append(evt)

    def _update_active_story(self, event: MarketEvent) -> None:
        """Deterministically update the active compressed story from factual events."""
        self._story_revision += 1
        now_utc = datetime.now(timezone.utc).isoformat()

        all_event_ids = [e.event_id for e in self._durable_session_events]

        open_summary = self._active_story.session_open_summary
        if self._story_revision == 1 or "uninitialized" in open_summary.lower() or "reset" in open_summary.lower():
            open_summary = f"Session established at {event.timestamp_ist}: {event.summary}"

        struct_summary = self._active_story.structure_evolution_summary
        flow_summary = self._active_story.flow_regime_summary
        pos_summary = self._active_story.positioning_summary

        if "SPOT_MOVE" in event.event_type or "ATM_MIGRATION" in event.event_type or "FUTURES_MOVE" in event.event_type or "BASIS_SHIFT" in event.event_type:
            struct_summary = f"Latest structural move ({event.timestamp_ist}): {event.summary}"
        elif "FLOW" in event.event_type:
            flow_summary = f"Latest flow shift ({event.timestamp_ist}): {event.summary}"
        elif "OI" in event.event_type or "CLOSED_OI" in event.event_type:
            pos_summary = f"Latest strike positioning ({event.timestamp_ist}): {event.summary}"
        elif "GEX" in event.event_type or "STRADDLE" in event.event_type or "VOLATILITY" in event.event_type:
            struct_summary = f"Latest volatility/positioning shift ({event.timestamp_ist}): {event.summary}"

        story_dict = {
            "revision": self._story_revision,
            "session_date": self._session_date,
            "last_event_id": event.event_id,
            "total_events": len(self._durable_session_events),
            "open": open_summary,
            "struct": struct_summary,
            "flow": flow_summary,
            "pos": pos_summary,
        }
        prov_hash = ProvenanceGuard.compute_sha256(story_dict)

        self._active_story = ActiveMarketStory(
            story_revision=self._story_revision,
            session_date=self._session_date,
            established_at_utc=now_utc,
            last_event_id=event.event_id,
            total_events_processed=len(self._durable_session_events),
            session_open_summary=open_summary,
            structure_evolution_summary=struct_summary,
            flow_regime_summary=flow_summary,
            positioning_summary=pos_summary,
            retained_event_refs=all_event_ids,
            provenance_hash=prov_hash,
        )

    def get_recent_raw_events(self, limit: Optional[int] = None) -> List[MarketEvent]:
        with self._lock:
            evts = list(self._raw_events)
            if limit and limit > 0:
                return evts[-limit:]
            return evts

    def get_all_session_events(self) -> List[MarketEvent]:
        with self._lock:
            return list(self._durable_session_events)

    def get_active_story(self) -> ActiveMarketStory:
        with self._lock:
            return self._active_story

    def total_events_in_session(self) -> int:
        with self._lock:
            return len(self._durable_session_events)

    def raw_buffer_count(self) -> int:
        with self._lock:
            return len(self._raw_events)

    def check_session_boundary(self, current_session_date: Optional[str]) -> bool:
        if not current_session_date:
            return False
        with self._lock:
            if self._session_date != current_session_date:
                self.reset_session(current_session_date)
                return True
            return False

    def reset_session(self, session_date: str) -> None:
        with self._lock:
            self._raw_events.clear()
            self._durable_session_events.clear()
            self._persisted_event_hashes.clear()
            self._pending_unpersisted_events.clear()
            self._session_date = session_date
            self._story_revision = 0
            now_utc = datetime.now(timezone.utc).isoformat()
            self._active_story = ActiveMarketStory(
                story_revision=0,
                session_date=session_date,
                established_at_utc=now_utc,
                last_event_id="session_start",
                total_events_processed=0,
                session_open_summary=f"Session reset for date {session_date}.",
                structure_evolution_summary="Awaiting opening strikes and price action.",
                flow_regime_summary="Awaiting opening flow stream.",
                positioning_summary="Awaiting opening OI chain snapshot.",
                retained_event_refs=[],
                provenance_hash="",
            )

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_date": self._session_date,
                "story_revision": self._story_revision,
                "active_story": self._active_story.to_dict(),
                "total_events_processed": len(self._durable_session_events),
                "raw_event_count": len(self._raw_events),
                "event_store_status": self.event_store_status,
                "last_successful_write_utc": self.last_successful_write_utc,
                "last_persistence_error": self.last_persistence_error,
                "pending_unpersisted_count": len(self._pending_unpersisted_events),
            }


WorkingMarketMemory = EventSourcedMarketMemory
