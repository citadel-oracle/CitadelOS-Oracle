"""Deterministic, advisory-only NIFTY Options Structure Engine (OSE).

OSE observes one stable 100-point ITM call/put pair.  It consumes the existing
ARGUS option-chain fanout, stores contract candles separately from Strategy Lab
and NIFTY VOB state, and never participates in execution.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.data.data_engine import DataEngine
from src.paper_trading.contracts import ContractResolutionError, DhanInstrumentMaster
from src.vob import NiftyVOBEngine
from src.ose.option_flow import calculate_option_flow, directional_edge
from src.ose.presentation import (
    build_ssi,
    decision_window,
    detect_transition,
    engine_agreement,
    structural_read,
    transition_snapshot,
)


IST = ZoneInfo("Asia/Kolkata")


class OptionsStructureEngine:
    """Read-only market intelligence for one locked NIFTY CE/PE pair."""

    TIMEFRAMES = ("1m", "3m", "5m")
    ROLLOVER_COOLDOWN_SECONDS = 15 * 60
    MAX_CANDLES = 6000
    EXECUTION_INFLUENCE = "ZERO"
    STRATEGY_INFLUENCE = 0
    SCORE_WEIGHTS = {
        "vob_direction": 32,
        "timeframe_agreement": 15,
        "ema_50": 15,
        "supertrend": 15,
        "break_retest_quality": 10,
        "freshness": 5,
        "zone_distance": 4,
        "lifecycle_quality": 4,
    }

    def __init__(
        self,
        *,
        dhan: Any,
        instrument_master: Any | None = None,
        state_root: str | Path = "logs/options_structure",
        spot_candle_path: str | Path = "logs/vob_1m_candles.json",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.dhan = dhan
        self.instrument_master = instrument_master or DhanInstrumentMaster()
        self.state_root = Path(state_root)
        self.state_path = self.state_root / "state.json"
        self.projection_path = self.state_root / "projection.json"
        self.candle_root = self.state_root / "candles"
        self.spot_candle_path = Path(spot_candle_path)
        self.clock = clock or (lambda: datetime.now(IST))
        self._lock = threading.RLock()
        self._state = self._load_json(self.state_path) or self._empty_state()
        self._projection = self._load_json(self.projection_path) or self._unavailable("WAITING_FOR_PAIR")
        self._live: dict[str, dict[str, Any] | None] = {"CE": None, "PE": None}
        self._last_volume: dict[str, float | None] = {"CE": None, "PE": None}
        self._last_spot_bucket: str | None = self._state.get("last_spot_bucket")
        self._flow_previous: dict[str, Any] = deepcopy(self._state.get("flow_previous") or {})
        self._calculation_count = 0
        self._history_reconciled_key: str | None = None
        self._history_reconcile_attempt: str | None = None
        # Selected-contract history is presentation-only and can involve Dhan
        # history I/O.  It must never hold the canonical OSE projection lock.
        self._contract_technical_lock = threading.RLock()
        self._contract_technical_cache: dict[str, dict[str, Any]] = {}
        self._resample_cache: dict[tuple[str, int, str], dict[str, Any]] = {}
        # perf(serialization): cache the last serialized projection bytes so that
        # identical payloads skip the json.dump + fsync + atomic rename on disk.
        self._last_projection_bytes: bytes | None = None
        self._last_projection_serialized_len: int = 0

    @staticmethod
    def nearest_anchor(spot: float) -> int:
        """Nearest 100, with a deterministic half-up boundary."""

        return int(math.floor((float(spot) + 50.0) / 100.0) * 100)

    @classmethod
    def strikes_for_anchor(cls, anchor: int) -> dict[str, int]:
        if int(anchor) % 100:
            raise ValueError("OSE anchor must be a 100-point strike")
        return {"CE": int(anchor) - 100, "PE": int(anchor) + 100}

    @staticmethod
    def selection_for_spot(spot: float) -> dict[str, int]:
        """Return the locked 100-point OSE pair for one authoritative spot."""

        value = float(spot)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("OSE spot must be a positive finite number")
        lower = int(math.floor(value / 100.0) * 100)
        upper = int(math.ceil(value / 100.0) * 100)
        return {
            "anchor": lower,
            "CE": lower - 100,
            "PE": upper + 100,
            "lower_boundary": lower,
            "upper_boundary": lower + 100,
        }

    def ingest(self, snapshot: Mapping[str, Any] | None) -> None:
        """Consume the already-fetched ARGUS snapshot; never polls ARGUS itself."""

        started = perf_counter()
        source_status = str(snapshot.get("status") or "").lower() if isinstance(snapshot, Mapping) else ""
        if not isinstance(snapshot, Mapping) or source_status not in {"available", "stale"}:
            self._publish_unavailable("ARGUS_UNAVAILABLE")
            return
        payload = snapshot.get("data")
        underlying = payload.get("underlying") if isinstance(payload, Mapping) else None
        if not isinstance(underlying, Mapping) or str(underlying.get("symbol") or "").upper() != "NIFTY":
            self._publish_unavailable("NIFTY_UNDERLYING_UNAVAILABLE")
            return
        try:
            observed_at = self._aware(
                underlying.get("source_event_time") or underlying.get("fetched_at")
            )
            spot = float(underlying.get("ltp"))
        except (TypeError, ValueError):
            self._publish_unavailable("ARGUS_SPOT_INVALID")
            return
        if source_status == "stale" and str(underlying.get("market_state") or "").upper() == "OPEN":
            cache = snapshot.get("cache")
            threshold = self._number(cache.get("projection_freshness_seconds")) if isinstance(cache, Mapping) else None
            threshold = threshold if threshold is not None and threshold > 0 else 20.0
            source_age = max(0.0, (self.clock() - observed_at).total_seconds())
            if source_age <= threshold:
                source_status = "available"
        rows = [row for row in payload.get("atm_window") or [] if isinstance(row, Mapping)]

        with self._lock:
            try:
                self._state["market_state"] = str(
                    underlying.get("market_state") or "UNKNOWN"
                ).upper()
                self._update_participation_baseline(
                    payload, underlying, observed_at, source_status,
                )
                selection = self.selection_for_spot(spot)
                if not isinstance(self._state.get("pair"), Mapping):
                    self._activate_pair(
                        selection["anchor"], underlying, rows, observed_at,
                        "INITIAL_SELECTION", strikes=selection,
                    )
                self._consider_rollover(underlying, rows, observed_at, spot)
                pair = self._state.get("pair")
                if not isinstance(pair, Mapping):
                    self._projection = self._unavailable(self._state.get("reason") or "PAIR_UNAVAILABLE")
                    return
                completed = self._reconcile_current_session_history(observed_at)
                if source_status == "available":
                    self._state["runtime_status"] = "LIVE"
                    self._state["reason"] = None
                    for side in ("CE", "PE"):
                        completed = self._update_contract(side, rows, observed_at) or completed
                if source_status == "stale" and isinstance(self._state.get("option_flow"), Mapping):
                    option_flow = deepcopy(self._state["option_flow"])
                    previous_edge = option_flow.get("edge") if isinstance(option_flow.get("edge"), Mapping) else {}
                    last_authoritative_state = previous_edge.get("last_authoritative_state")
                    if option_flow.get("status") == "LIVE":
                        last_authoritative_state = previous_edge.get("state") or option_flow.get("state")
                    option_flow.update({"state": "DATA STALE", "status": "DATA STALE"})
                    option_flow["edge"] = directional_edge(
                        option_flow.get("call") or {}, option_flow.get("put") or {}, fresh=False,
                    )
                    option_flow["edge"]["last_authoritative_state"] = last_authoritative_state
                    source_timestamp = option_flow.get("source_timestamp")
                    if source_timestamp:
                        option_flow["age_seconds"] = round(max(0.0, (observed_at - self._aware(source_timestamp)).total_seconds()), 3)
                    for leg in (option_flow.get("call"), option_flow.get("put")):
                        if isinstance(leg, dict):
                            leg["status"] = "DATA STALE"
                    flow_snapshot = self._flow_previous
                else:
                    option_flow, flow_snapshot = calculate_option_flow(
                        rows, self._state["pair"]["contracts"], observed_at, source_status, self._flow_previous,
                    )
                self._state["option_flow"] = option_flow
                if source_status == "available":
                    self._flow_previous = flow_snapshot
                    self._state["flow_previous"] = deepcopy(flow_snapshot)
                self._state["spot"] = spot
                self._state["source_timestamp"] = observed_at.isoformat()
                self._state["updated_at"] = self.clock().isoformat()
                if completed or self._projection.get("status") in {"UNAVAILABLE", "WARMING UP", "INSUFFICIENT HISTORY"}:
                    self._projection = self._calculate_projection(spot, observed_at)
                elif source_status == "stale":
                    self._projection = deepcopy(self._projection)
                    self._projection["option_flow"] = deepcopy(option_flow)
                else:
                    self._projection = self._update_live_projection(self._projection, spot, rows, observed_at)
                self._projection["source_freshness"] = source_status.upper()
                self._projection["market_state"] = self._state["market_state"]
                self._projection["participation_baseline"] = deepcopy(
                    self._state.get("participation_baseline")
                )
                if source_status == "stale":
                    self._projection.update({
                        "status": "STALE", "runtime_status": "STALE",
                        "reason": "ARGUS_POST_MARKET_CACHE",
                    })
                    self._projection.setdefault("data_quality", {})["status"] = "STALE"
                self._projection["performance"]["ingestion_ms"] = round((perf_counter() - started) * 1000, 3)
                self._persist_state()
                self._write_projection()
            except ContractResolutionError:
                self._state.update({
                    "runtime_status": "BLOCKED",
                    "reason": "CURRENT_CONTRACT_PAIR_UNAVAILABLE",
                })
                self._projection = self._unavailable(
                    "CURRENT_CONTRACT_PAIR_UNAVAILABLE"
                )
                self._persist_state()
                self._write_projection()
            except Exception as exc:
                self._projection = self._unavailable(f"OSE_CALCULATION_ERROR:{type(exc).__name__}")

    def projection(self) -> dict[str, Any]:
        started = perf_counter()
        with self._lock:
            result = deepcopy(self._projection)
            # perf(serialization): read cached byte count without serializing again.
            cached_serialized_len = self._last_projection_serialized_len
        for contract in (result.get("contracts") or {}).values():
            if not isinstance(contract, Mapping):
                continue
            composite = contract.get("composite")
            vob = contract.get("vob")
            trend = contract.get("trend")
            if isinstance(composite, dict) and not composite.get("explanation"):
                composite["explanation"] = self._composite_explanation(
                    str(vob.get("state") or "NEUTRAL") if isinstance(vob, Mapping) else "NEUTRAL",
                    str(trend.get("state") or "NEUTRAL") if isinstance(trend, Mapping) else "NEUTRAL",
                    str(composite.get("state") or "LOW EDGE"),
                )
        self._decorate_projection(result, record_transitions=False)
        # perf(serialization): avoid a full json.dumps just to count bytes.
        # Use the byte count from the last committed write; the API caller
        # only uses this for observability — it never changes the response body.
        result.setdefault("performance", {})["api_serialization_ms"] = round((perf_counter() - started) * 1000, 3)
        result["performance"]["serialized_bytes"] = cached_serialized_len
        return result

    def contract_technicals(
        self,
        contract: Mapping[str, Any],
        observed_at: Any,
    ) -> dict[str, Any]:
        """Return completed-candle technicals for one ARGUS-selected contract.

        This reuses OSE's canonical Dhan history, resampling, VOB, EMA and
        Supertrend implementations. It is presentation-only, cached by the
        latest completed five-minute boundary, and never changes the locked OSE
        pair or any execution state.
        """

        total_started = perf_counter()
        side = str(contract.get("side") or contract.get("option_type") or "").upper()
        security_id = str(contract.get("security_id") or "")
        expiry = str(contract.get("expiry") or "")
        strike = self._number(contract.get("strike"))
        if side not in {"CE", "PE"} or not security_id or not expiry or strike is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "SELECTED_CONTRACT_IDENTITY_UNAVAILABLE",
            }
        observed = self._aware(observed_at)
        completed_boundary = observed.replace(
            minute=(observed.minute // 5) * 5,
            second=0,
            microsecond=0,
        )
        cache_key = f"{security_id}:{completed_boundary.isoformat()}"
        with self._contract_technical_lock:
            cached = self._contract_technical_cache.get(cache_key)
            if isinstance(cached, Mapping):
                return deepcopy(dict(cached))

            normalized = {
                "security_id": security_id,
                "exchange_segment": "NSE_FNO",
                "underlying": "NIFTY",
                "option_type": side,
                "strike": strike,
                "expiry": expiry,
                "trading_symbol": str(
                    contract.get("trading_symbol")
                    or self._trading_symbol(expiry, int(strike), side)
                ),
            }
            candle_started = perf_counter()
            one_minute = self._load_or_fetch_history(normalized, observed)
            if one_minute:
                self._write_candles(normalized, one_minute)
            refresh_1m_ms = round((perf_counter() - candle_started) * 1000, 3)
            three_started = perf_counter()
            three = self._incremental_resample(one_minute, 3, security_id)
            refresh_3m_ms = round((perf_counter() - three_started) * 1000, 3)
            five_started = perf_counter()
            five = self._incremental_resample(one_minute, 5, security_id)
            refresh_5m_ms = round((perf_counter() - five_started) * 1000, 3)
            if len(five) < 50:
                result = {
                    "status": "UNAVAILABLE",
                    "reason": "SELECTED_CONTRACT_5M_HISTORY_INSUFFICIENT",
                    "security_id": security_id,
                    "side": side,
                    "completed_5m_count": len(five),
                    "completed_3m_count": len(three),
                    "completed_1m_count": len(one_minute),
                    "performance": {
                        "cache_hit": False, "refresh_1m_ms": refresh_1m_ms,
                        "refresh_3m_ms": refresh_3m_ms, "refresh_5m_ms": refresh_5m_ms,
                        "candle_retrieval_ms": refresh_1m_ms,
                        "feature_retrieval_ms": 0.0,
                        "total_ms": round((perf_counter() - total_started) * 1000, 3),
                    },
                }
                self._contract_technical_cache[cache_key] = result
                while len(self._contract_technical_cache) > 8:
                    self._contract_technical_cache.pop(
                        next(iter(self._contract_technical_cache))
                    )
                return deepcopy(result)

            feature_started = perf_counter()
            completed_premium = float(five[-1]["close"])
            current_premium = (
                self._number(contract.get("premium")) or completed_premium
            )
            trend = self._trend(five)
            engine = NiftyVOBEngine(
                persistence_path=self.state_root
                / f"prime_vob_{side}_{security_id}_3m.json"
            )
            raw_vob = engine.analyze_timeframe(
                timeframe="3m",
                candles=three,
                current_nifty_price=completed_premium,
                now=observed,
            )
            structure = self._classify_structure(raw_vob, three, normalized)
            demand = structure.get("demand")
            supply = structure.get("supply")
            latest = five[-1]
            previous = five[-2] if len(five) > 1 else None
            pullback_state = "WAITING_FOR_5M_PULLBACK"
            active_levels: list[str] = []
            for label, zone in (
                ("EMA21", trend.get("ema_21_zone")),
                ("EMA50", trend.get("ema_50_zone")),
                ("SUPERTREND", trend.get("supertrend_zone")),
            ):
                if (
                    isinstance(zone, Mapping)
                    and float(zone["low"]) <= completed_premium <= float(zone["high"])
                ):
                    active_levels.append(label)
            trend_valid = (
                trend.get("supertrend_direction") == "POSITIVE"
                and trend.get("supertrend_value") is not None
                and completed_premium >= float(trend["supertrend_value"])
            )
            if not trend_valid:
                pullback_state = "PULLBACK_FAILED"
            elif active_levels:
                pullback_state = "PULLBACK_ACTIVE"
            elif (
                isinstance(previous, Mapping)
                and any(
                    isinstance(zone, Mapping)
                    and float(previous["low"]) <= float(zone["high"])
                    and float(latest["close"]) > float(latest["open"])
                    and float(latest["close"]) > float(zone["high"])
                    for zone in (
                        trend.get("ema_21_zone"),
                        trend.get("ema_50_zone"),
                        trend.get("supertrend_zone"),
                    )
                )
            ):
                pullback_state = "PULLBACK_CONFIRMED"

            result = {
                "status": "AVAILABLE",
                "reason": None,
                "security_id": security_id,
                "side": side,
                "strike": strike,
                "expiry": expiry,
                "trading_symbol": normalized["trading_symbol"],
                "current_premium": current_premium,
                "completed_5m_premium": completed_premium,
                "trend": trend,
                "vob_3m": {
                    "state": structure.get("state"),
                    "support": deepcopy(demand) if isinstance(demand, Mapping) else None,
                    "resistance": deepcopy(supply) if isinstance(supply, Mapping) else None,
                    "support_buy_zone": (
                        {
                            "low": demand.get("zone_low"),
                            "high": demand.get("zone_high"),
                        }
                        if isinstance(demand, Mapping)
                        else None
                    ),
                    "breakout_trigger": (
                        supply.get("zone_high")
                        if isinstance(supply, Mapping)
                        else None
                    ),
                    "evaluated_through": structure.get("evaluated_through"),
                },
                "pullback_state": pullback_state,
                "active_levels": active_levels,
                "completed_5m_timestamp": latest.get("timestamp"),
                "completed_5m_close_timestamp": latest.get("candle_closed_at"),
                "completed_3m_timestamp": (
                    three[-1].get("timestamp") if three else None
                ),
                "source_timestamp": observed.isoformat(),
                "freshness": "FRESH",
                "source": "DHAN_DATA_API_COMPLETED_OPTION_CANDLES",
                "candle_count": len(five),
                "completed_1m_count": len(one_minute),
                "completed_3m_count": len(three),
                "completed_5m_count": len(five),
                "latest_completed_5m_volume": float(latest.get("volume") or 0.0),
                "forming_candle_excluded": True,
            }
            result["performance"] = {
                "cache_hit": False, "refresh_1m_ms": refresh_1m_ms,
                "refresh_3m_ms": refresh_3m_ms, "refresh_5m_ms": refresh_5m_ms,
                "candle_retrieval_ms": refresh_1m_ms,
                "feature_retrieval_ms": round((perf_counter() - feature_started) * 1000, 3),
                "total_ms": round((perf_counter() - total_started) * 1000, 3),
            }
            self._contract_technical_cache[cache_key] = result
            while len(self._contract_technical_cache) > 8:
                self._contract_technical_cache.pop(
                    next(iter(self._contract_technical_cache))
                )
            return deepcopy(result)

    def _activate_pair(
        self,
        anchor: int,
        underlying: Mapping[str, Any],
        rows: list[Mapping[str, Any]],
        observed_at: datetime,
        reason: str,
        *,
        strikes: Mapping[str, int] | None = None,
    ) -> None:
        selected = dict(strikes or self.strikes_for_anchor(anchor))
        expiry = str(underlying.get("expiry") or "")
        if not expiry:
            self._state.update({
                "runtime_status": "BLOCKED",
                "reason": "CURRENT_EXPIRY_UNAVAILABLE",
            })
            return
        contracts = {
            side: self._resolve_contract(side, selected[side], expiry, rows)
            for side in ("CE", "PE")
        }
        if contracts["CE"]["expiry"] != contracts["PE"]["expiry"]:
            self._state.update({"runtime_status": "EXPIRY MISMATCH", "reason": "PAIR_EXPIRY_MISMATCH"})
            return

        histories = {side: self._load_or_fetch_history(contracts[side], observed_at) for side in ("CE", "PE")}
        previous = self._state.get("pair")
        audit = list(self._state.get("rollover_audit") or [])
        if isinstance(previous, Mapping):
            audit.append({
                "from_anchor": previous.get("anchor"),
                "to_anchor": anchor,
                "old_ce": deepcopy(previous.get("contracts", {}).get("CE")),
                "old_pe": deepcopy(previous.get("contracts", {}).get("PE")),
                "reason": reason,
                "completed_5m_candle": self._last_spot_bucket,
                "activated_at": observed_at.isoformat(),
            })
        self._state.update({
            "pair": {
                "anchor": anchor,
                "expiry": expiry,
                "contracts": contracts,
                "activated_at": observed_at.isoformat(),
                "status": "PAIR LOCKED",
                "selection_floor": selected.get("lower_boundary", anchor),
                "selection_ceiling": selected.get("upper_boundary", anchor + 100),
            },
            "market_context": {
                "symbol": "NIFTY",
                "trading_date": str(underlying.get("trading_date") or observed_at.date().isoformat()),
                "spot": float(underlying.get("ltp")),
                "expiry": expiry,
                "expiry_source": "DHAN_INSTRUMENT_MASTER_OPTION_CHAIN",
                "source_timestamp": observed_at.isoformat(),
                "resolved_at": self.clock().isoformat(),
                "ce_security_id": contracts["CE"]["security_id"],
                "pe_security_id": contracts["PE"]["security_id"],
                "ce_strike": contracts["CE"]["strike"],
                "pe_strike": contracts["PE"]["strike"],
            },
            "runtime_status": "WARMING UP",
            "reason": None,
            "last_rollover_at": observed_at.isoformat() if previous else None,
            "rollover_audit": audit[-20:],
        })
        self._live = {"CE": None, "PE": None}
        self._last_volume = {"CE": None, "PE": None}
        if isinstance(previous, Mapping):
            self._flow_previous = {}
            self._state["flow_previous"] = {}
            self._state["option_flow"] = None
        for side in ("CE", "PE"):
            self._write_candles(contracts[side], histories[side])
        current_five_minute_bucket = self._current_five_minute_bucket(observed_at)
        if all(not self._current_session_missing(histories[side], current_five_minute_bucket) for side in ("CE", "PE")):
            self._history_reconciled_key = self._history_key(observed_at)

    def _resolve_contract(
        self, side: str, strike: int, expiry: str, rows: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        if strike % 100:
            raise ContractResolutionError("OSE rejects non-100-point strikes")
        row = next((item for item in rows if abs(float(item.get("strike", -1)) - strike) < 0.001), None)
        leg = row.get(side.lower()) if isinstance(row, Mapping) else None
        if not isinstance(leg, Mapping) or leg.get("security_id") is None:
            raise ContractResolutionError(f"OSE {side} contract unavailable at {strike}")
        arguments = {
            "security_id": str(leg["security_id"]), "expiry": expiry,
            "strike": strike, "option_type": side, "underlying": "NIFTY",
        }
        try:
            master = self.instrument_master.resolve(**arguments)
        except TypeError:
            arguments.pop("underlying")
            master = self.instrument_master.resolve(**arguments)
        return {
            "security_id": str(master["security_id"]),
            "exchange_segment": str(master["exchange_segment"]),
            "underlying": "NIFTY", "option_type": side, "strike": strike,
            "expiry": expiry, "lot_size": int(master["lot_size"]),
            "instrument_source": str(master["source"]),
            "quote_source": "DHAN_OPTION_CHAIN",
            "trading_symbol": self._trading_symbol(expiry, strike, side),
        }

    def _load_or_fetch_history(self, contract: Mapping[str, Any], observed_at: datetime) -> list[dict[str, Any]]:
        existing = self._read_candles(contract)
        start = observed_at.date() if len(existing) >= 250 else observed_at.date() - timedelta(days=20)
        response = self.dhan.get_intraday_candles(
            segment="NSE_FNO", security_id=contract["security_id"], instrument="OPTIDX",
            interval="1", from_date=start.isoformat(), to_date=observed_at.date().isoformat(),
        )
        fetched = []
        if isinstance(response, Mapping) and response.get("success") is True:
            fetched = [
                normalized for row in response.get("candles") or []
                if (normalized := self._history_candle(row, contract, observed_at)) is not None
            ]
        return self._dedupe([*existing, *fetched])[-self.MAX_CANDLES:]

    def _reconcile_current_session_history(self, observed_at: datetime) -> bool:
        pair = self._state.get("pair")
        if not isinstance(pair, Mapping):
            return False
        reconciliation_key = self._history_key(observed_at)
        if self._history_reconciled_key == reconciliation_key:
            return False
        attempt = f"{reconciliation_key}:{observed_at.replace(second=0, microsecond=0).isoformat()}"
        if self._history_reconcile_attempt == attempt:
            return False
        self._history_reconcile_attempt = attempt
        changed = False
        complete = True
        current_five_minute_bucket = self._current_five_minute_bucket(observed_at)
        for side in ("CE", "PE"):
            contract = pair["contracts"][side]
            existing = self._read_candles(contract)
            reconciled = self._load_or_fetch_history(contract, observed_at)
            if [row.get("timestamp") for row in reconciled] != [row.get("timestamp") for row in existing]:
                self._write_candles(contract, reconciled)
                changed = True
            if self._current_session_missing(reconciled, current_five_minute_bucket):
                complete = False
        if complete:
            self._history_reconciled_key = reconciliation_key
        return changed

    def _current_five_minute_bucket(self, observed_at: datetime) -> datetime:
        observed = self._aware(observed_at)
        return observed.replace(
            minute=(observed.minute // 5) * 5,
            second=0,
            microsecond=0,
        )

    def _history_key(self, observed_at: datetime) -> str:
        pair = self._state.get("pair")
        contracts = pair.get("contracts") if isinstance(pair, Mapping) else {}
        current_five_minute_bucket = self._current_five_minute_bucket(observed_at)
        latest_completed = current_five_minute_bucket - timedelta(minutes=1)
        return ":".join([
            observed_at.date().isoformat(),
            str((contracts or {}).get("CE", {}).get("security_id") or ""),
            str((contracts or {}).get("PE", {}).get("security_id") or ""),
            latest_completed.isoformat(),
        ])

    @classmethod
    def _current_session_missing(
        cls, rows: Sequence[Mapping[str, Any]], observed_at: datetime
    ) -> list[str]:
        observed = cls._aware(observed_at)
        if observed.weekday() >= 5:
            return []
        session_start = observed.replace(hour=9, minute=15, second=0, microsecond=0)
        final_bucket = observed.replace(hour=15, minute=29, second=0, microsecond=0)
        latest_completed = min(observed.replace(second=0, microsecond=0) - timedelta(minutes=1), final_bucket)
        if latest_completed < session_start:
            return []
        available = {
            cls._aware(row.get("timestamp") or row.get("time")).replace(second=0, microsecond=0)
            for row in rows
            if row.get("timestamp") or row.get("time")
            if cls._aware(row.get("timestamp") or row.get("time")).date() == observed.date()
        }
        expected_count = int((latest_completed - session_start).total_seconds() // 60) + 1
        return [
            (session_start + timedelta(minutes=index)).isoformat()
            for index in range(expected_count)
            if session_start + timedelta(minutes=index) not in available
        ]

    def _update_contract(self, side: str, rows: list[Mapping[str, Any]], observed_at: datetime) -> bool:
        contract = self._state["pair"]["contracts"][side]
        row = next((item for item in rows if abs(float(item.get("strike", -1)) - float(contract["strike"])) < 0.001), None)
        leg = row.get(side.lower()) if isinstance(row, Mapping) else None
        if not isinstance(leg, Mapping) or str(leg.get("security_id")) != str(contract["security_id"]):
            self._state["runtime_status"] = "PARTIAL PAIR"
            self._state["reason"] = f"{side}_QUOTE_UNAVAILABLE"
            return False
        try:
            price = float(leg["ltp"])
        except (KeyError, TypeError, ValueError):
            return False
        bucket = observed_at.replace(second=0, microsecond=0)
        volume = self._number(leg.get("volume"))
        previous_volume = self._last_volume[side]
        incremental = max(0.0, volume - previous_volume) if volume is not None and previous_volume is not None else 0.0
        if volume is not None:
            self._last_volume[side] = volume
        live = self._live[side]
        completed = False
        if live is not None and self._aware(live["timestamp"]) < bucket:
            # Option-chain polling supplies a quote, not authoritative candle
            # OHLCV.  The prior forming bucket is discarded here and only the
            # Dhan intraday-history reconciliation above may persist it.
            live = None
        if live is None:
            self._live[side] = {
                "symbol": contract["trading_symbol"], "underlying": "NIFTY", "timeframe": "1m",
                "timestamp": bucket.isoformat(), "open": price, "high": price, "low": price, "close": price,
                "volume": incremental, "source": "DHAN_OPTION_CHAIN", "received_at": observed_at.isoformat(),
                "contract": contract["security_id"], "closed": False, "is_closed": False,
            }
        else:
            live["high"] = max(float(live["high"]), price)
            live["low"] = min(float(live["low"]), price)
            live["close"] = price
            live["volume"] = float(live.get("volume") or 0.0) + incremental
            live["received_at"] = observed_at.isoformat()
        return completed

    def _consider_rollover(
        self,
        underlying: Mapping[str, Any],
        rows: list[Mapping[str, Any]],
        observed_at: datetime,
        spot: float,
    ) -> None:
        pair = self._state.get("pair")
        if not isinstance(pair, Mapping):
            return
        expiry = str(underlying.get("expiry") or "")
        if not expiry:
            self._state.update({
                "runtime_status": "BLOCKED",
                "reason": "CURRENT_EXPIRY_UNAVAILABLE",
            })
            return
        selection = self.selection_for_spot(spot)
        current_contracts = pair.get("contracts") or {}
        expiry_changed = str(pair.get("expiry") or "") != expiry
        strikes_changed = any(
            int((current_contracts.get(side) or {}).get("strike", -1))
            != selection[side]
            for side in ("CE", "PE")
        )
        if not expiry_changed and not strikes_changed:
            self._state["rollover_state"] = "LOCKED"
            return
        self._state["rollover_state"] = "SWITCHING"
        started = perf_counter()
        try:
            self._activate_pair(
                selection["anchor"],
                underlying,
                rows,
                observed_at,
                "AUTHORITATIVE_EXPIRY_ROLLOVER"
                if expiry_changed
                else "SPOT_100_POINT_BOUNDARY",
                strikes=selection,
            )
            self._state["last_rollover_duration_ms"] = round((perf_counter() - started) * 1000, 3)
            self._state["rollover_state"] = "LOCKED"
        except Exception as exc:
            self._state["rollover_state"] = "ARMED"
            self._state["reason"] = f"ROLLOVER_FAILED:{type(exc).__name__}"

    def _calculate_projection(self, spot: float, observed_at: datetime) -> dict[str, Any]:
        started = perf_counter()
        contracts: dict[str, Any] = {}
        for side in ("CE", "PE"):
            contract = self._state["pair"]["contracts"][side]
            one_minute = self._read_candles(contract)
            three = self._incremental_resample(one_minute, 3, contract["security_id"])
            five = self._incremental_resample(one_minute, 5, contract["security_id"])
            premium = float(self._live[side]["close"]) if self._live[side] else (float(one_minute[-1]["close"]) if one_minute else None)
            timeframe_rows = {"1m": one_minute, "3m": three, "5m": five}
            structures: dict[str, Any] = {}
            for timeframe in self.TIMEFRAMES:
                engine = NiftyVOBEngine(
                    persistence_path=self.state_root
                    / f"vob_{side}_{contract['security_id']}_{timeframe}.json"
                )
                raw = engine.analyze_timeframe(
                    timeframe=timeframe, candles=timeframe_rows[timeframe], current_nifty_price=premium,
                    now=observed_at,
                )
                structures[timeframe] = self._classify_structure(raw, timeframe_rows[timeframe], contract)
            vob_wheel = self._vob_wheel(structures)
            trend = self._trend(five)
            quality = self._quality(one_minute, five, observed_at)
            composite = self._composite(vob_wheel, trend)
            score, breakdown = self._score(vob_wheel, trend, structures, quality)
            contracts[side] = {
                "contract": deepcopy(contract), "premium": premium,
                "vob": vob_wheel, "trend": trend, "composite": composite,
                "structures": structures, "score": score, "score_breakdown": breakdown,
                "quality": quality, "candle_buffer_size": len(one_minute),
            }
        duel = self._duel(contracts["CE"]["score"], contracts["PE"]["score"])
        self._calculation_count += 1
        calculated_at = self.clock().isoformat()
        status = self._pair_status(contracts)
        result = {
            "module": "OPTIONS STRUCTURE ENGINE", "schema_version": 1,
            "status": status, "runtime_status": "LIVE" if status == "LIVE" else status,
            "reason": self._state.get("reason"), "symbol": "NIFTY", "spot": spot,
            "anchor": self._state["pair"]["anchor"], "expiry": self._state["pair"]["expiry"],
            "pair_status": self._state["pair"]["status"],
            "market_context": deepcopy(self._state.get("market_context")),
            "rollover": {
                "state": self._state.get("rollover_state", "LOCKED"),
                "upper_boundary": self._state["pair"].get(
                    "selection_ceiling", self._state["pair"]["anchor"] + 100
                ),
                "lower_boundary": self._state["pair"].get(
                    "selection_floor", self._state["pair"]["anchor"]
                ),
                "next_up": self._state["pair"].get(
                    "selection_ceiling", self._state["pair"]["anchor"] + 100
                ),
                "next_down": self._state["pair"]["anchor"] - 100,
                "last_rollover": self._state.get("last_rollover_at"),
                "audit": deepcopy(self._state.get("rollover_audit") or []),
            },
            "contracts": contracts, "duel": duel,
            "option_flow": deepcopy(self._state.get("option_flow")),
            # This is the independently calculated Argus ATM±5 dominance
            # snapshot carried intact for publication.  OSE never derives or
            # changes its values; it only preserves the input's lineage.
            "participation_baseline": deepcopy(
                self._state.get("participation_baseline")
            ),
            "market_state": self._state.get("market_state", "UNKNOWN"),
            "recent_lifecycle_events": self._lifecycle_events(contracts),
            "data_quality": {
                "status": status, "source": "DHAN_OPTION_CHAIN_AND_DATA_API",
                "data_gap_count": sum(contract["quality"]["data_gap_count"] for contract in contracts.values()),
                "canonical_state": str(self.state_path), "render_contract": "BACKEND_AUTHORITATIVE",
            },
            "score_weights": deepcopy(self.SCORE_WEIGHTS),
            "calculated_at": calculated_at, "source_timestamp": observed_at.isoformat(),
            "source_age_seconds": round(
                max(0.0, (self.clock() - observed_at).total_seconds()), 3
            ),
            "executionInfluence": self.EXECUTION_INFLUENCE, "execution_influence": 0,
            "strategy_influence": self.STRATEGY_INFLUENCE, "advisory_only": True,
            "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
            "performance": {
                "calculation_ms": round((perf_counter() - started) * 1000, 3),
                "calculation_count": self._calculation_count,
                "rollover_duration_ms": self._state.get("last_rollover_duration_ms", 0.0),
            },
        }
        self._decorate_projection(result, record_transitions=True)
        return result

    def _classify_structure(
        self, raw: Mapping[str, Any], candles: list[Mapping[str, Any]], contract: Mapping[str, Any]
    ) -> dict[str, Any]:
        support = self._zone(raw.get("nearest_bullish_support"), contract)
        resistance = self._zone(raw.get("nearest_bearish_resistance"), contract)
        broken = [self._zone(zone, contract) for zone in raw.get("recently_broken") or []]
        supply_break = next((zone for zone in broken if zone and zone.get("role") == "RESISTANCE"), None)
        demand_break = next((zone for zone in broken if zone and zone.get("role") == "SUPPORT"), None)
        bullish_retest = self._retest(candles, supply_break, bullish=True)
        bearish_retest = self._retest(candles, demand_break, bullish=False)
        if supply_break and demand_break:
            state = "NEUTRAL"
            reason = "Conflicting demand and supply breaks"
        elif supply_break:
            state = "BULLISH"
            reason = "Supply break confirmed" + ("; retest held" if bullish_retest else "")
        elif demand_break:
            state = "BEARISH"
            reason = "Demand break confirmed" + ("; retest failed" if bearish_retest else "")
        else:
            state = "NEUTRAL"
            reason = "Premium remains between active zones"
        premium = float(candles[-1]["close"]) if candles else None
        evaluated_through = raw.get("evaluated_through")
        if candles:
            # All V2 intelligence modules identify a completed 5-minute
            # decision boundary by its exchange bucket-open timestamp.
            evaluated_through = candles[-1].get("timestamp")
        return {
            "timeframe": raw.get("timeframe"), "state": state, "reason": reason,
            "premium": premium, "demand": support, "supply": resistance,
            "recently_broken": [zone for zone in broken if zone],
            "supply_break": bool(supply_break), "demand_break": bool(demand_break),
            "bullish_retest": bullish_retest, "bearish_retest": bearish_retest,
            "evaluated_through": evaluated_through,
            "completed_bucket": bool(candles),
        }

    def _vob_wheel(self, structures: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        three, five = structures["3m"], structures["5m"]
        if five["state"] == "BULLISH" and five["bullish_retest"] and three["state"] == "BULLISH":
            state, strength = "ULTRA BULLISH", 100
        elif five["state"] == "BEARISH" and five["bearish_retest"] and three["state"] == "BEARISH":
            state, strength = "ULTRA BEARISH", 0
        elif "BULLISH" in {three["state"], five["state"]} and "BEARISH" not in {three["state"], five["state"]}:
            state, strength = "BULLISH", 75
        elif "BEARISH" in {three["state"], five["state"]} and "BULLISH" not in {three["state"], five["state"]}:
            state, strength = "BEARISH", 25
        else:
            state, strength = "NEUTRAL", 50
        return {
            "state": state, "strength": strength,
            "reasons": [three["reason"], five["reason"]],
            "evaluated_through": five.get("evaluated_through") or three.get("evaluated_through"),
        }

    def _trend(self, candles: list[Mapping[str, Any]]) -> dict[str, Any]:
        closes = [float(row["close"]) for row in candles]
        ema_21 = self.ema(closes, 21)
        ema = self.ema(closes, 50)
        atr = self.atr(candles, 10)
        supertrend_value, supertrend_direction = self.supertrend(candles, 10, 3.4)
        close = closes[-1] if closes else None
        if close is None or ema is None or supertrend_direction is None:
            state = "INSUFFICIENT HISTORY"
        elif close > ema and supertrend_direction == "POSITIVE":
            state = "ULTRA BULLISH"
        elif close < ema and supertrend_direction == "NEGATIVE":
            state = "ULTRA BEARISH"
        elif close > ema and supertrend_direction is None:
            state = "BULLISH"
        elif close < ema and supertrend_direction is None:
            state = "BEARISH"
        else:
            state = "NEUTRAL / MIXED"
        return {
            "state": state, "close": close, "ema_21": ema_21, "ema_50": ema,
            "strength": {"ULTRA BULLISH": 100, "BULLISH": 75, "NEUTRAL / MIXED": 50, "BEARISH": 25, "ULTRA BEARISH": 0}.get(state),
            "above_ema_21": None if close is None or ema_21 is None else close > ema_21,
            "above_ema_50": None if close is None or ema is None else close > ema,
            "supertrend_value": supertrend_value, "supertrend_direction": supertrend_direction,
            "atr": atr, "atr_period": 10, "multiplier": 3.4,
            "ema_21_zone": self._technical_zone(ema_21, atr),
            "ema_50_zone": self._technical_zone(ema, atr),
            "supertrend_zone": self._technical_zone(supertrend_value, atr),
            "evaluated_through": candles[-1].get("timestamp") if candles else None,
            "reason": self._trend_reason(close, ema, supertrend_direction),
        }

    def _decorate_projection(self, result: dict[str, Any], *, record_transitions: bool) -> None:
        """Attach canonical explanatory metadata without changing OSE calculations."""

        contracts = result.get("contracts")
        duel = result.get("duel")
        if not isinstance(contracts, dict) or not isinstance(duel, Mapping):
            return
        flow = result.get("option_flow")
        if isinstance(flow, dict) and not isinstance(flow.get("edge"), Mapping):
            flow["edge"] = directional_edge(
                flow.get("call") or {}, flow.get("put") or {}, fresh=flow.get("status") == "LIVE",
            )
        snapshots = deepcopy(self._state.get("contract_snapshots") or {})
        transitions = list(self._state.get("contract_transitions") or [])
        agreement: dict[str, Any] = {}
        for side in ("CE", "PE"):
            contract = contracts.get(side)
            if not isinstance(contract, dict):
                continue
            if not isinstance(contract.get("ssi"), Mapping):
                contract["ssi"] = build_ssi(int(contract["score"]), contract["score_breakdown"])
            contract["decision_window"] = decision_window(contract)
            flow_side = (flow or {}).get("call" if side == "CE" else "put") if isinstance(flow, Mapping) else None
            contract["engine_agreement"] = engine_agreement(
                contract, flow_side if isinstance(flow_side, Mapping) else None,
                str((flow or {}).get("status") or "UNAVAILABLE") if isinstance(flow, Mapping) else "UNAVAILABLE",
            )
            agreement[side] = deepcopy(contract["engine_agreement"])
            security_id = str((contract.get("contract") or {}).get("security_id") or "")
            previous = snapshots.get(side)
            if record_transitions:
                if isinstance(previous, Mapping) and str(previous.get("security_id") or "") == security_id:
                    event = detect_transition(side, previous, contract)
                    if event is not None:
                        transitions.append(event)
                snapshots[side] = transition_snapshot(contract)
            contract["latest_state_change"] = next(
                (deepcopy(event) for event in reversed(transitions) if event.get("side") == side and str(event.get("security_id") or "") == security_id),
                None,
            )
        if record_transitions:
            self._state["contract_snapshots"] = snapshots
            self._state["contract_transitions"] = transitions[-50:]
        result["engine_agreement"] = agreement
        result["structural_read"] = structural_read(contracts, duel, flow if isinstance(flow, Mapping) else None)
        digest_flow = deepcopy(flow) if isinstance(flow, Mapping) else flow
        if isinstance(digest_flow, dict):
            digest_flow.pop("age_seconds", None)
        result["canonical_digest"] = self._digest({
            "anchor": result.get("anchor"), "expiry": result.get("expiry"),
            "contracts": contracts, "duel": duel, "option_flow": digest_flow,
            "engine_agreement": agreement, "structural_read": result.get("structural_read"),
        })

    @staticmethod
    def ema(values: Sequence[float], period: int) -> float | None:
        if len(values) < period:
            return None
        value = sum(float(item) for item in values[:period]) / period
        multiplier = 2.0 / (period + 1.0)
        for item in values[period:]:
            value = (float(item) - value) * multiplier + value
        return round(value, 6)

    @staticmethod
    def atr(
        candles: Sequence[Mapping[str, Any]], period: int
    ) -> float | None:
        if len(candles) < period + 1:
            return None
        true_ranges: list[float] = []
        for index, row in enumerate(candles):
            high, low = float(row["high"]), float(row["low"])
            previous = (
                float(candles[index - 1]["close"])
                if index
                else float(row["close"])
            )
            true_ranges.append(
                max(high - low, abs(high - previous), abs(low - previous))
            )
        value = sum(true_ranges[1 : period + 1]) / period
        for item in true_ranges[period + 1 :]:
            value = ((value * (period - 1)) + item) / period
        return round(value, 6)

    @staticmethod
    def _technical_zone(
        level: float | None,
        atr: float | None,
        *,
        tick_size: float = 0.05,
    ) -> dict[str, float] | None:
        if level is None or atr is None:
            return None
        # Presentation width is volatility-derived and snapped to the option
        # tick. It is not an entry, risk, or execution threshold.
        half_width = max(tick_size * 2.0, atr * 0.08)
        half_width = math.ceil(half_width / tick_size) * tick_size
        return {
            "low": round(level - half_width, 2),
            "high": round(level + half_width, 2),
            "width": round(half_width * 2.0, 2),
        }

    @staticmethod
    def supertrend(
        candles: Sequence[Mapping[str, Any]], period: int, multiplier: float
    ) -> tuple[float | None, str | None]:
        if len(candles) < period + 1:
            return None, None
        trs: list[float] = []
        for index, row in enumerate(candles):
            high, low = float(row["high"]), float(row["low"])
            previous = float(candles[index - 1]["close"]) if index else float(row["close"])
            trs.append(max(high - low, abs(high - previous), abs(low - previous)))
        atr = sum(trs[1: period + 1]) / period
        upper = lower = super_value = None
        direction = 1
        for index in range(period, len(candles)):
            if index > period:
                atr = ((atr * (period - 1)) + trs[index]) / period
            row = candles[index]
            high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
            previous_close = float(candles[index - 1]["close"])
            basic_upper = (high + low) / 2.0 + multiplier * atr
            basic_lower = (high + low) / 2.0 - multiplier * atr
            upper = basic_upper if upper is None or basic_upper < upper or previous_close > upper else upper
            lower = basic_lower if lower is None or basic_lower > lower or previous_close < lower else lower
            if direction < 0 and close > upper:
                direction = 1
            elif direction > 0 and close < lower:
                direction = -1
            super_value = lower if direction > 0 else upper
        return (round(super_value, 6) if super_value is not None else None, "POSITIVE" if direction > 0 else "NEGATIVE")

    def _score(
        self, vob: Mapping[str, Any], trend: Mapping[str, Any], structures: Mapping[str, Mapping[str, Any]], quality: Mapping[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        state_values = {"ULTRA BULLISH": 1.0, "BULLISH": 0.6, "NEUTRAL": 0.0, "BEARISH": -0.6, "ULTRA BEARISH": -1.0}
        vob_value = state_values.get(str(vob.get("state")), 0.0)
        directions = [structures[tf]["state"] for tf in self.TIMEFRAMES]
        agreement = 1.0 if directions == ["BULLISH", "BULLISH"] else -1.0 if directions == ["BEARISH", "BEARISH"] else 0.0
        ema_value = 1.0 if trend.get("above_ema_50") is True else -1.0 if trend.get("above_ema_50") is False else 0.0
        st_value = 1.0 if trend.get("supertrend_direction") == "POSITIVE" else -1.0 if trend.get("supertrend_direction") == "NEGATIVE" else 0.0
        five = structures["5m"]
        event_value = 1.0 if five["bullish_retest"] else -1.0 if five["bearish_retest"] else 0.5 if five["supply_break"] else -0.5 if five["demand_break"] else 0.0
        freshness_value = 1.0 if quality["freshness"] == "FRESH" else 0.0 if quality["freshness"] == "AGING" else -1.0
        demand = five.get("demand")
        supply = five.get("supply")
        demand_distance = abs(float(demand.get("distance_points", 0))) if demand else None
        supply_distance = abs(float(supply.get("distance_points", 0))) if supply else None
        zone_value = 0.0
        if demand_distance is not None and supply_distance is not None and demand_distance + supply_distance:
            zone_value = (supply_distance - demand_distance) / (supply_distance + demand_distance)
        lifecycle_value = 1.0 if demand and demand.get("status") in {"ACTIVE", "TESTED"} else -1.0 if supply and supply.get("status") in {"ACTIVE", "TESTED"} else 0.0
        raw = {
            "vob_direction": vob_value, "timeframe_agreement": agreement,
            "ema_50": ema_value, "supertrend": st_value,
            "break_retest_quality": event_value, "freshness": freshness_value,
            "zone_distance": zone_value, "lifecycle_quality": lifecycle_value,
        }
        weighted = {name: round(raw[name] * self.SCORE_WEIGHTS[name], 4) for name in self.SCORE_WEIGHTS}
        total = sum(weighted.values())
        return int(round(max(0.0, min(100.0, 50.0 + total / 2.0)))), {
            name: {"weight": self.SCORE_WEIGHTS[name], "input": raw[name], "contribution": weighted[name]}
            for name in self.SCORE_WEIGHTS
        }

    @staticmethod
    def _composite_explanation(v_state: str, t_state: str, label: str) -> list[str]:
        def phrase(prefix: str, state: str) -> str:
            normalized = state.replace("ULTRA ", "strongly ").replace("NEUTRAL / MIXED", "mixed").lower()
            return f"{prefix} {normalized}"

        explanation = [phrase("VOB", v_state), phrase("Trend", t_state)]
        if label == "TRANSITION":
            explanation[1] = "Trend confirmation incomplete"
        return explanation

    @staticmethod
    def _composite(vob: Mapping[str, Any], trend: Mapping[str, Any]) -> dict[str, Any]:
        v_state, t_state = str(vob.get("state")), str(trend.get("state"))
        v_dir = "BULLISH" if "BULLISH" in v_state else "BEARISH" if "BEARISH" in v_state else "NEUTRAL"
        t_dir = "BULLISH" if "BULLISH" in t_state else "BEARISH" if "BEARISH" in t_state else "NEUTRAL"
        if v_dir == t_dir and v_dir != "NEUTRAL":
            full = v_state.startswith("ULTRA") and t_state.startswith("ULTRA")
            label = f"{'FULL' if full else 'STRONG'} {v_dir} ALIGNMENT"
        elif v_dir == "NEUTRAL" and t_dir != "NEUTRAL":
            label = f"PARTIAL {t_dir} ALIGNMENT"
        elif t_dir == "NEUTRAL" and v_dir != "NEUTRAL":
            label = "TRANSITION"
        elif v_dir != t_dir and "NEUTRAL" not in {v_dir, t_dir}:
            label = "CONFLICT"
        else:
            label = "LOW EDGE"
        explanation = OptionsStructureEngine._composite_explanation(v_state, t_state, label)
        return {
            "state": label,
            "vob_direction": v_dir,
            "trend_direction": t_dir,
            "explanation": explanation,
        }

    @staticmethod
    def _duel(ce: int, pe: int) -> dict[str, Any]:
        delta = ce - pe
        if abs(delta) <= 8:
            state = "BALANCED"
        elif delta >= 30:
            state = "CLEAR CALL ADVANTAGE"
        elif delta > 8:
            state = "MODERATE CALL ADVANTAGE"
        elif delta <= -30:
            state = "CLEAR PUT ADVANTAGE"
        else:
            state = "MODERATE PUT ADVANTAGE"
        return {"ce_score": ce, "pe_score": pe, "delta": delta, "state": state, "label": f"CALL {delta:+d}" if delta >= 0 else f"PUT {abs(delta):+d}"}

    def _quality(self, one: list[Mapping[str, Any]], five: list[Mapping[str, Any]], observed_at: datetime) -> dict[str, Any]:
        if not one:
            return {"status": "INSUFFICIENT HISTORY", "freshness": "STALE", "stale_age_seconds": None, "data_gap_count": 0}
        latest = self._aware(one[-1].get("candle_closed_at") or one[-1]["timestamp"])
        age = max(0.0, (observed_at - latest).total_seconds())
        timestamps = [self._aware(row["timestamp"]) for row in one if self._aware(row["timestamp"]).date() == observed_at.date()]
        gaps = sum(max(0, int((right - left).total_seconds() // 60) - 1) for left, right in zip(timestamps, timestamps[1:]))
        freshness = "FRESH" if age <= 120 else "AGING" if age <= 600 else "STALE"
        status = "LIVE" if len(five) >= 50 and freshness == "FRESH" and gaps == 0 else "DATA GAP" if gaps else "INSUFFICIENT HISTORY" if len(five) < 50 else "STALE"
        return {"status": status, "freshness": freshness, "stale_age_seconds": round(age, 3), "data_gap_count": gaps, "latest_completed_1m": one[-1].get("candle_closed_at")}

    @staticmethod
    def _pair_status(contracts: Mapping[str, Mapping[str, Any]]) -> str:
        statuses = {str(contract["quality"]["status"]) for contract in contracts.values()}
        if statuses == {"LIVE"}:
            return "LIVE"
        if "DATA GAP" in statuses:
            return "DATA GAP"
        if "STALE" in statuses:
            return "STALE"
        return "INSUFFICIENT HISTORY"

    @staticmethod
    def _trend_reason(close: float | None, ema: float | None, direction: str | None) -> str:
        if close is None or ema is None or direction is None:
            return "Completed 5M history insufficient"
        return f"Close {'above' if close > ema else 'below'} EMA 50; Supertrend {direction.lower()}"

    @staticmethod
    def _retest(candles: list[Mapping[str, Any]], zone: Mapping[str, Any] | None, *, bullish: bool) -> bool:
        if not zone or not zone.get("broken_at"):
            return False
        broken = OptionsStructureEngine._aware(zone["broken_at"])
        later = [row for row in candles if OptionsStructureEngine._aware(row["timestamp"]) > broken]
        if bullish:
            return any(float(row["low"]) <= float(zone["zone_high"]) and float(row["close"]) > float(zone["zone_high"]) for row in later)
        return any(float(row["high"]) >= float(zone["zone_low"]) and float(row["close"]) < float(zone["zone_low"]) for row in later)

    @staticmethod
    def _zone(value: Any, contract: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        return {**deepcopy(dict(value)), "symbol": contract["trading_symbol"], "security_id": contract["security_id"]}

    @staticmethod
    def _lifecycle_events(contracts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        events = []
        for side, contract in contracts.items():
            for timeframe, structure in contract["structures"].items():
                for zone in structure.get("recently_broken") or []:
                    events.append({"side": side, "timeframe": timeframe, "event": "BREAK", "role": zone.get("role"), "timestamp": zone.get("broken_at")})
                if structure.get("bullish_retest") or structure.get("bearish_retest"):
                    events.append({"side": side, "timeframe": timeframe, "event": "RETEST", "role": "SUPPLY" if structure.get("bullish_retest") else "DEMAND", "timestamp": structure.get("evaluated_through")})
        return sorted(events, key=lambda row: str(row.get("timestamp") or ""), reverse=True)[:12]

    def _latest_completed_spot_5m(self, observed_at: datetime) -> dict[str, Any] | None:
        payload = self._load_json(self.spot_candle_path)
        rows = payload.get("candles") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            return None
        buckets = self._incremental_resample(rows, 5, "NIFTY_SPOT")
        eligible = [row for row in buckets if self._aware(row["candle_closed_at"]) <= observed_at]
        return eligible[-1] if eligible else None

    def _update_live_projection(
        self, projection: dict[str, Any], spot: float, rows: list[Mapping[str, Any]], observed_at: datetime
    ) -> dict[str, Any]:
        result = deepcopy(projection)
        result["spot"] = spot
        result["source_timestamp"] = observed_at.isoformat()
        result["source_age_seconds"] = round(
            max(0.0, (self.clock() - observed_at).total_seconds()), 3
        )
        result["option_flow"] = deepcopy(self._state.get("option_flow"))
        result["participation_baseline"] = deepcopy(
            self._state.get("participation_baseline")
        )
        result["market_state"] = self._state.get("market_state", "UNKNOWN")
        for side in ("CE", "PE"):
            contract = result.get("contracts", {}).get(side, {}).get("contract")
            if not isinstance(contract, Mapping):
                continue
            row = next((item for item in rows if abs(float(item.get("strike", -1)) - float(contract["strike"])) < 0.001), None)
            leg = row.get(side.lower()) if isinstance(row, Mapping) else None
            if isinstance(leg, Mapping) and self._number(leg.get("ltp")) is not None:
                result["contracts"][side]["premium"] = float(leg["ltp"])
        status = self._pair_status(result.get("contracts") or {})
        result["status"] = status
        result["runtime_status"] = "LIVE" if status == "LIVE" else status
        result["reason"] = self._state.get("reason")
        result.setdefault("data_quality", {})["status"] = status
        self._decorate_projection(result, record_transitions=False)
        return result

    def _update_participation_baseline(
        self,
        payload: Mapping[str, Any],
        underlying: Mapping[str, Any],
        observed_at: datetime,
        source_status: str,
    ) -> None:
        """Carry the independent Buyers/Writers result with its real lineage.

        The OptionChainEngine remains the only calculator for this snapshot.
        This method only copies its already-computed values into the OSE
        publication object so Fast Lane can publish the source revision without
        waiting for the slower Strategy Lab dashboard refresh.
        """

        market_state = str(underlying.get("market_state") or "UNKNOWN").upper()
        dominance = payload.get("dominance")
        if source_status == "available" and isinstance(dominance, Mapping):
            values = deepcopy(dict(dominance))
            source_timestamp = observed_at.isoformat()
            revision_seed = json.dumps(
                {"source_timestamp": source_timestamp, "dominance": values},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            self._state["participation_baseline"] = {
                "status": "LIVE",
                "source": "ARGUS_OPTION_CHAIN_DOMINANCE",
                "source_timestamp": source_timestamp,
                "receive_timestamp": str(
                    underlying.get("receipt_timestamp")
                    or underlying.get("fetched_at")
                    or source_timestamp
                ),
                "timestamp_semantics": (
                    "ARGUS_OPTION_CHAIN_RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"
                ),
                "calculation_revision": hashlib.sha256(revision_seed).hexdigest()[:20],
                "values": values,
            }
            return

        prior = self._state.get("participation_baseline")
        if not isinstance(prior, Mapping):
            self._state["participation_baseline"] = {
                "status": "UNAVAILABLE",
                "source": "ARGUS_OPTION_CHAIN_DOMINANCE",
                "source_timestamp": None,
                "receive_timestamp": None,
                "timestamp_semantics": "SOURCE_UNAVAILABLE",
                "calculation_revision": None,
                "values": {},
            }
            return
        retained = deepcopy(dict(prior))
        retained["status"] = "MARKET_CLOSED" if market_state != "OPEN" else "STALE"
        self._state["participation_baseline"] = retained

    def _history_candle(self, row: Mapping[str, Any], contract: Mapping[str, Any], observed_at: datetime) -> dict[str, Any] | None:
        try:
            timestamp = DataEngine.exchange_datetime(row.get("time")).replace(second=0, microsecond=0)
            if timestamp + timedelta(minutes=1) > observed_at:
                return None
            return {
                "symbol": contract["trading_symbol"], "underlying": "NIFTY", "timeframe": "1m",
                "timestamp": timestamp.isoformat(), "candle_closed_at": (timestamp + timedelta(minutes=1)).isoformat(),
                "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]),
                "volume": float(row.get("volume") or 0.0), "source": "DHAN_DATA_API",
                "received_at": observed_at.isoformat(), "closed": True, "is_closed": True,
                "contract": contract["security_id"],
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _resample(cls, rows: Sequence[Mapping[str, Any]], minutes: int) -> list[dict[str, Any]]:
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            try:
                stamp = cls._aware(row.get("timestamp") or row.get("time"))
            except (TypeError, ValueError):
                continue
            session = stamp.replace(hour=9, minute=15, second=0, microsecond=0)
            offset = int((stamp - session).total_seconds() // 60)
            if offset < 0 or offset > 374:
                continue
            bucket = session + timedelta(minutes=(offset // minutes) * minutes)
            groups.setdefault(bucket.isoformat(), []).append(row)
        result = []
        for key in sorted(groups):
            group = sorted(groups[key], key=lambda row: cls._aware(row.get("timestamp") or row.get("time")))
            bucket = cls._aware(key)
            expected = [bucket + timedelta(minutes=index) for index in range(minutes)]
            actual = [cls._aware(row.get("timestamp") or row.get("time")).replace(second=0, microsecond=0) for row in group]
            if actual != expected:
                continue
            result.append({
                "symbol": group[0].get("symbol", "NIFTY"), "timeframe": f"{minutes}m",
                "timestamp": bucket.isoformat(), "candle_closed_at": (bucket + timedelta(minutes=minutes)).isoformat(),
                "open": float(group[0]["open"]), "high": max(float(row["high"]) for row in group),
                "low": min(float(row["low"]) for row in group), "close": float(group[-1]["close"]),
                "volume": sum(float(row.get("volume") or 0.0) for row in group), "closed": True, "is_closed": True,
            })
        return result

    @staticmethod
    def _hash_candles(candles: Sequence[Mapping[str, Any]]) -> str:
        parts = []
        for r in candles:
            parts.append(f"{r.get('timestamp') or r.get('time')}|{r.get('open')}|{r.get('high')}|{r.get('low')}|{r.get('close')}|{r.get('volume', 0.0)}")
        return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()

    def _incremental_resample(self, rows: Sequence[Mapping[str, Any]], minutes: int, security_id: str) -> list[dict[str, Any]]:
        session_groups: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            ts_str = str(row.get("timestamp") or row.get("time") or "")
            if len(ts_str) >= 10:
                session_date = ts_str[:10]
                session_groups.setdefault(session_date, []).append(row)

        final_result = []
        for session_date in sorted(session_groups):
            group = sorted(session_groups[session_date], key=lambda r: str(r.get("timestamp") or r.get("time") or ""))
            current_raw_count = len(group)
            current_first_ts = group[0].get("timestamp") or group[0].get("time")
            current_last_ts = group[-1].get("timestamp") or group[-1].get("time")
            current_fingerprint = self._hash_candles(group)
            cache_key = (security_id, minutes, session_date)
            cached = self._resample_cache.get(cache_key)

            is_pure_append = False
            if cached and current_raw_count >= cached.get("raw_count", 0):
                prefix_fingerprint = self._hash_candles(group[:cached.get("raw_count", 0)])
                if prefix_fingerprint == cached.get("fingerprint"):
                    is_pure_append = True

            if cached and current_raw_count == cached.get("raw_count") and current_fingerprint == cached.get("fingerprint"):
                final_result.extend(cached["resampled"])
                continue

            if is_pure_append and cached and cached.get("resampled"):
                last_bucket_ts = cached["resampled"][-1]["timestamp"]
                merged = [b for b in cached["resampled"] if b["timestamp"] < last_bucket_ts]
                overlap_candles = [r for r in group if self._aware(r.get("timestamp") or r.get("time")) >= self._aware(last_bucket_ts)]
                new_buckets = self._resample(overlap_candles, minutes)
                merged.extend(new_buckets)
                self._resample_cache[cache_key] = {
                    "raw_count": current_raw_count,
                    "first_timestamp": current_first_ts,
                    "last_timestamp": current_last_ts,
                    "fingerprint": current_fingerprint,
                    "resampled": merged
                }
                final_result.extend(merged)
            else:
                merged = self._resample(group, minutes)
                self._resample_cache[cache_key] = {
                    "raw_count": current_raw_count,
                    "first_timestamp": current_first_ts,
                    "last_timestamp": current_last_ts,
                    "fingerprint": current_fingerprint,
                    "resampled": merged
                }
                final_result.extend(merged)
        return final_result

    def _read_candles(self, contract: Mapping[str, Any]) -> list[dict[str, Any]]:
        payload = self._load_json(self._candle_path(contract))
        return list(payload.get("candles") or []) if isinstance(payload, Mapping) else []

    def _write_candles(self, contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
        self._atomic_json(self._candle_path(contract), {
            "schema_version": 1, "security_id": str(contract["security_id"]),
            "contract": deepcopy(dict(contract)), "candles": self._dedupe(rows)[-self.MAX_CANDLES:],
        })

    def _candle_path(self, contract: Mapping[str, Any]) -> Path:
        return self.candle_root / f"{contract['security_id']}_1m.json"

    @staticmethod
    def _dedupe(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        unique = {str(row.get("timestamp") or row.get("time")): deepcopy(dict(row)) for row in rows if row.get("timestamp") or row.get("time")}
        return [unique[key] for key in sorted(unique)]

    def _persist_state(self) -> None:
        state = deepcopy(self._state)
        state["schema_version"] = 1
        self._atomic_json(self.state_path, state)

    def _write_projection(self) -> None:
        """Serialize self._projection to disk, skipping the write when the
        serialized bytes are identical to the previously committed payload.

        perf(serialization): at ~2.2 ingests/sec the projection is updated
        every cycle (spot, timestamps, age_seconds change) so the skip
        rarely fires during live trading — but it eliminates the redundant
        encode during unavailable / stale / error cycles where the payload
        is structurally identical across many consecutive calls.
        The main benefit is moving the serialization from *two separate*
        json.dump paths (one inside _atomic_json, one inside projection())
        to a single encode whose result is reused for both the disk write
        and the byte-size counter exposed via the API.
        """
        raw = json.dumps(self._projection, separators=(",", ":"), default=str).encode("utf-8")
        self._last_projection_serialized_len = len(raw)
        if raw == self._last_projection_bytes:
            # Payload unchanged — skip fsync + atomic rename.
            return
        self._last_projection_bytes = raw
        path = self.projection_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, separators=(",", ":"), default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _aware(value: Any) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _trading_symbol(expiry: str, strike: int, side: str) -> str:
        stamp = datetime.fromisoformat(expiry).strftime("%d %b").upper()
        return f"NIFTY {stamp} {strike} {side}"

    @staticmethod
    def _digest(value: Mapping[str, Any]) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"schema_version": 1, "pair": None, "rollover_state": "LOCKED", "rollover_audit": [], "runtime_status": "WARMING UP", "reason": None}

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "module": "OPTIONS STRUCTURE ENGINE", "schema_version": 1,
            "status": "UNAVAILABLE", "runtime_status": "UNAVAILABLE", "reason": reason,
            "contracts": {}, "duel": None, "executionInfluence": self.EXECUTION_INFLUENCE,
            "execution_influence": 0, "strategy_influence": 0, "advisory_only": True,
            "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
            "performance": {"calculation_ms": 0.0, "api_serialization_ms": 0.0},
        }

    def _publish_unavailable(self, reason: str) -> None:
        with self._lock:
            prior = deepcopy(self._projection)
            if prior.get("contracts"):
                prior.update({"status": "STALE", "runtime_status": "STALE", "reason": reason})
                self._projection = prior
            else:
                self._projection = self._unavailable(reason)
