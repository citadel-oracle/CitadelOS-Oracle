"""Deterministic Strategy Lab market-state and projection invariants.

This module is deliberately independent of strategy decisions.  It owns only
completed-candle persistence, continuity certification and read-only position
projection helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
CANDLE_SCHEMA_VERSION = 2
READINESS_SCHEMA_VERSION = 1


_RUNTIME_METRICS_LOCK = threading.RLock()
_RUNTIME_METRICS = {
    "pid": os.getpid(),
    "canonical_disk_loads": 0,
    "canonical_full_state_hashes": 0,
    "canonical_cache_hits": 0,
    "canonical_atomic_writes": 0,
}


def _metric(name: str) -> None:
    with _RUNTIME_METRICS_LOCK:
        if _RUNTIME_METRICS["pid"] != os.getpid():
            reset_state_truth_runtime_metrics()
        _RUNTIME_METRICS[name] = int(_RUNTIME_METRICS.get(name, 0)) + 1


def state_truth_runtime_metrics() -> dict[str, int]:
    """Process-local evidence for canonical truth I/O and full-state hashing."""

    with _RUNTIME_METRICS_LOCK:
        return {key: int(value) for key, value in _RUNTIME_METRICS.items()}


def reset_state_truth_runtime_metrics() -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS.update({
            "pid": os.getpid(),
            "canonical_disk_loads": 0,
            "canonical_full_state_hashes": 0,
            "canonical_cache_hits": 0,
            "canonical_atomic_writes": 0,
        })


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _aware(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def timeframe_minutes(value: str) -> int:
    normalized = str(value).strip().lower()
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return max(1, int(normalized[:-1]))
    raise ValueError("UNSUPPORTED_CANDLE_TIMEFRAME")


def _regular_session_candle(timestamp: datetime) -> bool:
    stamp = timestamp.astimezone(IST)
    return stamp.weekday() < 5 and (stamp.hour, stamp.minute) >= (9, 15) and (
        stamp.hour,
        stamp.minute,
    ) <= (15, 29)


@dataclass(frozen=True)
class CandleIdentity:
    instrument: str
    security_id: str
    timeframe: str
    expiry: str | None = None

    @property
    def key(self) -> str:
        raw = f"{self.instrument.upper()}|{self.security_id}|{self.expiry or '-'}|{self.timeframe.lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class HistoryRequirement:
    indicator_lookback: int
    stabilization_buffer: int
    structure_scan_window: int
    active_structure_age: int
    higher_timeframe_bars: int
    replay_overlap: int
    safety_buffer: int

    @property
    def required_bars(self) -> int:
        return max(
            self.indicator_lookback + self.stabilization_buffer,
            self.structure_scan_window,
            self.active_structure_age,
            self.higher_timeframe_bars,
        ) + self.replay_overlap + self.safety_buffer

    @classmethod
    def strategy_lab_default(cls, timeframe: str) -> "HistoryRequirement":
        # Values are derived from the shared engines: ATR/FVG 200, liquidity
        # normalization 500, pivot confirmation 10+8 and Pine history 5000.
        # For expiring option contracts, the canonical reservoir retains the
        # full contract lifetime; readiness uses the realizable four-session
        # structure horizon rather than fabricating pre-listing bars.
        minutes = timeframe_minutes(timeframe)
        bars_per_session = max(1, 375 // minutes)
        realizable_structure_age = min(5000, bars_per_session * 4)
        return cls(
            indicator_lookback=500,
            stabilization_buffer=200,
            structure_scan_window=max(500, realizable_structure_age),
            active_structure_age=realizable_structure_age,
            higher_timeframe_bars=0,
            replay_overlap=max(20, 30 // minutes),
            safety_buffer=max(64, 60 // minutes),
        )


class CanonicalCandleStore:
    """Atomic, versioned store of authoritative completed candles."""

    def __init__(self, root: str | Path, identity: CandleIdentity, *, max_candles: int = 12000) -> None:
        self.root = Path(root)
        self.identity = identity
        self.max_candles = max(512, int(max_candles))
        self.path = self.root / f"{identity.key}.json"
        self.audit_path = self.root / f"{identity.key}.audit.jsonl"
        self.gap_path = self.root / f"{identity.key}.gaps.json"
        self._lock = threading.RLock()
        self._loaded_signature: tuple[int, int] | None = None
        self._loaded_candles: list[dict[str, Any]] | None = None

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                stat = self.path.stat()
                signature = (int(stat.st_mtime_ns), int(stat.st_size))
                if signature == self._loaded_signature and self._loaded_candles is not None:
                    _metric("canonical_cache_hits")
                    return deepcopy(self._loaded_candles)
                value = json.loads(self.path.read_text(encoding="utf-8"))
                _metric("canonical_disk_loads")
                if value.get("schema_version") != CANDLE_SCHEMA_VERSION:
                    return []
                expected = value.get("reservoir_checksum")
                candles = list(value.get("candles") or [])
                _metric("canonical_full_state_hashes")
                if expected != _sha([{k: row.get(k) for k in self._checksum_fields()} for row in candles]):
                    return []
                loaded = [
                    row
                    for row in candles
                    if _regular_session_candle(_aware(row.get("timestamp")))
                ]
                self._loaded_signature = signature
                self._loaded_candles = deepcopy(loaded)
                return loaded
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return []

    def merge(self, rows: Iterable[Mapping[str, Any]], *, fetch_timestamp: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = {str(row["timestamp"]): dict(row) for row in self.load()}
            inserted = duplicates = corrections = rejected = 0
            for raw in rows:
                normalized = self._normalize(raw)
                if normalized is None:
                    rejected += 1
                    continue
                timestamp = normalized["timestamp"]
                prior = current.get(timestamp)
                if prior is None:
                    current[timestamp] = normalized
                    inserted += 1
                elif prior["checksum"] == normalized["checksum"]:
                    duplicates += 1
                else:
                    corrections += 1
                    self._audit("CANDLE_CORRECTED", timestamp, prior, normalized)
                    current[timestamp] = normalized
            candles = [current[key] for key in sorted(current)][-self.max_candles :]
            document = {
                "schema_version": CANDLE_SCHEMA_VERSION,
                "identity": asdict(self.identity),
                "updated_at": fetch_timestamp or datetime.now(timezone.utc).isoformat(),
                "last_successful_historical_fetch": fetch_timestamp,
                "candle_count": len(candles),
                "reservoir_checksum": _sha([{k: row.get(k) for k in self._checksum_fields()} for row in candles]),
                "candles": candles,
            }
            self._atomic_write(document)
            stat = self.path.stat()
            self._loaded_signature = (int(stat.st_mtime_ns), int(stat.st_size))
            self._loaded_candles = deepcopy(candles)
            return {"inserted": inserted, "duplicates": duplicates, "corrections": corrections, "rejected": rejected, **self.audit(candles)}

    def audit(self, rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        candles = list(rows if rows is not None else self.load())
        interval = timeframe_minutes(self.identity.timeframe)
        parsed = [_aware(row["timestamp"]) for row in candles]
        duplicates = len(parsed) - len(set(parsed))
        out_of_order = sum(left >= right for left, right in zip(parsed, parsed[1:]))
        incomplete = sum(not (row.get("closed") is True or row.get("is_closed") is True) for row in candles)
        by_day: dict[Any, set[datetime]] = {}
        for stamp in parsed:
            if _regular_session_candle(stamp):
                by_day.setdefault(stamp.date(), set()).add(stamp.replace(second=0, microsecond=0))
        missing: list[str] = []
        for day, available in sorted(by_day.items()):
            first = min(available)
            last = max(available)
            expected = first
            while expected <= last:
                if expected not in available:
                    missing.append(expected.isoformat())
                expected += timedelta(minutes=interval)
        sessions = sorted(by_day)
        latest_day = sessions[-1] if sessions else None
        current_starts_at_0915 = False
        if latest_day is not None:
            current_starts_at_0915 = datetime.combine(latest_day, datetime.min.time(), IST).replace(hour=9, minute=15) in by_day[latest_day]
        return {
            "schema_version": READINESS_SCHEMA_VERSION,
            "identity": asdict(self.identity),
            "loaded_bars": len(candles),
            "earliest_candle": candles[0].get("timestamp") if candles else None,
            "latest_completed_candle": candles[-1].get("timestamp") if candles else None,
            "session_count": len(sessions),
            "current_session_starts_at_0915": current_starts_at_0915,
            "previous_session_present": len(sessions) >= 2,
            "missing_candle_count": len(missing),
            "missing_timestamps": missing[:100],
            "duplicate_candle_count": duplicates,
            "out_of_order_count": out_of_order,
            "incomplete_candle_count": incomplete,
            "reservoir_checksum": _sha([{k: row.get(k) for k in self._checksum_fields()} for row in candles]),
        }

    def readiness(self, requirement: HistoryRequirement, *, now: datetime | None = None, max_age_seconds: float = 600.0) -> dict[str, Any]:
        audit = self.audit()
        loaded = int(audit["loaded_bars"])
        reason = None
        if loaded < requirement.required_bars:
            reason = "INSUFFICIENT_HISTORY"
        elif audit["duplicate_candle_count"]:
            reason = "DUPLICATE_CONFLICT"
        elif audit["missing_candle_count"]:
            reason = "CANDLE_GAP"
        elif audit["incomplete_candle_count"]:
            reason = "INCOMPLETE_CANDLE"
        latest = audit.get("latest_completed_candle")
        age = None
        if latest:
            age = max(0.0, ((_aware(now or datetime.now(IST)) - _aware(latest) - timedelta(minutes=timeframe_minutes(self.identity.timeframe))).total_seconds()))
        if reason is None and age is not None and age > max_age_seconds:
            reason = "LIVE_FEED_STALE"
        ready = reason is None
        return {
            **audit,
            "gap_classifications": self.gap_classifications(),
            "required_bars": requirement.required_bars,
            "history_requirement": asdict(requirement),
            "indicator_warmup_complete": loaded >= requirement.indicator_lookback + requirement.stabilization_buffer,
            "structure_replay_complete": loaded >= requirement.active_structure_age,
            "historical_bootstrap_complete": loaded >= requirement.required_bars and not audit["missing_candle_count"],
            "live_overlap_reconciled": not audit["duplicate_candle_count"],
            "freshness_age_seconds": age,
            "DATA_READY": ready,
            "not_ready_reason": reason,
        }

    def record_gap_classifications(self, rows: Iterable[Mapping[str, Any]]) -> None:
        """Persist provider-backed continuity decisions without altering candles."""

        with self._lock:
            current = {str(row.get("timestamp") or ""): dict(row) for row in self.gap_classifications()}
            for row in rows:
                timestamp = str(row.get("timestamp") or "")
                if timestamp:
                    current[timestamp] = deepcopy(dict(row))
            document = {
                "schema_version": READINESS_SCHEMA_VERSION,
                "identity": asdict(self.identity),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "classifications": [current[key] for key in sorted(current)],
            }
            self.gap_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.gap_path.with_suffix(self.gap_path.suffix + ".tmp")
            temporary.write_text(_canonical(document), encoding="utf-8")
            os.replace(temporary, self.gap_path)

    def gap_classifications(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.gap_path.read_text(encoding="utf-8"))
            if value.get("schema_version") != READINESS_SCHEMA_VERSION:
                return []
            return [dict(row) for row in value.get("classifications") or [] if isinstance(row, Mapping)]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def _normalize(self, raw: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            if raw.get("closed") is not True and raw.get("is_closed") is not True:
                return None
            parsed_stamp = _aware(raw["timestamp"]).replace(second=0, microsecond=0)
            if not _regular_session_candle(parsed_stamp):
                return None
            stamp = parsed_stamp.isoformat()
            values = {key: float(raw[key]) for key in ("open", "high", "low", "close")}
            if values["high"] < max(values.values()) or values["low"] > min(values.values()):
                return None
            payload = {
                **deepcopy(dict(raw)),
                **values,
                "timestamp": stamp,
                "volume": float(raw.get("volume") or 0.0),
                "source": str(raw.get("source") or "UNKNOWN"),
                "completion_state": "COMPLETED",
                "closed": True,
                "is_closed": True,
                "ingest_timestamp": str(raw.get("received_at") or datetime.now(timezone.utc).isoformat()),
                "schema_version": CANDLE_SCHEMA_VERSION,
            }
            payload["checksum"] = _sha({key: payload.get(key) for key in self._checksum_fields()})
            return payload
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _checksum_fields() -> tuple[str, ...]:
        return ("timestamp", "open", "high", "low", "close", "volume", "source", "completion_state")

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(_canonical(document), encoding="utf-8")
        os.replace(temporary, self.path)
        _metric("canonical_atomic_writes")

    def _audit(self, event: str, timestamp: str, prior: Mapping[str, Any], current: Mapping[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(_canonical({
                "event": event,
                "timestamp": timestamp,
                "prior_checksum": prior.get("checksum"),
                "current_checksum": current.get("checksum"),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }) + "\n")


def authoritative_open_positions(states: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [deepcopy(dict(position)) for state in states for position in state.get("positions") or [] if str(position.get("status") or "").upper() == "OPEN"]
    ids = [str(row.get("position_id") or "") for row in rows]
    if any(not value for value in ids):
        raise ValueError("OPEN_POSITION_ID_REQUIRED")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_OPEN_POSITION_ID")
    return rows


def reconcile_deployment_positions(
    strategies: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for position in positions:
        by_strategy.setdefault(str(position.get("strategy_id") or ""), []).append(deepcopy(dict(position)))
    rows = []
    for strategy in strategies:
        row = deepcopy(dict(strategy))
        owned = by_strategy.get(str(row.get("strategy_id") or ""), [])
        row["current_positions"] = owned
        row["current_position"] = owned[0] if len(owned) == 1 else None
        row["current_position_count"] = len(owned)
        row["position_state"] = "OPEN" if owned else "FLAT"
        rows.append(row)
    mapped = sum(len(row["current_positions"]) for row in rows)
    warnings = []
    if mapped != len(positions):
        warnings.append("OPEN_POSITION_DEPLOYMENT_MAPPING_MISMATCH")
    return rows, {
        "status": "RECONCILED" if not warnings else "WARNING",
        "authoritative_open_count": len(positions),
        "mapped_open_count": mapped,
        "warnings": warnings,
    }


def stable_structure_id(*, security_id: str, timeframe: str, origin_timestamp: str, structure_type: str, direction: str, rule_version: str) -> str:
    return "structure_" + _sha({
        "security_id": str(security_id), "timeframe": timeframe, "origin_timestamp": origin_timestamp,
        "type": structure_type, "direction": direction, "rule_version": rule_version,
    })[:24]
