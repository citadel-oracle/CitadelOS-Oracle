"""Restart-safe, content-addressed seven-lane context cache.

This service assembles perception substrate only.  It contains no trade scoring,
decision, risk, planning, order or position behavior.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.oracle.contracts.perception import (
    Availability, CanonicalCandleRef, CompletionStatus, FreshnessState,
    MarketContextSnapshot, SUPPORTED_TIMEFRAMES, TimeframeContext,
    record_from_dict, seal,
)
from src.strategy_lab.storage import _atomic_write
from src.vob import NiftyVOBEngine


IST = ZoneInfo("Asia/Kolkata")
POLICY_VERSION = "oracle-context-2.0.1"
RESAMPLER_VERSION = "vob-resampler+session-boundary-1.0.1"
FRESHNESS_SECONDS = {"1m": 120, "3m": 360, "5m": 600, "15m": 1800, "1H": 7200, "4H": 28800, "1D": 172800}
INTERVALS = {"3m": 3, "5m": 5, "15m": 15, "1H": 60}
LANE_ROLES = {
    "1D": "PRIMARY_REGIME_AND_MAJOR_STRUCTURE",
    "4H": "SESSION_BOUNDARY_STRUCTURE_PARITY_GATED",
    "1H": "INTRADAY_STRUCTURAL_BIAS_AND_MAJOR_SWINGS",
    "15m": "SESSION_ENVIRONMENT_AND_SETUP_PERMISSION_SUBSTRATE",
    "5m": "SETUP_FORMATION_SUBSTRATE_ONLY",
    "3m": "TRIGGER_CONFIRMATION_SUBSTRATE_ONLY",
    "1m": "OPTIONAL_REFINEMENT_NEVER_HTF_REVERSAL_AUTHORITY",
}


class ContextStateError(RuntimeError):
    pass


def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=IST)
    return result.astimezone(IST)


class ContextEngine:
    """Build and persist immutable context records from canonical 1m candles."""

    def __init__(self, root: str | Path, *, candle_path: str | Path, clock=None):
        self.root = Path(root)
        self.candle_path = Path(candle_path)
        self.records_root = self.root / "records"
        self.index_path = self.root / "latest_valid.json"
        self.snapshot_path = self.root / "latest_snapshot.json"
        self.diagnostics_path = self.root / "diagnostics.json"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._index = self._load_index()
        self._stats = {"hits": 0, "misses": 0, "lane_builds": {tf: 0 for tf in SUPPORTED_TIMEFRAMES}, "invalidations": 0, "last_build_ms": None}
        self._last_snapshot = self._load_snapshot()
        self._normalized_signature: str | None = None
        self._normalized_cache: list[dict[str, Any]] | None = None

    def bootstrap_from_persisted(self, *, correlation_id: str = "oracle-perception-startup") -> MarketContextSnapshot | None:
        candles = self._load_candles()
        if not candles:
            return self._last_snapshot
        return self.build(
            instrument_id="NSE:IDX_I:13", symbol="NIFTY", candles_1m=candles,
            correlation_id=correlation_id, parity_4h=False,
            source_ids={"canonical_candle_store": str(self.candle_path)},
            dependency_versions={"policy": POLICY_VERSION, "resampler": RESAMPLER_VERSION, "vob": "existing-authority"},
        )

    def build(
        self, *, instrument_id: str, symbol: str, candles_1m: Sequence[Mapping[str, Any]],
        correlation_id: str, parity_4h: bool, source_ids: Mapping[str, str],
        dependency_versions: Mapping[str, str],
    ) -> MarketContextSnapshot:
        started = perf_counter()
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        raw_last = dict(candles_1m[-1]) if candles_1m else {}
        build_signature = hashlib.sha256(json.dumps({
            "count": len(candles_1m),
            "last": {key: raw_last.get(key) for key in ("time", "timestamp", "open", "high", "low", "close", "volume")},
            "instrument_id": instrument_id, "symbol": symbol, "parity_4h": parity_4h,
            "dependencies": dict(dependency_versions), "policy": POLICY_VERSION,
        }, sort_keys=True, default=str).encode()).hexdigest()
        with self._lock:
            same_signature = self._index.get("_build_signature") == build_signature
            cached_lanes = {timeframe: self.latest_lane(timeframe) for timeframe in SUPPORTED_TIMEFRAMES}
            required_timeframes = {
                timeframe for timeframe, lane in cached_lanes.items()
                if lane is None
                or not bool((self._index.get(timeframe) or {}).get("valid"))
                or not self._lane_freshness_is_current(lane, timeframe, now)
            } if same_signature else set(SUPPORTED_TIMEFRAMES)
            if (
                self._last_snapshot is not None
                and same_signature
                and not required_timeframes
            ):
                self._stats["hits"] += len(SUPPORTED_TIMEFRAMES)
                self._stats["last_build_ms"] = round((perf_counter() - started) * 1000, 3)
                self._persist_diagnostics(now)
                return self._last_snapshot
        if self._normalized_signature == build_signature and self._normalized_cache is not None:
            normalized = self._normalized_cache
        else:
            normalized = self._normalize_1m(candles_1m, symbol)
            self._normalized_signature = build_signature
            self._normalized_cache = normalized
        if not normalized:
            raise ContextStateError("CANONICAL_1M_CANDLES_UNAVAILABLE")
        lanes_raw: dict[str, dict[str, Any] | None] = {}
        if "1m" in required_timeframes:
            lanes_raw["1m"] = normalized[-1]
        helper = NiftyVOBEngine()
        for timeframe, minutes in INTERVALS.items():
            if timeframe not in required_timeframes:
                continue
            rows = helper._resample_1m(normalized, minutes)
            if rows:
                lanes_raw[timeframe] = self._adapt_resampled(rows[-1], timeframe)
            else:
                lanes_raw[timeframe] = None
        if "4H" in required_timeframes:
            lanes_raw["4H"] = self._session_bar(normalized, "4H")
        if "1D" in required_timeframes:
            lanes_raw["1D"] = self._session_bar(normalized, "1D")

        lanes = []
        with self._lock:
            for timeframe in SUPPORTED_TIMEFRAMES:
                if timeframe not in required_timeframes:
                    self._stats["hits"] += 1
                    lanes.append(cached_lanes[timeframe])
                    continue
                lanes.append(self._lane(
                    instrument_id=instrument_id, symbol=symbol, timeframe=timeframe,
                    raw=lanes_raw.get(timeframe), correlation_id=correlation_id,
                    parity_4h=parity_4h, now=now, source_ids=source_ids,
                    dependency_versions=dependency_versions,
                ))
            missing = tuple(lane.timeframe for lane in lanes if not lane.evidence_eligible)
            generated = now.isoformat()
            source_time = max(lane.source_timestamp for lane in lanes)
            lane_hashes = {lane.timeframe: lane.content_hash for lane in lanes}
            snapshot_seed = hashlib.sha256(json.dumps(lane_hashes, sort_keys=True).encode()).hexdigest()[:20]
            snapshot = seal(MarketContextSnapshot(
                correlation_id=correlation_id, instrument_id=instrument_id, symbol=symbol,
                timeframe="MULTI", source_timestamp=source_time, generated_at=generated,
                as_of=source_time, availability=Availability.AVAILABLE if not missing else Availability.HISTORICAL,
                freshness_state=FreshnessState.FRESH if not missing else FreshnessState.STALE,
                source_ids=dict(source_ids), dependency_versions=dict(dependency_versions),
                completion_status=CompletionStatus.COMPLETE,
                provenance={"service": "ContextEngine", "policy_version": POLICY_VERSION, "advisory_only": True, "execution_influence": "ZERO"},
                snapshot_id=f"ctx_{symbol.lower()}_{snapshot_seed}", lane_hashes=lane_hashes,
                lanes=tuple(lanes), composite_state="ACTIONABLE_CONTEXT" if not missing else "HISTORICAL_OR_INCOMPLETE_CONTEXT",
                mandatory_missing=missing,
            ))
            self._last_snapshot = snapshot
            _atomic_write(self.snapshot_path, snapshot.to_dict())
            self._index["_build_signature"] = build_signature
            _atomic_write(self.index_path, self._index)
            self._stats["last_build_ms"] = round((perf_counter() - started) * 1000, 3)
            self._persist_diagnostics(now)
            return snapshot

    def invalidate(self, timeframe: str, reason: str, *, provisional: bool = True) -> None:
        if timeframe not in SUPPORTED_TIMEFRAMES or not str(reason).strip():
            raise ValueError("invalid invalidation")
        with self._lock:
            current = dict(self._index.get(timeframe) or {})
            current.update({"valid": False, "reason": str(reason), "provisional": bool(provisional), "invalidated_at": self.clock().isoformat()})
            self._index[timeframe] = current
            self._stats["invalidations"] += 1
            _atomic_write(self.index_path, self._index)
            self._persist_diagnostics(self.clock())

    def latest_snapshot(self) -> MarketContextSnapshot | None:
        return self._last_snapshot

    def latest_lane(self, timeframe: str) -> TimeframeContext | None:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            return None
        pointer = self._index.get(timeframe) or {}
        if not pointer.get("valid") or not pointer.get("content_hash"):
            return None
        return self._read_lane(timeframe, pointer["content_hash"])

    def diagnostics(self) -> dict[str, Any]:
        now = self.clock()
        lanes = {}
        for tf in SUPPORTED_TIMEFRAMES:
            lane = self.latest_lane(tf)
            pointer = dict(self._index.get(tf) or {})
            lanes[tf] = {
                "content_hash": lane.content_hash if lane else pointer.get("content_hash"),
                "valid": bool(lane), "cache_key": pointer.get("cache_key"),
                "invalidation_reason": pointer.get("reason"),
                "provisional": pointer.get("provisional", lane.provisional if lane else None),
                "source_boundary": lane.candle.bar_end if lane and lane.candle else None,
                "lane_age_seconds": round((now - _aware(lane.as_of).astimezone(now.tzinfo)).total_seconds(), 3) if lane else None,
            }
        return {"status": "AVAILABLE", "policy_version": POLICY_VERSION, "cache": deepcopy(self._stats), "lanes": lanes,
                "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                "advisory_only": True, "execution_influence": "ZERO"}

    @staticmethod
    def _lane_freshness_is_current(lane: TimeframeContext, timeframe: str, now: datetime) -> bool:
        """Prevent a cached lane from surviving across its freshness boundary."""
        age = max(0.0, (now - _aware(lane.as_of).astimezone(now.tzinfo)).total_seconds())
        expected = FreshnessState.FRESH if age <= FRESHNESS_SECONDS[timeframe] else FreshnessState.STALE
        return lane.freshness_state is expected

    def _lane(self, *, instrument_id, symbol, timeframe, raw, correlation_id, parity_4h, now, source_ids, dependency_versions):
        if raw is None:
            return self._unavailable_lane(instrument_id, symbol, timeframe, correlation_id, now, source_ids, dependency_versions, "SOURCE_BOUNDARY_UNAVAILABLE")
        candle = self._candle(instrument_id, symbol, timeframe, raw, correlation_id, now, source_ids, dependency_versions)
        key_body = {"instrument_id": instrument_id, "timeframe": timeframe, "candle_hash": candle.content_hash,
                    "dependencies": dict(dependency_versions), "policy": POLICY_VERSION, "parity_4h": parity_4h}
        cache_key = hashlib.sha256(json.dumps(key_body, sort_keys=True).encode()).hexdigest()
        pointer = self._index.get(timeframe) or {}
        if pointer.get("valid") and pointer.get("cache_key") == cache_key:
            cached = self._read_lane(timeframe, pointer.get("content_hash"))
            if cached:
                self._stats["hits"] += 1
                return cached
        self._stats["misses"] += 1
        self._stats["lane_builds"][timeframe] += 1
        age = max(0.0, (now - _aware(candle.bar_end).astimezone(now.tzinfo)).total_seconds())
        fresh = age <= FRESHNESS_SECONDS[timeframe]
        historical = not fresh
        reasons = []
        provisional = candle.completion_status is CompletionStatus.PARTIAL_SESSION_BAR
        eligible = fresh and not provisional
        availability = Availability.AVAILABLE if fresh else Availability.HISTORICAL
        parity_proven = parity_4h and bool(dependency_versions.get("tradingview_4h_parity_proof"))
        if timeframe == "4H" and not parity_proven:
            availability, eligible = Availability.UNAVAILABLE, False
            reasons.append("TRADINGVIEW_CANONICAL_4H_PARITY_UNPROVEN")
        if provisional:
            reasons.append("PARTIAL_SESSION_BAR")
        lane = seal(TimeframeContext(
            correlation_id=correlation_id, instrument_id=instrument_id, symbol=symbol, timeframe=timeframe,
            source_timestamp=candle.source_timestamp, generated_at=now.isoformat(), as_of=candle.bar_end,
            availability=availability, freshness_state=FreshnessState.FRESH if fresh else FreshnessState.STALE,
            source_ids={**dict(source_ids), "candle_id": candle.candle_id},
            dependency_versions={**dict(dependency_versions), "candle_hash": candle.content_hash},
            completion_status=candle.completion_status,
            provenance={"service": "ContextEngine", "resampling": raw.get("resampling_source"),
                        "lane_role": LANE_ROLES[timeframe], "execution_influence": "ZERO"},
            lane_id=f"lane_{symbol.lower()}_{timeframe.lower()}_{cache_key[:16]}", cache_key=cache_key,
            candle=candle, lane_state="PROVISIONAL" if provisional else availability.value,
            provisional=provisional, evidence_eligible=eligible, invalidation_reasons=tuple(reasons),
            context_payload={"boundary": {"start": candle.bar_start, "end": candle.bar_end},
                             "lane_role": LANE_ROLES[timeframe], "trading_date": candle.trading_date,
                             "close": candle.close, "range": {"high": candle.high, "low": candle.low},
                             "substrate_only": True, "trade_score": None, "decision": None},
        ))
        path = self._lane_path(timeframe, lane.content_hash)
        if not path.exists():
            _atomic_write(path, lane.to_dict())
        self._index[timeframe] = {"valid": True, "cache_key": cache_key, "content_hash": lane.content_hash,
                                  "updated_at": now.isoformat(), "reason": None, "provisional": provisional}
        _atomic_write(self.index_path, self._index)
        return lane

    def _candle(self, instrument_id, symbol, timeframe, raw, correlation_id, now, source_ids, dependency_versions):
        start, end = _aware(raw["bar_start"]), _aware(raw["bar_end"])
        completion = CompletionStatus(raw.get("completion_status", "COMPLETE"))
        candle_id = f"{instrument_id}:{timeframe}:{start.isoformat()}:{end.isoformat()}"
        security_id = instrument_id.rsplit(":", 1)[-1]
        return seal(CanonicalCandleRef(
            correlation_id=correlation_id, instrument_id=instrument_id, security_id=security_id, symbol=symbol,
            timeframe=timeframe, source_timestamp=end.isoformat(), generated_at=end.isoformat(), as_of=end.isoformat(),
            availability=Availability.HISTORICAL if (now - end.astimezone(now.tzinfo)).total_seconds() > FRESHNESS_SECONDS[timeframe] else Availability.AVAILABLE,
            freshness_state=FreshnessState.STALE if (now - end.astimezone(now.tzinfo)).total_seconds() > FRESHNESS_SECONDS[timeframe] else FreshnessState.FRESH,
            source_ids=dict(source_ids), dependency_versions=dict(dependency_versions), completion_status=completion,
            provenance={"source": raw.get("source", "CANONICAL_PERSISTED_1M"), "resampling_source": raw.get("resampling_source")},
            candle_id=candle_id, bar_start=start.isoformat(), bar_end=end.isoformat(), open=float(raw["open"]),
            high=float(raw["high"]), low=float(raw["low"]), close=float(raw["close"]), volume=float(raw.get("volume") or 0),
            trading_date=start.date().isoformat(),
        ))

    def _unavailable_lane(self, instrument_id, symbol, timeframe, correlation_id, now, source_ids, deps, reason):
        cache_key = hashlib.sha256(f"{instrument_id}:{timeframe}:{reason}:{POLICY_VERSION}".encode()).hexdigest()
        return seal(TimeframeContext(
            correlation_id=correlation_id, instrument_id=instrument_id, symbol=symbol, timeframe=timeframe,
            source_timestamp=now.isoformat(), generated_at=now.isoformat(), as_of=now.isoformat(),
            availability=Availability.UNAVAILABLE, freshness_state=FreshnessState.UNKNOWN,
            source_ids=dict(source_ids), dependency_versions=dict(deps), completion_status=CompletionStatus.COMPLETE,
            provenance={"service": "ContextEngine", "execution_influence": "ZERO"}, lane_id=f"lane_unavailable_{timeframe}",
            cache_key=cache_key, candle=None, lane_state="UNAVAILABLE", provisional=False, evidence_eligible=False,
            invalidation_reasons=(reason,), context_payload={"substrate_only": True, "decision": None},
        ))

    def _normalize_1m(self, rows, symbol):
        result = []
        for raw in rows:
            try:
                start = _aware(raw.get("timestamp") or raw.get("time"))
                result.append({"symbol": symbol, "timeframe": "1m", "timestamp": start.isoformat(),
                               "bar_start": start.isoformat(), "bar_end": (start + timedelta(minutes=1)).isoformat(),
                               "open": float(raw["open"]), "high": float(raw["high"]), "low": float(raw["low"]),
                               "close": float(raw["close"]), "volume": float(raw.get("volume") or 0), "closed": True,
                               "completion_status": "COMPLETE", "source": "CANONICAL_VOB_1M_STORE", "resampling_source": "NONE"})
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(result, key=lambda row: row["timestamp"])

    @staticmethod
    def _adapt_resampled(raw, timeframe):
        start = _aware(raw.get("timestamp") or raw.get("time"))
        minutes = INTERVALS[timeframe]
        end = start + timedelta(minutes=minutes)
        if timeframe == "1H" and start.time() == time(15, 15):
            end = start.replace(hour=15, minute=30)
        return {**dict(raw), "bar_start": start.isoformat(), "bar_end": end.isoformat(),
                "completion_status": "COMPLETE", "resampling_source": "NiftyVOBEngine._resample_1m"}

    def _session_bar(self, rows, timeframe):
        if timeframe == "1D":
            dates = sorted({_aware(row["timestamp"]).date() for row in rows}, reverse=True)
            for trading_date in dates:
                session = [row for row in rows if _aware(row["timestamp"]).date() == trading_date
                           and time(9, 15) <= _aware(row["timestamp"]).time() < time(15, 30)]
                start = datetime.combine(trading_date, time(9, 15), IST)
                end = datetime.combine(trading_date, time(15, 30), IST)
                if session and _aware(session[-1]["bar_end"]) >= end:
                    return self._aggregate_session(session, start, end, "COMPLETE")
            return None

        latest_date = _aware(rows[-1]["timestamp"]).date()
        session = [row for row in rows if _aware(row["timestamp"]).date() == latest_date
                   and time(9, 15) <= _aware(row["timestamp"]).time() < time(15, 30)]
        if not session:
            return None
        cutoff = datetime.combine(latest_date, time(13, 15), IST)
        if _aware(session[-1]["bar_end"]) < cutoff:
            return None
        later = [row for row in session if _aware(row["timestamp"]) >= cutoff]
        if later:
            return self._aggregate_session(
                later, cutoff, datetime.combine(latest_date, time(15, 30), IST), "PARTIAL_SESSION_BAR"
            )
        return self._aggregate_session(
            session, datetime.combine(latest_date, time(9, 15), IST), cutoff, "COMPLETE"
        )

    @staticmethod
    def _aggregate_session(session, start, end, completion):
        return {"bar_start": start.isoformat(), "bar_end": end.isoformat(), "open": session[0]["open"],
                "high": max(row["high"] for row in session), "low": min(row["low"] for row in session),
                "close": session[-1]["close"], "volume": sum(row["volume"] for row in session),
                "completion_status": completion, "source": "CANONICAL_VOB_1M_STORE",
                "resampling_source": "ExchangeSessionBoundaryAdapter"}

    def _load_candles(self):
        try:
            raw = json.loads(self.candle_path.read_text(encoding="utf-8"))
            return raw.get("candles", raw) if isinstance(raw, dict) else raw
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _load_index(self):
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ContextStateError("CONTEXT_INDEX_CORRUPT") from error

    def _load_snapshot(self):
        try:
            raw = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            return record_from_dict(MarketContextSnapshot, raw)
        except FileNotFoundError:
            return None
        except Exception as error:
            raise ContextStateError("CONTEXT_SNAPSHOT_CORRUPT") from error

    def _read_lane(self, timeframe, content_hash):
        try:
            return record_from_dict(TimeframeContext, json.loads(self._lane_path(timeframe, content_hash).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _lane_path(self, timeframe, content_hash):
        return self.records_root / timeframe / f"{content_hash}.json"

    def _persist_diagnostics(self, now):
        _atomic_write(self.diagnostics_path, {"generated_at": now.isoformat(), "cache": self._stats, "index": self._index,
                                              "advisory_only": True, "execution_influence": "ZERO"})
