"""In-memory append-only matched research ledger for VOB episodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Callable, Mapping

from .episodes import VobEpisode


VARIANTS = ("VOB_ONLY", "EARLY_REVERSAL", "CONFIRMED_REVERSAL")


@dataclass(frozen=True, slots=True)
class ShadowLedgerEvent:
    event_id: str
    event_type: str
    episode_id: str
    variant: str
    recorded_at: str
    payload: Mapping[str, Any]
    post_hoc: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["payload"] = dict(self.payload)
        return value


class MatchedShadowLedger:
    """Append-only event stream; durable writes belong to an async recorder."""

    def __init__(self, event_sink: Callable[[Mapping[str, Any]], None] | None = None) -> None:
        self._lock = RLock()
        self._events: list[ShadowLedgerEvent] = []
        self._keys: set[str] = set()
        self._event_sink = event_sink

    def begin_episode(
        self,
        episode: VobEpisode,
        *,
        recorded_at: str,
        authority_refs: Mapping[str, Any] | None = None,
    ) -> tuple[ShadowLedgerEvent, ...]:
        emitted = []
        refs = dict(authority_refs or {})
        for variant in VARIANTS:
            trade_id = f"{episode.episode_id}_{variant}"
            emitted_event = self._append(
                "SHADOW_VARIANT_ELIGIBLE",
                episode,
                variant,
                recorded_at,
                {
                    "trade_id": trade_id,
                    "episode_id": episode.episode_id,
                    "timeframe": episode.timeframe,
                    "variant": variant,
                    "contract_security_id": episode.contract_identity.security_id,
                    "contract_expiry": episode.contract_identity.expiry,
                    "session_date": episode.session_date,
                    "expiry_day": episode.expiry_day,
                    "expiry_bucket": (
                        "EXPIRY" if episode.expiry_day is True
                        else "NON_EXPIRY" if episode.expiry_day is False
                        else "UNKNOWN"
                    ),
                    "entry_time": None,
                    "entry_ask": None,
                    "initial_sl": refs.get("initial_sl"),
                    "target": refs.get("target"),
                    "current_bid": None,
                    "exit_bid": None,
                    "exit_time": None,
                    "exit_reason": None,
                    "mfe": None,
                    "mae": None,
                    "r": None,
                    "time_to_1r": None,
                    "time_to_2r": None,
                    "time_to_3r": None,
                    "confirmation_delay": None,
                    "move_lost_before_confirmation": None,
                    "evidence_missing": list(refs.get("evidence_missing") or []),
                    "entry_sl_target_authority": "PULLBACK_MASTER",
                },
            )
            if emitted_event is not None:
                emitted.append(emitted_event)
        return tuple(emitted)

    def append_observation(
        self,
        episode: VobEpisode,
        variant: str,
        *,
        event_type: str,
        recorded_at: str,
        payload: Mapping[str, Any],
    ) -> ShadowLedgerEvent | None:
        if variant not in VARIANTS:
            raise ValueError("unsupported VOB shadow variant")
        full_payload = {
            "trade_id": f"{episode.episode_id}_{variant}",
            "episode_id": episode.episode_id,
            "timeframe": episode.timeframe,
            "variant": variant,
            **dict(payload),
        }
        return self._append(event_type, episode, variant, recorded_at, full_payload)

    def record_entry(
        self,
        episode: VobEpisode,
        variant: str,
        *,
        entry_time: str,
        entry_ask: float,
        initial_sl: Any,
        target: Any,
        evidence_missing: list[str] | None = None,
    ) -> ShadowLedgerEvent | None:
        """Record executable long-option entry truth without inventing levels."""

        return self.append_observation(
            episode,
            variant,
            event_type="SHADOW_ENTRY",
            recorded_at=entry_time,
            payload={
                "trade_id": f"{episode.episode_id}_{variant}",
                "episode_id": episode.episode_id,
                "timeframe": episode.timeframe,
                "variant": variant,
                "contract_security_id": episode.contract_identity.security_id,
                "entry_time": entry_time,
                "entry_ask": float(entry_ask),
                "initial_sl": initial_sl,
                "target": target,
                "evidence_missing": list(evidence_missing or []),
            },
        )

    def mark(
        self,
        episode: VobEpisode,
        variant: str,
        *,
        recorded_at: str,
        current_bid: float,
    ) -> ShadowLedgerEvent | None:
        """Mark a hypothetical long option at executable BID."""

        current = self.current(episode.episode_id).get(variant) or {}
        entry = _number(current.get("entry_ask"))
        stop = _number(current.get("initial_sl"))
        bid = float(current_bid)
        prior_mfe = _number(current.get("mfe"))
        prior_mae = _number(current.get("mae"))
        favorable = None if entry is None else bid - entry
        adverse = None if entry is None else entry - bid
        risk = abs(entry - stop) if entry is not None and stop is not None and entry != stop else None
        return self.append_observation(
            episode,
            variant,
            event_type="SHADOW_MARK",
            recorded_at=recorded_at,
            payload={
                "current_bid": bid,
                "mfe": max(prior_mfe or 0.0, favorable or 0.0) if favorable is not None else prior_mfe,
                "mae": max(prior_mae or 0.0, adverse or 0.0) if adverse is not None else prior_mae,
                "r": None if risk is None or favorable is None else favorable / risk,
            },
        )

    def events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            selected = self._events[-limit:] if limit is not None else self._events
            return [event.to_dict() for event in selected]

    def current(self, episode_id: str) -> dict[str, Any]:
        with self._lock:
            selected = [event for event in self._events if event.episode_id == episode_id]
        result = {variant: None for variant in VARIANTS}
        for event in selected:
            result[event.variant] = {
                **(result[event.variant] or {}),
                **dict(event.payload),
                "event_type": event.event_type,
                "recorded_at": event.recorded_at,
                "post_hoc": event.post_hoc,
            }
        return result

    def current_all(self) -> dict[str, dict[str, Any]]:
        """Return aggregated variant state dictionary keyed by episode_id."""
        with self._lock:
            episode_ids = {event.episode_id for event in self._events}
        return {ep_id: self.current(ep_id) for ep_id in episode_ids}

    def active_trades(self) -> list[dict[str, Any]]:
        """Return list of all active shadow trades across all episodes."""
        all_episodes = self.current_all()
        trades = []
        for ep_id, variants in all_episodes.items():
            for variant, data in variants.items():
                if data and data.get("entry_ask") is not None:
                    trades.append(dict(data))
        return trades

    def _append(
        self,
        event_type: str,
        episode: VobEpisode,
        variant: str,
        recorded_at: str,
        payload: Mapping[str, Any],
    ) -> ShadowLedgerEvent | None:
        identity = {
            "event_type": event_type,
            "episode_id": episode.episode_id,
            "variant": variant,
            "recorded_at": recorded_at,
            "payload": dict(payload),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
        event_id = "vobled_" + sha256(encoded).hexdigest()[:24]
        with self._lock:
            if event_id in self._keys:
                return None
            event = ShadowLedgerEvent(
                event_id=event_id,
                event_type=event_type,
                episode_id=episode.episode_id,
                variant=variant,
                recorded_at=recorded_at,
                payload=dict(payload),
            )
            self._keys.add(event_id)
            self._events.append(event)
        if self._event_sink is not None:
            self._event_sink(event.to_dict())
        return event


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
