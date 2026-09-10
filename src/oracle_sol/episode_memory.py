"""Market Episode Memory Subsystem for CITADEL ORACLE Cognitive V2.

Enforces:
1. CITADEL owns episode memory (Model is NOT memory).
2. Temporal continuity across unchanged thesis states (e.g. NO_TRADE remains across multiple analyses).
3. Automatic closure and archiving of episodes upon state transition (e.g. NO_TRADE -> PUT_DEVELOPING).
4. Session rollover creates a fresh episode identity.
5. Provider failure resilience: accumulated events are never lost on network or 429 timeouts.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.oracle_sol.contracts import MarketEvent

logger = logging.getLogger(__name__)


@dataclass
class MarketEpisode:
    """A bounded cognitive market episode spanning a continuous thesis state."""

    episode_id: str
    session_id: str
    state: str
    started_at: str
    closed_at: Optional[str] = None
    start_cursor: Optional[str] = None
    end_cursor: Optional[str] = None
    accumulated_event_ids: List[str] = field(default_factory=list)
    accumulated_events: List[Dict[str, Any]] = field(default_factory=list)
    theses_committed: List[str] = field(default_factory=list)
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MarketEpisode:
        return cls(
            episode_id=d["episode_id"],
            session_id=d["session_id"],
            state=d["state"],
            started_at=d["started_at"],
            closed_at=d.get("closed_at"),
            start_cursor=d.get("start_cursor"),
            end_cursor=d.get("end_cursor"),
            accumulated_event_ids=d.get("accumulated_event_ids", []),
            accumulated_events=d.get("accumulated_events", []),
            theses_committed=d.get("theses_committed", []),
            is_active=d.get("is_active", True),
        )


class MarketEpisodeMemory:
    """Deterministic, provider-neutral repository of cognitive market episodes and session chronology."""

    def __init__(self, storage_path: str = "data/oracle_sol/market_episodes.jsonl") -> None:
        self.storage_path = storage_path
        self.base_dir = os.path.dirname(storage_path) or "data/oracle_sol"
        os.makedirs(self.base_dir, exist_ok=True)
        self.current_episode: Optional[MarketEpisode] = None
        self.session_id: Optional[str] = None
        self.session_events: List[Dict[str, Any]] = []
        self.session_event_ids: List[str] = []
        self._load_active_episode()

    def _get_events_path(self, session_id: str) -> str:
        return os.path.join(self.base_dir, f"session_events_{session_id}.jsonl")

    def _load_active_episode(self) -> None:
        """Loads the most recent active episode and reconciles durable session chronology from disk."""
        if not os.path.exists(self.storage_path):
            return
        last_active = None
        last_seen_session = None
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        last_seen_session = d.get("session_id")
                        if d.get("is_active"):
                            last_active = MarketEpisode.from_dict(d)
                        else:
                            last_active = None
        except Exception as e:
            logger.error("Failed loading active episode from %s: %s", self.storage_path, e)
        self.current_episode = last_active
        effective_session = last_active.session_id if last_active else last_seen_session
        if effective_session:
            self.session_id = effective_session
            # Reconcile from durable session events ledger on disk
            self._load_session_events_from_disk(effective_session)
            if last_active and not self.session_events and last_active.accumulated_events:
                self.session_events = list(last_active.accumulated_events)
                self.session_event_ids = list(last_active.accumulated_event_ids)

    def _load_session_events_from_disk(self, session_id: str) -> None:
        """Loads all canonical session events from durable append-only disk storage."""
        self.session_events.clear()
        self.session_event_ids.clear()
        ev_path = self._get_events_path(session_id)
        if not os.path.exists(ev_path):
            return
        try:
            with open(ev_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        evt = json.loads(line)
                        eid = evt.get("event_id")
                        if eid and eid not in self.session_event_ids:
                            self.session_event_ids.append(eid)
                            self.session_events.append(evt)
            logger.info("Reconstructed %d canonical session events from %s across process boundary", len(self.session_events), ev_path)
        except Exception as exc:
            logger.error("Failed reconstructing session events from %s: %s", ev_path, exc)

    def _persist_episode(self, episode: MarketEpisode) -> None:
        """Appends the episode record to disk."""
        try:
            with open(self.storage_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(episode.to_dict()) + "\n")
        except Exception as e:
            logger.error("Failed persisting episode %s: %s", episode.episode_id, e)

    def get_or_create_episode(
        self,
        session_id: str,
        current_state: str,
        current_cursor: Optional[str] = None,
    ) -> MarketEpisode:
        """Ensures an active episode exists for the current session and thesis state.

        Preserves the continuous, append-only session chronology across all thesis state transitions.
        Model thesis state transitions NEVER truncate or reset underlying market evidence.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        
        # Session Rollover: new session gets fresh identity and fresh event container
        if (
            self.current_episode is None
            or not self.current_episode.is_active
            or self.current_episode.session_id != session_id
        ):
            if self.current_episode and self.current_episode.is_active:
                self.close_current_episode(next_state=current_state, cursor=current_cursor)
            
            # If session changed, reset in-memory session chronology and reload from that session's disk log
            if self.session_id != session_id:
                self.session_id = session_id
                self._load_session_events_from_disk(session_id)

            ep_id = f"ep_{session_id}_{uuid.uuid4().hex[:8]}"
            self.current_episode = MarketEpisode(
                episode_id=ep_id,
                session_id=session_id,
                state=current_state,
                started_at=now_utc,
                start_cursor=current_cursor,
                end_cursor=current_cursor,
                accumulated_event_ids=list(self.session_event_ids),
                accumulated_events=list(self.session_events),
                is_active=True,
            )
            self._persist_episode(self.current_episode)
            logger.info("Started fresh MarketEpisode: %s (Session=%s, State=%s)", ep_id, session_id, current_state)
            return self.current_episode

        # Check for model thesis state transition within the same session
        if self.current_episode.state != current_state:
            logger.info(
                "State transition detected in MarketEpisodeMemory: %s -> %s (Preserving %d canonical session events)",
                self.current_episode.state,
                current_state,
                len(self.session_events),
            )
            self.close_current_episode(next_state=current_state, cursor=current_cursor)
            ep_id = f"ep_{session_id}_{uuid.uuid4().hex[:8]}"
            # NEW EPISODE INHERITS ALL ACCUMULATED CANONICAL SESSION EVENTS:
            self.current_episode = MarketEpisode(
                episode_id=ep_id,
                session_id=session_id,
                state=current_state,
                started_at=now_utc,
                start_cursor=current_cursor,
                end_cursor=current_cursor,
                accumulated_event_ids=list(self.session_event_ids),
                accumulated_events=list(self.session_events),
                is_active=True,
            )
            self._persist_episode(self.current_episode)
            return self.current_episode

        return self.current_episode

    def record_events(self, events: List[MarketEvent]) -> None:
        """Accumulates canonical events monotonically into the active session chronology."""
        if not events:
            return
        
        newly_added = []
        for e in events:
            if e.event_id not in self.session_event_ids:
                self.session_event_ids.append(e.event_id)
                evt_dict = {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "timestamp": getattr(e, "timestamp_ist", "") or getattr(e, "timestamp", "") or getattr(e, "timestamp_utc", ""),
                    "summary": getattr(e, "summary", ""),
                    "details": getattr(e, "details", {}) if hasattr(e, "details") else getattr(e, "supporting_values", {}),
                    "provenance_hash": getattr(e, "provenance_hash", ""),
                }
                self.session_events.append(evt_dict)
                newly_added.append(evt_dict)
                if self.current_episode:
                    if e.event_id not in self.current_episode.accumulated_event_ids:
                        self.current_episode.accumulated_event_ids.append(e.event_id)
                        self.current_episode.accumulated_events.append(evt_dict)
                    self.current_episode.end_cursor = e.event_id

        # Persist newly added events to dedicated append-only session events log
        session_id = self.session_id or (self.current_episode.session_id if self.current_episode else None)
        if session_id and newly_added:
            ev_path = self._get_events_path(session_id)
            try:
                with open(ev_path, "a", encoding="utf-8") as f:
                    for item in newly_added:
                        f.write(json.dumps(item) + "\n")
                    f.flush()
            except Exception as exc:
                logger.error("Failed writing durable session events to %s: %s", ev_path, exc)

        if self.current_episode:
            self._persist_episode(self.current_episode)

    def record_thesis_commit(self, thesis_id: str, new_state: str, cursor: str) -> None:
        """Records a committed thesis and evaluates state transition without truncating history."""
        if not self.current_episode:
            return
        
        if thesis_id not in self.current_episode.theses_committed:
            self.current_episode.theses_committed.append(thesis_id)
            self.current_episode.end_cursor = cursor

        # If thesis changes state, close prior episode segment and establish new segment
        if self.current_episode.state != new_state:
            session_id = self.current_episode.session_id
            self.close_current_episode(next_state=new_state, cursor=cursor)
            self.get_or_create_episode(session_id=session_id, current_state=new_state, current_cursor=cursor)

    def close_current_episode(self, next_state: Optional[str] = None, cursor: Optional[str] = None) -> None:
        """Closes the current active episode and persists its archived state."""
        if not self.current_episode or not self.current_episode.is_active:
            return
        
        self.current_episode.is_active = False
        self.current_episode.closed_at = datetime.now(timezone.utc).isoformat()
        if cursor:
            self.current_episode.end_cursor = cursor
        self._persist_episode(self.current_episode)
        logger.info(
            "Archived MarketEpisode segment: %s (Preserved: %d events in session chronology)",
            self.current_episode.episode_id,
            len(self.session_events),
        )

    def get_accumulated_events(self) -> List[Dict[str, Any]]:
        """Returns all events accumulated in the current session chronology."""
        if self.session_events:
            return list(self.session_events)
        if self.current_episode:
            return list(self.current_episode.accumulated_events)
        return []

    def get_session_chronology(self) -> List[Dict[str, Any]]:
        """Immutable view of the continuous, model-independent session market events."""
        return list(self.session_events)
