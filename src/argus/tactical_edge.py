"""Canonical, advisory-only ARGUS Tactical Edge projection."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from math import isfinite
from statistics import median
from time import perf_counter
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.argus.tactical_config import (
    ATM_BREADTH_STRIKES,
    BREADTH_CONFIRMATION_SCORE,
    DATA_QUALITY_WEIGHTS,
    ENTRY_STATES,
    EXTREME_BREAK_BREADTH_CONFIRMATIONS,
    EXTREME_BREAK_PRESSURE_DELTA,
    GAMMA_UNAVAILABLE_REASON,
    HIGH_CONVICTION_EVIDENCE_QUALITY,
    PRESSURE_BALANCED_DELTA,
    PRESSURE_DIRECTIONAL_DELTA,
    PRESSURE_WEIGHTS,
    REGIME_BALANCED_LIMIT,
    REGIME_CONFIRMATION_SECONDS,
    REGIME_CONFIRMATION_SNAPSHOTS,
    REGIME_EXIT_LIMIT,
    REGIME_WEIGHTS,
    SCHEMA_VERSION,
    SETUP_CLASSES,
)
from src.argus.tactical_store import ArgusTacticalStore
from src.argus.prime import ArgusPrimeProjection, PRIME_FORMULA_VERSION
from src.argus.session_recorder import ArgusSessionRecorder


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        result = float(value)
        return int(result) if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _median(values: Sequence[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return median(present) if present else None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_IST = ZoneInfo("Asia/Kolkata")


def _timestamp(value: Any) -> datetime | None:
    """Return an aware timestamp without inventing a source time."""

    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _session_date(value: Any) -> str | None:
    parsed = _timestamp(value)
    return parsed.astimezone(_IST).date().isoformat() if parsed else None


class ArgusTacticalEdgeEngine:
    """Compose one immutable ARGUS/OSE input into a read-only tactical projection."""

    @staticmethod
    def _classify_pressure_imbalance(value: float) -> tuple[str, str]:
        magnitude = abs(value)
        if magnitude <= PRESSURE_BALANCED_DELTA:
            return "BALANCED", "NO_CLEAN_EDGE"
        direction = "CALL" if value < 0 else "PUT"
        strength = "STRONG_" if magnitude >= PRESSURE_DIRECTIONAL_DELTA else ""
        return direction, f"{strength}{direction}_PRESSURE"

    EXECUTION_INFLUENCE = "ZERO"

    def __init__(
        self,
        store: ArgusTacticalStore,
        clock=None,
        recorder: ArgusSessionRecorder | None = None,
        contract_technicals_provider=None,
    ):
        self.store = store
        self.clock = clock or _iso_now
        self.recorder = recorder
        self.contract_technicals_provider = contract_technicals_provider

    def evaluate(
        self,
        argus_projection: Mapping[str, Any],
        ose_projection: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        started = perf_counter()
        argus = dict(argus_projection) if isinstance(argus_projection, Mapping) else {}
        ose = dict(ose_projection) if isinstance(ose_projection, Mapping) else {}
        if not self._is_fresh(argus):
            return self._stale_or_unavailable(argus, started)

        source = argus.get("data") if isinstance(argus.get("data"), Mapping) else {}
        underlying = (
            source.get("underlying")
            if isinstance(source.get("underlying"), Mapping)
            else {}
        )
        rows = self._seven_strikes(
            source.get("atm_window") or [], _number(underlying.get("atm_strike"))
        )
        if not rows:
            return self._unavailable(
                "ARGUS_SEVEN_STRIKE_WINDOW_UNAVAILABLE", argus, started
            )

        calculation_id = self._calculation_id(argus, ose)
        latest = self.store.latest()
        if (
            isinstance(latest, Mapping)
            and latest.get("calculation_id") == calculation_id
            and latest.get("status") == "LIVE"
        ):
            return dict(latest)

        history = self.store.history()
        previous = history[-1] if history else {}
        pressure = self._pressure(rows, underlying, previous)
        contract_selection = self._contract_selection(
            underlying, ose, rows, pressure.get("direction")
        )
        contract_technicals: dict[str, Any] = {}
        if callable(self.contract_technicals_provider):
            for side in ("CE", "PE"):
                candidate = next(
                    (
                        item
                        for item in contract_selection.get("all_candidate_ranks") or []
                        if isinstance(item, Mapping)
                        and item.get("side") == side
                        and item.get("status") == "CANDIDATE"
                    ),
                    None,
                )
                if not isinstance(candidate, Mapping):
                    contract_technicals[side] = {
                        "status": "UNAVAILABLE",
                        "reason": f"{side}_LIQUID_CONTRACT_UNAVAILABLE",
                    }
                    continue
                try:
                    contract_technicals[side] = self.contract_technicals_provider(
                        candidate,
                        underlying.get("fetched_at"),
                    )
                except Exception as exc:
                    contract_technicals[side] = {
                        "status": "UNAVAILABLE",
                        "reason": (
                            "SELECTED_CONTRACT_TECHNICALS_UNAVAILABLE:"
                            f"{type(exc).__name__}"
                        ),
                    }
        previous_oi = self._previous_oi(source, rows, previous)
        breadth = self._breadth(pressure)
        iv = self._iv_intelligence(rows, contract_selection, previous, underlying)
        premium = self._premium_attribution(
            rows, underlying, contract_selection
        )
        persistence = self._persistence(
            pressure["direction"], history, underlying.get("fetched_at"), pressure.get("chain_snapshot_id")
        )
        continuation = self._continuation_reversal(
            pressure,
            breadth,
            persistence,
            iv,
            ose,
            contract_selection,
            history,
            underlying.get("fetched_at"),
        )
        entry = self._entry_lifecycle(
            pressure, breadth, continuation, ose, contract_selection, previous
        )
        quality = self._quality_dimensions(
            pressure, breadth, iv, continuation, contract_selection, ose
        )
        setups = self._setups(
            quality, pressure, breadth, entry, continuation,
            contract_selection, ose
        )
        melt_risk = self._melt_risk(iv, premium, pressure)
        decision = self._decision(
            pressure, entry, setups, quality, continuation,
            premium, contract_selection, breadth, persistence, iv, previous_oi, underlying, "LIVE"
        )
        quality = decision["quality"]
        why = self._why(
            pressure, breadth, previous_oi, persistence, iv, premium,
            continuation, entry, contract_selection, quality
        )
        calculated_at = self.clock()
        atm_strike = _number(underlying.get("atm_strike"))
        universe_version = (
            f"{underlying.get('expiry')}_{int(atm_strike)}_V1"
            if atm_strike is not None
            else f"{underlying.get('expiry')}_UNAVAILABLE_V1"
        )
        computed_snapshot_id = hashlib.md5(
            f"{underlying.get('fetched_at')}_{pressure.get('chain_snapshot_id')}_{calculation_id}".encode()
        ).hexdigest()[:12]
        prime_source = dict(source)
        prime_source["tactical_edge"] = {"decision": dict(decision)}
        argus_prime = ArgusPrimeProjection.compose(
            source=prime_source,
            rows=rows,
            pressure=pressure,
            previous_oi=previous_oi,
            breadth=breadth,
            persistence=persistence,
            iv=iv,
            premium=premium,
            continuation=continuation,
            entry=entry,
            selection=contract_selection,
            quality=quality,
            ose=ose,
            snapshot_id=computed_snapshot_id,
            history=history,
            previous_projection=latest,
            contract_technicals=contract_technicals,
        )
        result = {
            "module": "ARGUS TACTICAL EDGE",
            "schema_version": SCHEMA_VERSION,
            "calculation_id": calculation_id,
            "status": "LIVE",
            "freshness": "FRESH",
            "source_event_time": underlying.get("source_event_time"),
            "receipt_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "snapshot_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "timestamp_semantics": underlying.get("timestamp_semantics"),
            # Provider event time is deliberately nullable.  Dhan's current
            # option-chain payload does not always carry an event timestamp;
            # a local receipt must never be relabelled as one.
            "source_timestamp": underlying.get("source_event_time"),
            "source_age_seconds": _number(
                (argus.get("cache") or {}).get("age_seconds")
            ),
            "receipt_age_seconds": _number(
                (argus.get("cache") or {}).get("age_seconds")
            ),
            "freshness_basis": (
                "PROVIDER_EVENT_TIME"
                if underlying.get("source_event_time") is not None
                else "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"
            ),
            "calculated_at": calculated_at,
            "symbol": underlying.get("symbol"),
            "expiry": underlying.get("expiry"),
            "spot": underlying.get("ltp"),
            "spot_source_timestamp": underlying.get("source_event_time"),
            "option_chain_source_timestamp": underlying.get("source_event_time"),
            "option_chain_receipt_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "pressure_computed_at": pressure.get("pressure_computed_at"),
            "chain_snapshot_id": pressure.get("chain_snapshot_id"),
            "computed_snapshot_id": computed_snapshot_id,
            "universe_version": universe_version,
            "pressure_recomputed": pressure.get("pressure_recomputed", False),
            "chain_row_count": pressure.get("chain_row_count", 0),
            "pressure_status": pressure.get("pressure_status", "PRESSURE UNAVAILABLE"),
            "contract_selection": contract_selection,
            "pressure": pressure,
            "previous_oi": previous_oi,
            "breadth": breadth,
            "persistence": persistence,
            "iv_intelligence": iv,
            "gamma": self._gamma_unavailable(),
            "premium_attribution": premium,
            "continuation_reversal": continuation,
            "entry_lifecycle": entry,
            "setups": setups,
            "decision": decision,
            "quality": quality,
            "melt_risk": melt_risk,
            "why": why,
            "argus_prime": argus_prime,
            "input_lineage": {
                "argus_snapshot": (
                    underlying.get("receipt_timestamp")
                    or underlying.get("fetched_at")
                ),
                "source_event_time": underlying.get("source_event_time"),
                "receipt_timestamp": (
                    underlying.get("receipt_timestamp")
                    or underlying.get("fetched_at")
                ),
                "timestamp_semantics": underlying.get("timestamp_semantics"),
                "ose_calculation_id": ose.get("canonical_digest"),
                "ose_calculated_at": ose.get("calculated_at"),
                "ose_status": ose.get("status") or "UNAVAILABLE",
                "immutable_input": True,
            },
            "advisory_only": True,
            "execution_influence": self.EXECUTION_INFLUENCE,
            "strategy_influence": "ZERO",
            "order_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "performance": {
                "calculation_ms": round((perf_counter() - started) * 1000, 3),
                "cache_hit": False,
            },
        }
        record = {
            "calculation_id": calculation_id,
            # `observation_timestamp` is a local receipt/observation marker
            # used only for ordering persisted snapshots.  It is not source
            # event time and remains explicitly named as such.
            "source_timestamp": underlying.get("source_event_time"),
            "observation_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "receipt_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "source_event_time": underlying.get("source_event_time"),
            "symbol": underlying.get("symbol"),
            "expiry": underlying.get("expiry"),
            "strike_scope": sorted(
                {
                    strike
                    for row in rows
                    if (strike := _number(row.get("strike"))) is not None
                }
            ),
            "session_date": _session_date(
                underlying.get("source_event_time")
                or underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "calculated_at": calculated_at,
            "direction": pressure["direction"],
            "pressure_delta": pressure["delta"],
            "evidence_quality": quality["data_quality"]["score"],
            "data_quality": quality["data_quality"]["score"],
            "evidence_agreement": quality["evidence_agreement"]["score"],
            "signal_stability": quality["signal_stability"]["score"],
            "actionability": quality["actionability"]["score"],
            "raw_regime_state": continuation["raw_state"],
            "raw_compass": continuation["raw_compass"],
            "confirmed_regime_state": continuation["confirmed_state"],
            "confirmed_compass": continuation["compass"],
            "pending_regime_state": continuation["pending_state"],
            "pending_regime_count": continuation["pending_count"],
            "pending_regime_since": continuation["pending_since"],
            "spot": underlying.get("ltp"),
            "call_wall": previous_oi["call_wall"],
            "put_wall": previous_oi["put_wall"],
            "aggregate_intraday_ce_change": previous_oi[
                "aggregate_intraday_ce_change"
            ],
            "aggregate_intraday_pe_change": previous_oi[
                "aggregate_intraday_pe_change"
            ],
            "ce_iv_median": iv["ce_median"],
            "pe_iv_median": iv["pe_median"],
            "entry_state": entry["state"],
            "chain_snapshot_id": pressure.get("chain_snapshot_id"),
            "prime_raw_direction": argus_prime.get("raw_direction"),
            "prime_direction": argus_prime.get("direction"),
            "prime_action": argus_prime.get("action"),
            "prime_score": argus_prime.get("argus_prime_score"),
            "prime_raw_score": argus_prime.get("raw_score"),
            "oi_pcr": (argus_prime.get("live_pcr") or {}).get("oi_pcr"),
            "pcr_observation": (
                {
                    "timestamp": (argus_prime.get("live_pcr") or {}).get(
                        "source_timestamp"
                    ),
                    "expiry": (argus_prime.get("live_pcr") or {}).get(
                        "expiry"
                    ),
                    "underlying": (argus_prime.get("live_pcr") or {}).get(
                        "underlying"
                    ),
                    "total_put_oi": (
                        argus_prime.get("live_pcr") or {}
                    ).get("total_put_oi"),
                    "total_call_oi": (
                        argus_prime.get("live_pcr") or {}
                    ).get("total_call_oi"),
                    "pcr": (argus_prime.get("live_pcr") or {}).get(
                        "oi_pcr"
                    ),
                    "snapshot_id": (
                        argus_prime.get("live_pcr") or {}
                    ).get("snapshot_id"),
                }
                if (argus_prime.get("live_pcr") or {}).get("status")
                == "AVAILABLE"
                and (argus_prime.get("live_pcr") or {}).get("snapshot_id")
                else None
            ),
            "best_stack_strike": (
                argus_prime.get("best_strike_stack") or {}
            ).get("strike"),
            "best_stack_direction": (
                argus_prime.get("best_strike_stack") or {}
            ).get("direction"),
            "prime_smoothed_score": argus_prime.get("smoothed_score"),
            "prime_display_score": argus_prime.get("display_score"),
            "prime_outcome_engines": {
                key: {
                    "state": value.get("state"),
                    "raw_score": value.get("raw_score"),
                    "smoothed_score": value.get("smoothed_score"),
                    "display_score": value.get("display_score"),
                }
                for key, value in (
                    argus_prime.get("outcome_engines") or {}
                ).items()
                if isinstance(value, Mapping)
            },
            "prime_strike_state": [
                {
                    "strike": item.get("strike"),
                    "CE": {
                        "oi": (item.get("CE") or {}).get("oi"),
                        "oi_velocity": (item.get("CE") or {}).get(
                            "oi_velocity"
                        ),
                    },
                    "PE": {
                        "oi": (item.get("PE") or {}).get("oi"),
                        "oi_velocity": (item.get("PE") or {}).get(
                            "oi_velocity"
                        ),
                    },
                }
                for item in argus_prime.get("strike_spine") or []
                if isinstance(item, Mapping)
            ],
            "prime_entry_style": argus_prime.get("entry_style"),
            "prime_contract_security_id": (
                (argus_prime.get("recommended_contract") or {}).get(
                    "security_id"
                )
            ),
            "prime_pending_direction": (
                (argus_prime.get("stability") or {}).get(
                    "pending_direction"
                )
            ),
            "prime_pending_count": (
                (argus_prime.get("stability") or {}).get("pending_count")
            ),
            "prime_pending_since": (
                (argus_prime.get("stability") or {}).get("pending_since")
            ),
        }
        self.store.publish(calculation_id, result, record)
        if self.recorder is not None:
            self.recorder.append(
                projection=result,
                rows=rows,
                source=source,
            )
        return result

    @staticmethod
    def _is_fresh(argus: Mapping[str, Any]) -> bool:
        data = argus.get("data") if isinstance(argus.get("data"), Mapping) else {}
        underlying = (
            data.get("underlying")
            if isinstance(data.get("underlying"), Mapping)
            else {}
        )
        return (
            str(argus.get("status")).lower() == "available"
            and str(argus.get("freshness")).lower() in {"fresh", "cached"}
            and str(underlying.get("market_state")).upper() == "OPEN"
        )

    def _stale_or_unavailable(
        self, argus: Mapping[str, Any], started: float
    ) -> dict[str, Any]:
        latest = self.store.latest()
        if not isinstance(latest, Mapping):
            return self._unavailable(
                "NO_AUTHORITATIVE_TACTICAL_SNAPSHOT", argus, started
            )
        result = deepcopy(dict(latest))
        result.update(
            {
                "status": "STALE",
                "freshness": "STALE",
                "stale_reason": "ARGUS_SOURCE_NOT_FRESH",
                "calculated_at": self.clock(),
            }
        )
        data = argus.get("data") if isinstance(argus.get("data"), Mapping) else {}
        underlying = data.get("underlying") if isinstance(data.get("underlying"), Mapping) else {}
        m_state = str(underlying.get("market_state") or "OPEN").upper()
        market_closed = m_state in {
            "CLOSED", "POST_MARKET", "PRE_MARKET", "WEEKEND", "HOLIDAY",
        }
        retained_prime = (
            result.get("argus_prime")
            if isinstance(result.get("argus_prime"), Mapping)
            else {}
        )
        retained_truth = (
            retained_prime.get("data_truth")
            if isinstance(retained_prime.get("data_truth"), Mapping)
            else {}
        )
        # Keep provider event-time lineage null when the provider did not
        # supply it.  Older projections may have overloaded
        # `source_timestamp` with a local receipt, so it is intentionally not
        # consulted here.
        authoritative_source_event_time = (
            result.get("source_event_time")
            or retained_truth.get("source_event_time")
        )
        authoritative_receipt_timestamp = (
            result.get("receipt_timestamp")
            or retained_truth.get("receipt_timestamp")
            or retained_truth.get("receive_timestamp")
            or result.get("observation_timestamp")
        )
        # Observation time is safe for retained PCR/history ordering only.
        # It does not become a provider source event or source-age basis.
        authoritative_observation_timestamp = (
            authoritative_source_event_time or authoritative_receipt_timestamp
        )
        authoritative_freshness_timestamp = authoritative_source_event_time
        source_age = None
        receipt_age = None
        now = _timestamp(self.clock())
        event_at = _timestamp(authoritative_source_event_time)
        receipt_at = _timestamp(authoritative_receipt_timestamp)
        if now is not None and event_at is not None:
            source_age = max(0.0, (now - event_at).total_seconds())
        if now is not None and receipt_at is not None:
            receipt_age = max(0.0, (now - receipt_at).total_seconds())
        stale_reason = (
            "MARKET_CLOSED_LAST_GOOD"
            if market_closed
            else "LIVE_FEED_STALE_ACTION_LOCKED"
        )

        decision = dict(result.get("decision") or {})
        decision.update(
            {
                "state": "WAIT",
                "gate": "UNAVAILABLE",
                "current_action": "Last authoritative context retained; current tactical action unavailable.",
                "action_enabled": False,
                "data_quality": 0.0,
                "signal_stability": 0.0,
                "actionability": 0.0,
                "next_trigger": "Wait for a fresh authoritative ARGUS snapshot",
                "market_state": "MARKET_CLOSED" if market_closed else "STALE",
                "display_state": "LAST_GOOD_SNAPSHOT" if market_closed else "ACTION_LOCKED",
                "why_line": (
                    "Market closed; the last coherent production snapshot is retained."
                    if market_closed
                    else "Live feed is stale; the last coherent state is frozen and action is locked."
                ),
                "entry_zone_low": None,
                "entry_zone_high": None,
                "timing_guidance": "UNAVAILABLE",
                "hold_guidance": "No open position to hold",
                "risk_reward": "UNAVAILABLE",
                "readiness_score": 0,
                "readiness_label": "NO EDGE",
                "evidence_count": 0,
                "evidence_total": 0,
                "invalidation_level": "UNAVAILABLE",
            }
        )
        quality = deepcopy(dict(result.get("quality") or {}))
        for key in ("data_quality", "signal_stability", "actionability"):
            value = deepcopy(dict(quality.get(key) or {}))
            value.update({"score": 0.0, "status": "STALE"})
            quality[key] = value
        agreement = deepcopy(dict(quality.get("evidence_agreement") or {}))
        agreement["status"] = "LAST_AUTHORITATIVE"
        quality["evidence_agreement"] = agreement
        decision["quality"] = quality
        result["decision"] = decision
        result["quality"] = quality
        continuation = deepcopy(dict(result.get("continuation_reversal") or {}))
        continuation["status"] = "STALE"
        continuation["transition_reason"] = "LAST_AUTHORITATIVE_STATE_FROZEN"
        result["continuation_reversal"] = continuation
        prime = deepcopy(dict(result.get("argus_prime") or {}))
        prime.update(
            {
                "status": "STALE",
                "freshness": "STALE",
                "display_state": "LAST_GOOD" if market_closed else "STALE",
                "market_state": m_state,
                "stale_reason": stale_reason,
                "source_age_seconds": (
                    round(source_age, 1) if source_age is not None else None
                ),
                "receipt_age_seconds": (
                    round(receipt_age, 1) if receipt_age is not None else None
                ),
                "action": "HOLD",
                "hero_state": (
                    "MARKET CLOSED — LAST GOOD SNAPSHOT"
                    if market_closed
                    else "LIVE FEED STALE — ACTION LOCKED"
                ),
                "hard_blocks": sorted(
                    set(list(prime.get("hard_blocks") or []) + [stale_reason])
                ),
            }
        )
        component_scores = (
            prime.get("component_scores")
            if isinstance(prime.get("component_scores"), Mapping)
            else {}
        )
        score_weights = (
            prime.get("score_weights")
            if isinstance(prime.get("score_weights"), Mapping)
            else {}
        )
        existing_breakdown = prime.get("score_breakdown")
        breakdown_requires_upgrade = (
            not isinstance(existing_breakdown, Mapping)
            or any(
                not isinstance(item, Mapping) or "raw_score" not in item
                for item in existing_breakdown.values()
            )
        )
        if breakdown_requires_upgrade:
            prime["score_breakdown"] = {
                name: {
                    "raw_score": _number(component_scores.get(name)),
                    "weight": _number(weight),
                    "contribution": (
                        round(
                            float(component_scores[name]) * float(weight),
                            4,
                        )
                        if _number(component_scores.get(name)) is not None
                        and _number(weight) is not None
                        else None
                    ),
                    "availability": (
                        "LAST_GOOD"
                        if _number(component_scores.get(name)) is not None
                        else "UNAVAILABLE"
                    ),
                }
                for name, weight in sorted(score_weights.items())
            }
        evidence_coverage = prime.get("evidence_coverage")
        if isinstance(evidence_coverage, Mapping):
            coverage_value = _number(evidence_coverage.get("percentage"))
        else:
            coverage_value = _number(evidence_coverage)
        prime["score_formula_version"] = PRIME_FORMULA_VERSION
        prime["data_truth"] = {
            "source": "DHAN_V2_OPTION_CHAIN_PLUS_FULL_MARKET_QUOTE",
            "source_event_time": authoritative_source_event_time,
            "receipt_timestamp": authoritative_receipt_timestamp,
            "evaluation_timestamp": retained_truth.get(
                "evaluation_timestamp"
            ),
            "snapshot_timestamp": retained_truth.get("snapshot_timestamp"),
            "freshness_timestamp": authoritative_freshness_timestamp,
            "freshness_basis": (
                "PROVIDER_EVENT_TIME"
                if authoritative_source_event_time is not None
                else "SOURCE_EVENT_TIME_UNAVAILABLE"
            ),
            "timestamp_semantics": retained_truth.get(
                "timestamp_semantics"
            ),
            "source_timestamp": authoritative_source_event_time,
            "receive_timestamp": authoritative_receipt_timestamp,
            "age_seconds": (
                round(source_age, 1) if source_age is not None else None
            ),
            "receipt_age_seconds": (
                round(receipt_age, 1) if receipt_age is not None else None
            ),
            "freshness_threshold_seconds": 20.0,
            "snapshot_id": (
                result.get("calculation_id")
                or result.get("latest_calculation_id")
            ),
            "expiry": underlying.get("expiry"),
            "security_id": None,
            "formula_version": PRIME_FORMULA_VERSION,
            "evidence_coverage": coverage_value,
            "state": "LAST_GOOD" if market_closed else "STALE",
        }
        rows = self._seven_strikes(
            data.get("atm_window") or [],
            _number(underlying.get("atm_strike")),
        )
        history = self.store.history()
        live_pcr = ArgusPrimeProjection._live_pcr(
            rows,
            history,
            authoritative_observation_timestamp,
            data.get("totals") if isinstance(data.get("totals"), Mapping) else {},
            expiry=underlying.get("expiry"),
            underlying=underlying.get("symbol") or "NIFTY",
            snapshot_id=(
                result.get("calculation_id")
                or result.get("latest_calculation_id")
            ),
        )
        try:
            pcr_source_age = max(
                0.0,
                (
                    datetime.fromisoformat(str(self.clock()))
                    - datetime.fromisoformat(
                        str(authoritative_observation_timestamp)
                    )
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            pcr_source_age = None
        live_pcr["freshness"] = "STALE"
        live_pcr["source_age_seconds"] = (
            round(pcr_source_age, 1)
            if pcr_source_age is not None
            else None
        )
        live_pcr["current_state"] = (
            "LAST_GOOD" if live_pcr.get("oi_pcr") is not None else "UNAVAILABLE"
        )
        retained_futures = ArgusPrimeProjection._futures_confirmation(
            data.get("futures"),
            "HOLD",
            option_source_timestamp=authoritative_observation_timestamp,
            allow_last_good=market_closed,
        )
        if retained_futures.get("status") == "AVAILABLE":
            retained_futures.update(
                {
                    "status": "LAST_GOOD" if market_closed else "AVAILABLE",
                    "display_state": (
                        "LAST_GOOD" if market_closed else "LIVE"
                    ),
                    "as_of": retained_futures.get("source_timestamp"),
                    "reason": (
                        "MARKET_CLOSED_LAST_COHERENT_FUTURES_CONFIRMATION"
                        if market_closed
                        else "LAST_COHERENT_FUTURES_CONFIRMATION"
                    ),
                }
            )
        raw_rows = {
            _number(item.get("strike")): item
            for item in rows
            if isinstance(item, Mapping)
            and _number(item.get("strike")) is not None
        }
        depth_by_security = (
            data.get("option_market_depth")
            if isinstance(data.get("option_market_depth"), Mapping)
            else {}
        )
        retained_spine = deepcopy(list(prime.get("strike_spine") or []))
        for item in retained_spine:
            if not isinstance(item, dict):
                continue
            raw_row = raw_rows.get(_number(item.get("strike")))
            if not isinstance(raw_row, Mapping):
                continue
            for raw_side, projected_side in (("ce", "CE"), ("pe", "PE")):
                raw_leg = raw_row.get(raw_side)
                projected_leg = item.get(projected_side)
                if not isinstance(raw_leg, Mapping) or not isinstance(
                    projected_leg, dict
                ):
                    continue
                retained_depth = projected_leg.get("depth")
                depth = (
                    retained_depth
                    if isinstance(retained_depth, Mapping)
                    else depth_by_security.get(str(raw_leg.get("security_id")))
                )
                depth = depth if isinstance(depth, Mapping) else {}
                flow = ArgusPrimeProjection._probable_flow(
                    raw_leg,
                    depth,
                    source_timestamp=authoritative_observation_timestamp,
                    allow_last_good=market_closed,
                )
                projected_leg.update(
                    {
                        "probable_flow": flow.get("label"),
                        "flow_state": flow.get("state"),
                        "flow_confidence": flow.get("confidence"),
                        "flow_reasons": flow.get("reasons"),
                        "flow_evidence": flow.get("evidence"),
                        "flow_evidence_coverage": flow.get(
                            "evidence_coverage"
                        ),
                    }
                )
        best_stack = ArgusPrimeProjection._best_strike_stack(
            direction=str(prime.get("direction") or "HOLD"),
            recommended=(
                prime.get("recommended_contract")
                if isinstance(prime.get("recommended_contract"), Mapping)
                else None
            ),
            strike_spine=retained_spine,
            history=history,
            underlying=underlying,
            futures=retained_futures,
            entry=(
                result.get("entry_lifecycle")
                if isinstance(result.get("entry_lifecycle"), Mapping)
                else {}
            ),
        )
        prime["futures_confirmation"] = retained_futures
        prime["strike_spine"] = retained_spine
        retained_gamma = deepcopy(dict(prime.get("gamma_regime") or {}))
        if retained_gamma.get("state") == "DAMPING":
            retained_gamma.update(
                {
                    "state": "MOVE_SUPPRESSED",
                    "technical_state": "DAMPING",
                    "trader_explanation": (
                        "Gamma conditions are likely slowing or pinning the move."
                    ),
                }
            )
        prime["gamma_regime"] = retained_gamma
        reversal_semantics = ArgusPrimeProjection._reversal_semantics(
            score=_number(prime.get("reversal_score")) or 0.0,
            market_state=m_state,
            futures=retained_futures,
            pressure_price=(
                prime.get("pressure_to_price")
                if isinstance(prime.get("pressure_to_price"), Mapping)
                else {}
            ),
            continuation=continuation,
            source_timestamp=authoritative_observation_timestamp,
        )
        prime["reversal_semantics"] = reversal_semantics
        outcomes = deepcopy(dict(prime.get("outcome_engines") or {}))
        reversal_outcome = deepcopy(dict(outcomes.get("reversal") or {}))
        reversal_outcome.update(
            {"state": reversal_semantics["label"], "semantic": reversal_semantics}
        )
        outcomes["reversal"] = reversal_outcome
        prime["outcome_engines"] = outcomes
        prime["live_pcr"] = live_pcr
        prime["best_strike_stack"] = best_stack
        prime["selected_contract_technicals"] = {
            "status": "UNAVAILABLE",
            "reason": stale_reason,
            "pullback_state": "WAITING_FOR_FRESH_COMPLETED_5M",
        }
        prime["tactical_summary"] = ArgusPrimeProjection._tactical_summary(
            direction=str(prime.get("direction") or "HOLD"),
            smart_flow=(
                prime.get("smart_money_flow")
                if isinstance(prime.get("smart_money_flow"), Mapping)
                else {}
            ),
            wall=(
                prime.get("wall_outcome")
                if isinstance(prime.get("wall_outcome"), Mapping)
                else {}
            ),
            blast=(
                prime.get("expiry_gamma_blast")
                if isinstance(prime.get("expiry_gamma_blast"), Mapping)
                else {}
            ),
            reversal_score=_number(prime.get("reversal_score")) or 0.0,
            live_pcr=live_pcr,
            best_strike_stack=best_stack,
        )
        prime["chain_summary"] = ArgusPrimeProjection._chain_summary(
            direction=str(prime.get("direction") or "HOLD"),
            previous_oi=(
                result.get("previous_oi")
                if isinstance(result.get("previous_oi"), Mapping)
                else {}
            ),
            best_strike_stack=best_stack,
            live_pcr=live_pcr,
        )
        full_evidence = deepcopy(dict(prime.get("full_evidence") or {}))
        displayed_lineage = deepcopy(
            dict(full_evidence.get("displayed_value_lineage") or {})
        )
        displayed_lineage.update(
            {
                "futures_confirmation": retained_futures,
                "oi_pcr": live_pcr,
                "strongest_structural_strike": best_stack,
                "reversal": reversal_semantics,
            }
        )
        full_evidence["displayed_value_lineage"] = displayed_lineage
        prime["full_evidence"] = full_evidence
        action_card = deepcopy(dict(prime.get("action_card") or {}))
        action_card.update(
            {
                "status": "LAST GOOD" if market_closed else "DATA STALE",
                "reason": (
                    "Market closed; actionable levels remain locked."
                    if market_closed
                    else "Current action locked until a fresh authoritative ARGUS snapshot."
                ),
            }
        )
        prime["action_card"] = action_card
        result["argus_prime"] = prime
        for setup in (result.get("setups") or {}).values():
            setup["status"] = "UNAVAILABLE"
            setup["reason"] = "ARGUS_SOURCE_NOT_FRESH"
        result["performance"] = {
            "calculation_ms": round((perf_counter() - started) * 1000, 3)
        }
        calculation_id = str(
            result.get("calculation_id")
            or result.get("latest_calculation_id")
            or "LAST_GOOD_SNAPSHOT"
        )
        evidence_record = next(
            (
                item
                for item in reversed(history)
                if str(item.get("calculation_id")) == calculation_id
            ),
            {
                "calculation_id": calculation_id,
                "source_timestamp": result.get("source_timestamp"),
                "status": "LAST_GOOD",
            },
        )
        self.store.publish(calculation_id, result, evidence_record)
        return result

    def _unavailable(
        self, reason: str, argus: Mapping[str, Any], started: float
    ) -> dict[str, Any]:
        data = argus.get("data") if isinstance(argus.get("data"), Mapping) else {}
        underlying = (
            data.get("underlying")
            if isinstance(data.get("underlying"), Mapping)
            else {}
        )
        return {
            "module": "ARGUS TACTICAL EDGE",
            "schema_version": SCHEMA_VERSION,
            "calculation_id": None,
            "status": "UNAVAILABLE",
            "freshness": "UNAVAILABLE",
            "unavailable_reason": reason,
            "source_timestamp": underlying.get("source_event_time"),
            "source_event_time": underlying.get("source_event_time"),
            "receipt_timestamp": (
                underlying.get("receipt_timestamp")
                or underlying.get("fetched_at")
            ),
            "timestamp_semantics": underlying.get("timestamp_semantics"),
            "calculated_at": self.clock(),
            "symbol": underlying.get("symbol"),
            "contract_selection": {
                "status": "UNAVAILABLE", "reason": "OSE_PAIR_UNAVAILABLE"
            },
            "gamma": self._gamma_unavailable(),
            "argus_prime": ArgusPrimeProjection.unavailable(
                reason,
                source_timestamp=underlying.get("source_event_time"),
                snapshot_id=None,
            ),
            "setups": {
                name: {
                    "class": name,
                    "status": "UNAVAILABLE",
                    "reason": reason if name != "GAMMA_BLAST" else GAMMA_UNAVAILABLE_REASON,
                }
                for name in SETUP_CLASSES
            },
            "decision": {
                "gate": "UNAVAILABLE",
                "current_action": "Tactical context unavailable.",
                "action_enabled": False,
                "evidence_quality": 0.0,
                "entry_zone_low": None,
                "entry_zone_high": None,
                "timing_guidance": "UNAVAILABLE",
                "hold_guidance": "No open position to hold",
                "risk_reward": "UNAVAILABLE",
                "readiness_score": 0,
                "readiness_label": "NO EDGE",
                "evidence_count": 0,
                "evidence_total": 0,
                "invalidation_level": "UNAVAILABLE",
            },
            "why": {
                "observed": [],
                "derived": [],
                "approximated": [],
                "unavailable": [reason, GAMMA_UNAVAILABLE_REASON],
                "reasons": [reason],
            },
            "advisory_only": True,
            "execution_influence": "ZERO",
            "strategy_influence": "ZERO",
            "order_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "performance": {
                "calculation_ms": round((perf_counter() - started) * 1000, 3)
            },
        }

    @staticmethod
    def _compute_stretch(
        ltp: float | None,
        candles: list[dict[str, Any]] | None = None,
        underlying_move: float = 0.0,
        delta: float = 0.5,
        theta: float = 0.0,
        vega: float = 0.0,
        iv_change: float = 0.0,
    ) -> tuple[float | None, str]:
        if not candles or len(candles) < 14:
            return None, "UNAVAILABLE"
        else:
            # 14-period lookback true historical stretch math
            closes = [float(c.get("close", ltp or 0)) for c in candles[-14:]]
            highs = [float(c.get("high", ltp or 0)) for c in candles[-14:]]
            lows = [float(c.get("low", ltp or 0)) for c in candles[-14:]]
            vwaps = [float(c.get("vwap", ltp or 0)) for c in candles[-14:]]
            
            vwap_14 = vwaps[-1] if vwaps else 120.0
            sma_14 = sum(closes) / 14.0
            ema_9 = sum(closes[-9:]) / 9.0 if len(closes) >= 9 else sma_14
            
            true_ranges = [max(h - l, abs(h - c_prev), abs(l - c_prev)) for h, l, c_prev in zip(highs[1:], lows[1:], closes[:-1])]
            atr_14 = (sum(true_ranges) / len(true_ranges)) if true_ranges else 15.0
            if atr_14 == 0: atr_14 = 1.0
            
            variance = sum((c - sma_14) ** 2 for c in closes) / 14.0
            std_dev_14 = variance ** 0.5
            if std_dev_14 == 0: std_dev_14 = 1.0
            
            min_14, max_14 = min(lows), max(highs)
            range_diff = max_14 - min_14
            if range_diff == 0: range_diff = 1.0
            
            vwap_dev = round(((ltp - vwap_14) / vwap_14) * 100, 2) if ltp and vwap_14 else 0.0
            ema_dist = round(abs(ltp - ema_9) / atr_14, 2) if ltp else 0.0
            rolling_z = round((ltp - sma_14) / std_dev_14, 2) if ltp else 0.0
            range_pct = round(((ltp - min_14) / range_diff) * 100, 2) if ltp else 0.0
            
            # Greek attribution sanity
            delta_expected_move = delta * underlying_move
            residual_move = (closes[-1] - closes[-2]) - delta_expected_move - theta - (vega * iv_change) if len(closes) >= 2 else 0.0
            
        stretch_score = round(min(100.0, max(0.0, abs(vwap_dev) * 2.0 + ema_dist * 10.0 + rolling_z * 15.0)), 2)
        stretch_state = "EXTREME" if stretch_score >= 80 else "STRETCHED" if stretch_score >= 60 else "ELEVATED" if stretch_score >= 35 else "NORMAL"
        return stretch_score, stretch_state

    @staticmethod
    def _seven_strikes(
        rows: Sequence[Mapping[str, Any]], atm: float | None
    ) -> list[dict[str, Any]]:
        ordered = sorted(
            (deepcopy(dict(row)) for row in rows if _number(row.get("strike")) is not None),
            key=lambda row: float(row["strike"]),
        )
        if len(ordered) == 0:
            return []
            
        atm_strike = atm if atm is not None else float(ordered[len(ordered) // 2]["strike"])
        
        # Determine the strike interval
        strikes = [float(r["strike"]) for r in ordered]
        intervals = [strikes[i+1] - strikes[i] for i in range(len(strikes)-1)]
        if intervals:
            from collections import Counter
            interval = Counter(intervals).most_common(1)[0][0]
        else:
            interval = 50.0
            
        target_strikes = [atm_strike + i * interval for i in range(-3, 4)]
        
        result = []
        for ts in target_strikes:
            match = next((r for r in ordered if abs(float(r["strike"]) - ts) < 0.1), None)
            if match:
                result.append(match)
            else:
                result.append({"strike": ts, "ce": None, "pe": None, "missing": True})
        return result

    @staticmethod
    def _calculation_id(
        argus: Mapping[str, Any], ose: Mapping[str, Any]
    ) -> str:
        data = argus.get("data") if isinstance(argus.get("data"), Mapping) else {}
        underlying = data.get("underlying") if isinstance(data.get("underlying"), Mapping) else {}
        payload = {
            "symbol": underlying.get("symbol"),
            "expiry": underlying.get("expiry"),
            "fetched_at": underlying.get("fetched_at"),
            "market_fetched_at": (
                (data.get("argus_market_snapshot") or {}).get("fetched_at")
                if isinstance(data.get("argus_market_snapshot"), Mapping)
                else None
            ),
            "ose_digest": ose.get("canonical_digest"),
            "ose_calculated_at": ose.get("calculated_at"),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _contract_selection(
        underlying: Mapping[str, Any],
        ose: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]] = (),
        directional_bias: Any = None,
    ) -> dict[str, Any]:
        contracts = ose.get("contracts") if isinstance(ose.get("contracts"), Mapping) else {}
        selected: dict[str, Any] = {}
        for side in ("CE", "PE"):
            value = contracts.get(side) if isinstance(contracts.get(side), Mapping) else {}
            contract = value.get("contract") if isinstance(value.get("contract"), Mapping) else {}
            selected[side] = {
                "security_id": contract.get("security_id"),
                "strike": contract.get("strike"),
                "expiry": contract.get("expiry"),
                "trading_symbol": contract.get("trading_symbol"),
                "premium": value.get("premium"),
            }
        expiry = underlying.get("expiry")
        symbol = underlying.get("symbol")
        valid = all(
            selected[side]["security_id"] is not None
            and selected[side]["expiry"] == expiry
            for side in ("CE", "PE")
        ) and ose.get("symbol") == symbol
        reason = (
            "EXISTING_OSE_SAME_EXPIRY_100_POINT_ITM_PAIR"
            if valid
            else "ARGUS_OSE_CONTEXT_MISMATCH"
            if ose.get("symbol") != symbol
            else "OSE_PAIR_IDENTITY_UNAVAILABLE"
        )

        candidate_ranks: list[dict[str, Any]] = []
        atm_strike = _number(underlying.get("atm_strike"))
        
        # Select exact 7 strikes around ATM (ATM-3, ATM-2, ATM-1, ATM, ATM+1, ATM+2, ATM+3)
        sorted_strikes = sorted(list(set(_number(r.get("strike")) for r in rows if _number(r.get("strike")) is not None)))
        atm_idx = (
            min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - atm_strike))
            if sorted_strikes and atm_strike is not None
            else 0
        )
        start_idx = max(0, min(atm_idx - 3, len(sorted_strikes) - 7))
        target_strikes = set(sorted_strikes[start_idx : start_idx + 7]) if len(sorted_strikes) >= 7 else set(sorted_strikes)
        seven_strike_rows = [r for r in rows if _number(r.get("strike")) in target_strikes]

        final_bias = str(directional_bias or "BALANCED").upper()

        for r in sorted(seven_strike_rows, key=lambda x: _number(x.get("strike")) or 0.0):
            strike = _number(r.get("strike"))
            if strike is None:
                continue
            for side in ("CE", "PE"):
                leg = r.get(side.lower()) if isinstance(r.get(side.lower()), dict) else {}
                if not leg or r.get("missing"):
                    candidate_ranks.append({
                        "strike": strike,
                        "side": side,
                        "expiry": expiry,
                        "option_type": side,
                        "trading_symbol": f"{symbol}{str(expiry).replace('-', '')}{int(strike)}{side}",
                        "security_id": None,
                        "contract_score": 0.0,
                        "score_breakdown": {},
                        "rank": 0,
                        "delta": None,
                        "gamma_value": None,
                        "gamma_source": "UNAVAILABLE",
                        "gamma_available": False,
                        "gamma_risk": 0.0,
                        "gamma_reason": "Native Greeks offline",
                        "iv": None,
                        "volume": 0,
                        "oi": 0,
                        "bid": 0.0,
                        "ask": 0.0,
                        "spread_abs": 0.0,
                        "spread_pct": 0.0,
                        "distance_atm": abs(strike - atm_strike),
                        "premium": 0.0,
                        "stretch_score": 0.0,
                        "stretch_state": "NORMAL",
                        "activity": "NEUTRAL",
                        "status": "UNAVAILABLE",
                        "rejection_reason": "SOURCE_LEG_MISSING",
                    })
                    continue

                bid = _number(leg.get("top_bid_price"))
                ask = _number(leg.get("top_ask_price"))
                ltp = _number(leg.get("ltp")) or _number(leg.get("last_price")) or 0.0
                volume = _integer(leg.get("volume")) or 0
                oi = _integer(leg.get("oi")) or 0
                # Delta and IV are provider evidence.  They may be absent on
                # a real chain response and must not be replaced by neutral
                # defaults that improve contract rank.
                delta = _number(leg.get("delta"))
                raw_gamma = _number(leg.get("gamma"))
                iv = _number(leg.get("iv"))
                sec_id = leg.get("security_id")

                # Authoritative Gamma Consistency
                if raw_gamma is not None and raw_gamma > 0:
                    gamma_val = raw_gamma
                    gamma_src = "DHAN"
                    gamma_avail = True
                    gamma_risk = round(gamma_val * 10000.0, 2)
                    gamma_reason = f"Dhan native gamma ({gamma_val})"
                else:
                    gamma_val = None
                    gamma_src = "UNAVAILABLE"
                    gamma_avail = False
                    gamma_risk = 0.0
                    gamma_reason = "Native Greeks offline; gamma risk uncalculated"

                spread_abs = round(ask - bid, 2) if (bid is not None and ask is not None) else 0.0
                mid = (bid + ask) / 2.0 if (bid and ask and (bid + ask) > 0) else (ltp if ltp > 0 else 1.0)
                spread_pct = round((spread_abs / mid) * 100, 2)

                # Premium Stretch Engine Calculation
                stretch_score, stretch_state = ArgusTacticalEdgeEngine._compute_stretch(ltp)

                rejection = None
                if bid is None or bid <= 0:
                    rejection = "ZERO_OR_INVALID_BID_PRICE"
                elif ask is None or ask <= 0:
                    rejection = "ZERO_OR_INVALID_ASK_PRICE"
                elif bid > ask:
                    rejection = "CROSSED_MARKET"
                elif spread_pct > 3.0:
                    rejection = f"EXCESSIVE_SPREAD_{spread_pct}%"
                elif volume == 0 and oi == 0:
                    rejection = "ZERO_LIQUIDITY_VOLUME_AND_OI"
                elif stretch_state in ("STRETCHED", "EXTREME"):
                    rejection = f"PREMIUM_STRETCH_{stretch_state}"

                dist_atm = abs(strike - atm_strike) if atm_strike is not None else None
                dist_score = (
                    max(0.0, 100.0 - dist_atm * 0.2)
                    if dist_atm is not None
                    else 0.0
                )
                liq_score = max(0.0, 100.0 - spread_pct * 20.0)
                delta_target = 0.50 if side == "CE" else -0.50
                delta_score = (
                    max(0.0, 100.0 - abs(delta - delta_target) * 150.0)
                    if delta is not None
                    else None
                )
                
                # Directional Alignment (Bias Aware)
                if final_bias == "CALL":
                    c_dir = 20.0 if side == "CE" else 0.0
                elif final_bias == "PUT":
                    c_dir = 20.0 if side == "PE" else 0.0
                else:
                    c_dir = 5.0  # BALANCED

                c_liq = round(0.20 * liq_score, 2)
                c_delta = round(0.20 * delta_score, 2) if delta_score is not None else 0.0
                c_spread = round(0.15 * max(0.0, 100.0 - spread_abs * 10.0), 2)
                c_act = round(0.10 * (100.0 if "BUYING" in str(leg.get("activity")) else 50.0), 2)
                c_prem = round(0.05 * min(100.0, ltp), 2)
                c_stretch_pen = round(-0.20 if stretch_state == "EXTREME" else -0.10 if stretch_state == "STRETCHED" else -0.05 if stretch_state == "ELEVATED" else 0.0, 2)
                c_iv_risk = round(-0.03 * (iv * 2.0), 2) if iv is not None else 0.0
                c_gamma_risk = round(-0.02 * gamma_risk if gamma_avail else 0.0, 2)

                term_contributions = [c_dir, c_liq, c_delta, c_spread, c_act, c_prem, c_stretch_pen, c_iv_risk, c_gamma_risk]
                contract_score = round(max(0.0, sum(term_contributions)), 2)

                score_breakdown = {
                    "directional_alignment": {"raw": final_bias, "normalized": c_dir / 0.20, "weight": 0.20, "contribution": c_dir, "availability": "AVAILABLE"},
                    "liquidity": {"raw": volume, "normalized": liq_score, "weight": 0.20, "contribution": c_liq},
                    "delta_suitability": {"raw": delta, "normalized": delta_score, "weight": 0.20, "contribution": c_delta if delta_score is not None else None, "availability": "AVAILABLE" if delta_score is not None else "UNAVAILABLE", "reason": None if delta_score is not None else "NATIVE_DELTA_UNAVAILABLE_EXCLUDED"},
                    "spread_quality": {"raw": spread_pct, "normalized": max(0.0, 100.0 - spread_abs * 10.0), "weight": 0.15, "contribution": c_spread},
                    "strike_activity": {"raw": leg.get("activity") or "NEUTRAL", "normalized": 100.0 if "BUYING" in str(leg.get("activity")) else 50.0, "weight": 0.10, "contribution": c_act},
                    "premium_quality": {"raw": ltp, "normalized": min(100.0, ltp), "weight": 0.05, "contribution": c_prem},
                    "stretch_penalty": {"raw": stretch_score, "normalized": stretch_score, "weight": -0.05, "contribution": c_stretch_pen},
                    "iv_risk": {"raw": iv, "normalized": iv * 2.0 if iv is not None else None, "weight": -0.03, "contribution": c_iv_risk if iv is not None else None, "availability": "AVAILABLE" if iv is not None else "UNAVAILABLE", "reason": None if iv is not None else "NATIVE_IV_UNAVAILABLE_EXCLUDED"},
                    "gamma_risk": {"raw": gamma_val, "normalized": gamma_risk, "weight": -0.02, "contribution": c_gamma_risk},
                }

                if stretch_state in ("STRETCHED", "EXTREME"):
                    status = "BLOCKED"
                elif rejection:
                    status = "REJECTED"
                else:
                    status = "CANDIDATE"

                candidate_ranks.append({
                    "strike": strike,
                    "side": side,
                    "expiry": expiry,
                    "option_type": side,
                    "trading_symbol": f"{symbol}{str(expiry).replace('-', '')}{int(strike)}{side}",
                    "security_id": sec_id,
                    "contract_score": contract_score,
                    "score_breakdown": score_breakdown,
                    "rank": 0,
                    "delta": delta,
                    "gamma_value": gamma_val,
                    "gamma_source": gamma_src,
                    "gamma_available": gamma_avail,
                    "gamma_risk": gamma_risk,
                    "gamma_reason": gamma_reason,
                    "iv": iv,
                    "unavailable_evidence": [
                        name for name, value in (("NATIVE_DELTA", delta), ("NATIVE_IV", iv))
                        if value is None
                    ],
                    "ranking_policy": "MISSING_GREEKS_EXCLUDED_NO_RENORMALIZATION",
                    "volume": volume,
                    "oi": oi,
                    "bid": bid,
                    "ask": ask,
                    "spread_abs": spread_abs,
                    "spread_pct": spread_pct,
                    "distance_atm": dist_atm,
                    "premium": ltp,
                    "stretch_score": stretch_score,
                    "stretch_state": stretch_state,
                    "activity": leg.get("activity") or "NEUTRAL",
                    "status": status,
                    "rejection_reason": rejection,
                })

        candidate_ranks.sort(key=lambda x: (x["status"] != "CANDIDATE", -x["contract_score"]))
        for idx, item in enumerate(candidate_ranks, 1):
            item["rank"] = idx

        required_side = "CE" if final_bias == "CALL" else "PE" if final_bias == "PUT" else None
        winner = next(
            (
                candidate
                for candidate in candidate_ranks
                if candidate["status"] == "CANDIDATE"
                and (required_side is None or candidate["side"] == required_side)
            ),
            None,
        )
        runners_up = [c for c in candidate_ranks if c != winner][:2]

        why_winner = (
            f"TOP-RANKED CANDIDATE — BIAS NOT ACTIVATED: {ArgusTacticalEdgeEngine._candidate_reason(winner)}"
            if winner and final_bias == "BALANCED"
            else ArgusTacticalEdgeEngine._candidate_reason(winner)
            if winner else "No valid candidate contract passed execution filters."
        )
        why_runners_up_lost = []
        for c in runners_up:
            reason_text = c['rejection_reason'] or f"Lower score ({c['contract_score']}) vs winner"
            why_runners_up_lost.append(f"Rank {c['rank']} ({c['trading_symbol']}): {reason_text}")

        return {
            "status": "AVAILABLE" if valid else "UNAVAILABLE",
            "reason": reason,
            "anchor": ose.get("anchor"),
            "expiry": ose.get("expiry"),
            "CE": selected["CE"],
            "PE": selected["PE"],
            "unique_strike_count": len(target_strikes),
            "CE_count": sum(1 for c in candidate_ranks if c["side"] == "CE"),
            "PE_count": sum(1 for c in candidate_ranks if c["side"] == "PE"),
            "all_candidate_ranks": candidate_ranks,
            "directional_bias": final_bias,
            "directive_contract": (
                deepcopy(winner) if winner is not None and required_side else None
            ),
            "rejected_alternatives": [
                {
                    "security_id": candidate.get("security_id"),
                    "strike": candidate.get("strike"),
                    "side": candidate.get("side"),
                    "reason": candidate.get("rejection_reason")
                    or "LOWER_CANONICAL_RANK",
                }
                for candidate in candidate_ranks
                if candidate is not winner
            ][:6],
            "why_winner": why_winner,
            "why_runners_up_lost": why_runners_up_lost,
            "lineage": "OPTIONS_STRUCTURE_ENGINE",
        }

    @staticmethod
    def _candidate_reason(candidate: Mapping[str, Any]) -> str:
        """Explain an authorized candidate without claiming missing Greeks."""

        delta = candidate.get("delta")
        delta_text = (
            f"native delta ({delta})"
            if delta is not None
            else "native delta unavailable (excluded from rank)"
        )
        iv_text = (
            "native IV available"
            if candidate.get("iv") is not None
            else "native IV unavailable (excluded from rank)"
        )
        return (
            f"Selected {candidate['trading_symbol']} (Rank 1, Score "
            f"{candidate['contract_score']}) with tight spread "
            f"({candidate['spread_pct']}%), {delta_text}, {iv_text}, and ATM "
            f"distance {candidate['distance_atm']} pts."
        )

    def _pressure(
        self,
        rows: Sequence[Mapping[str, Any]],
        underlying: Mapping[str, Any],
        previous: Mapping[str, Any],
    ) -> dict[str, Any]:
        chain_row_count = len(rows)
        fetched_at = underlying.get("fetched_at")
        chain_snapshot_id = self._compute_chain_snapshot_id(rows, fetched_at)

        if chain_row_count == 0 or not chain_snapshot_id:
            return {
                "status": "PRESSURE_UNAVAILABLE",
                "direction": "BALANCED",
                "state": "NO_CLEAN_EDGE",
                "call_score": None,
                "put_score": None,
                "delta": None,
                "acceleration": None,
                "evidence_quality": 0.0,
                "strikes": [],
                "chain_row_count": 0,
                "chain_snapshot_id": None,
                "pressure_recomputed": False,
                "pressure_status": "PRESSURE UNAVAILABLE",
            }

        prev_chain_id = previous.get("chain_snapshot_id") if isinstance(previous, Mapping) else None
        pressure_recomputed = (chain_snapshot_id != prev_chain_id) if prev_chain_id else True
        pressure_status = "RECOMPUTED FROM NEW CHAIN" if pressure_recomputed else "UNCHANGED SOURCE SNAPSHOT"

        maxima: dict[str, float] = {}
        for field in ("oi", "day_change_oi", "intraday_change_oi", "volume", "intraday_price_change"):
            values = [
                abs(value)
                for row in rows
                for side in ("ce", "pe")
                if isinstance(row.get(side), Mapping)
                if (value := _number(row[side].get(field))) is not None
            ]
            maxima[field] = max(values) if values else 0.0
        previous_spot = _number(previous.get("spot"))
        current_spot = _number(underlying.get("ltp"))
        spot_change = (
            current_spot - previous_spot
            if current_spot is not None and previous_spot is not None
            else None
        )
        strike_results: list[dict[str, Any]] = []
        side_scores: dict[str, list[float]] = {"CE": [], "PE": []}
        observed = 0
        expected = 0
        for row in rows:
            item = {"strike": row.get("strike")}
            for side in ("CE", "PE"):
                leg = row.get(side.lower()) if isinstance(row.get(side.lower()), Mapping) else {}
                values = {
                    "open_interest": self._normalized(leg.get("oi"), maxima["oi"]),
                    "previous_oi_change": self._signed_normalized(
                        leg.get("day_change_oi"), maxima["day_change_oi"]
                    ),
                    "intraday_oi_change": self._signed_normalized(
                        leg.get("intraday_change_oi"), maxima["intraday_change_oi"]
                    ),
                    "premium_change": self._signed_normalized(
                        leg.get("intraday_price_change"), maxima["intraday_price_change"]
                    ),
                    "volume": self._normalized(leg.get("volume"), maxima["volume"]),
                    "bid_ask": self._book_score(leg),
                    "iv_quality": 1.0 if _number(leg.get("iv")) is not None else None,
                    "spot_confirmation": (
                        None
                        if spot_change is None
                        else 1.0
                        if (side == "CE" and spot_change > 0)
                        or (side == "PE" and spot_change < 0)
                        else 0.0
                    ),
                }
                expected += len(values)
                observed += sum(value is not None for value in values.values())
                contribution = 0.0
                available_weight = 0.0
                normalized_components: dict[str, Any] = {}
                activity = str(leg.get("activity") or "INSUFFICIENT_DATA")
                for name, value in values.items():
                    weight = PRESSURE_WEIGHTS[name]
                    normalized_components[name] = value
                    if value is None:
                        continue
                    available_weight += weight
                    signed = value
                    if name not in {"previous_oi_change", "intraday_oi_change", "premium_change"}:
                        signed = (value * 2.0) - 1.0
                    contribution += signed * weight
                raw_score = 50.0
                if available_weight:
                    raw_score += 50.0 * (contribution / available_weight)
                score = round(_clamp(raw_score), 2)
                side_scores[side].append(score)
                item[side] = {
                    "score": score,
                    "activity": activity,
                    "components": normalized_components,
                    "security_id": leg.get("security_id"),
                }
            strike_results.append(item)
        call_pressure = round(sum(side_scores["CE"]) / len(side_scores["CE"]), 2) if side_scores["CE"] else 50.0
        put_pressure = round(sum(side_scores["PE"]) / len(side_scores["PE"]), 2) if side_scores["PE"] else 50.0
        
        pressure_imbalance = round(put_pressure - call_pressure, 2)

        # For backwards compatibility during transition, preserve old aliases
        net_edge = pressure_imbalance
        delta = pressure_imbalance
        
        denom = round(call_pressure + put_pressure, 2)
        if denom > 0:
            call_norm = round((call_pressure / denom) * 100.0, 2)
            put_norm = round(100.00 - call_norm, 2)
        else:
            call_norm, put_norm = 50.00, 50.00
            denom = 100.00

        direction, state = self._classify_pressure_imbalance(
            pressure_imbalance
        )

        prev_delta = None
        prev_ts = None
        if isinstance(previous, dict):
            if isinstance(previous.get("pressure"), dict):
                prev_delta = _number(previous["pressure"].get("pressure_imbalance"))
                if prev_delta is None:
                    prev_delta = _number(previous["pressure"].get("delta"))
            if prev_delta is None:
                prev_delta = _number(previous.get("pressure_delta"))
                
            # Tactical history stores provider event time separately from the
            # local observation/receipt time.  Velocity needs elapsed time
            # even when the option-chain provider does not supply an event
            # timestamp, so use the observation clock for the calculation.
            prev_ts = (
                previous.get("observation_timestamp")
                or previous.get("receipt_timestamp")
                or previous.get("source_timestamp")
            )
            if prev_ts is None and isinstance(previous.get("pressure"), dict):
                prev_ts = previous["pressure"].get("option_chain_source_timestamp")
        curr_ts = underlying.get("fetched_at")
        acceleration = None
        if prev_delta is not None and prev_ts and curr_ts:
            try:
                from datetime import datetime
                dt_sec = (
                    datetime.fromisoformat(str(curr_ts))
                    - datetime.fromisoformat(str(prev_ts))
                ).total_seconds()
                if dt_sec > 0:
                    dt_min = dt_sec / 60.0
                    raw_rate = (pressure_imbalance - prev_delta) / dt_min
                    SCALE = 10.0  # 10 pts/min rate change = 1.0 index unit
                    acceleration = round(max(-10.0, min(10.0, raw_rate / SCALE)), 2)
            except (TypeError, ValueError, Exception):
                acceleration = None
                
        prev_chain_id = previous.get("chain_snapshot_id") if isinstance(previous, dict) else None
        pressure_recomputed = (chain_snapshot_id != prev_chain_id) if prev_chain_id else True
        source_state = "NEW_SOURCE_SNAPSHOT" if pressure_recomputed else "UNCHANGED_SOURCE_SNAPSHOT"

        return {
            "status": "LIVE",
            "source_state": source_state,
            "direction": direction,
            "state": state,
            "call_raw": call_pressure,
            "put_raw": put_pressure,
            "call_pressure": call_pressure,
            "put_pressure": put_pressure,
            "normalization_denominator": denom,
            "call_score": call_norm,
            "put_score": put_norm,
            "call_normalized": call_norm,
            "put_normalized": put_norm,
            "net_edge": net_edge,
            "delta": delta,
            "pressure_imbalance": pressure_imbalance,
            "pressure_delta": delta,
            "acceleration": acceleration,
            "evidence_quality": round(100.0 * observed / expected, 2) if expected else 0.0,
            "strikes": strike_results,
            "seven_strike_breadth": len(strike_results),
            "weights": {k: v for k, v in PRESSURE_WEIGHTS.items()},
            "spot_confirmation": (
                "UNAVAILABLE"
                if spot_change is None
                else "UP" if spot_change > 0 else "DOWN" if spot_change < 0 else "FLAT"
            ),
            "chain_row_count": chain_row_count,
            "chain_snapshot_id": chain_snapshot_id,
            "option_chain_source_timestamp": fetched_at,
            "pressure_computed_at": self.clock(),
            "pressure_recomputed": pressure_recomputed,
            "pressure_status": "UNCHANGED SOURCE SNAPSHOT" if not pressure_recomputed else source_state,
            "exact_sign_convention": "+ value = put-side pressure strengthening; - value = call-side pressure strengthening",
        }

    @staticmethod
    def _compute_chain_snapshot_id(rows: Sequence[Mapping[str, Any]], fetched_at: Any) -> str | None:
        if not rows:
            return None
        canonical_rows = []
        for r in sorted(rows, key=lambda x: _number(x.get("strike")) or 0.0):
            ce = r.get("ce") if isinstance(r.get("ce"), Mapping) else {}
            pe = r.get("pe") if isinstance(r.get("pe"), Mapping) else {}
            canonical_rows.append({
                "strike": _number(r.get("strike")),
                "ce_oi": _number(ce.get("oi")),
                "ce_oi_change": _number(ce.get("intraday_change_oi")) if _number(ce.get("intraday_change_oi")) is not None else _number(ce.get("day_change_oi")),
                "ce_volume": _number(ce.get("volume")),
                "ce_ltp": _number(ce.get("ltp")) if _number(ce.get("ltp")) is not None else _number(ce.get("last_price")),
                "pe_oi": _number(pe.get("oi")),
                "pe_oi_change": _number(pe.get("intraday_change_oi")) if _number(pe.get("intraday_change_oi")) is not None else _number(pe.get("day_change_oi")),
                "pe_volume": _number(pe.get("volume")),
                "pe_ltp": _number(pe.get("ltp")) if _number(pe.get("ltp")) is not None else _number(pe.get("last_price")),
            })
        raw_bytes = json.dumps(canonical_rows, sort_keys=True).encode("utf-8")
        return hashlib.md5(raw_bytes).hexdigest()[:12]

    @staticmethod
    def _normalized(value: Any, maximum: float) -> float | None:
        number = _number(value)
        if number is None or maximum <= 0:
            return None
        return round(_clamp(abs(number) / maximum, 0.0, 1.0), 4)

    @staticmethod
    def _signed_normalized(value: Any, maximum: float) -> float | None:
        number = _number(value)
        if number is None or maximum <= 0:
            return None
        return round(max(-1.0, min(1.0, number / maximum)), 4)

    @staticmethod
    def _book_score(leg: Mapping[str, Any]) -> float | None:
        bid, ask = _number(leg.get("top_bid_quantity")), _number(leg.get("top_ask_quantity"))
        if bid is None or ask is None or bid + ask <= 0:
            return None
        return round(_clamp((bid / (bid + ask)), 0.0, 1.0), 4)

    @staticmethod
    def _previous_oi(
        source: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        previous: Mapping[str, Any],
    ) -> dict[str, Any]:
        walls = source.get("walls") if isinstance(source.get("walls"), Mapping) else {}
        totals = source.get("totals") if isinstance(source.get("totals"), Mapping) else {}
        call_wall = (walls.get("highest_ce_oi") or {}).get("strike")
        put_wall = (walls.get("highest_pe_oi") or {}).get("strike")
        ce_intraday = _number(totals.get("intraday_ce_change_oi"))
        pe_intraday = _number(totals.get("intraday_pe_change_oi"))
        underlying = (
            source.get("underlying")
            if isinstance(source.get("underlying"), Mapping)
            else {}
        )
        current_observation = (
            underlying.get("receipt_timestamp")
            or underlying.get("fetched_at")
        )
        previous_observation = (
            previous.get("observation_timestamp")
            or previous.get("receipt_timestamp")
        )
        current_dt = _timestamp(current_observation)
        previous_dt = _timestamp(previous_observation)
        current_symbol = underlying.get("symbol")
        current_expiry = underlying.get("expiry")
        current_strike_scope = sorted(
            {
                strike
                for row in rows
                if (strike := _number(row.get("strike"))) is not None
            }
        )
        previous_strike_scope = previous.get("strike_scope")
        previous_scope_normalized = (
            [_number(strike) for strike in previous_strike_scope]
            if isinstance(previous_strike_scope, list)
            else []
        )
        lineage_reason = None
        if not previous:
            lineage_reason = "PREVIOUS_OI_HISTORY_UNAVAILABLE"
        elif not previous.get("symbol") or not previous.get("expiry"):
            lineage_reason = "PREVIOUS_OI_SCOPE_LINEAGE_UNAVAILABLE"
        elif previous.get("symbol") != current_symbol:
            lineage_reason = "PREVIOUS_OI_SYMBOL_MISMATCH"
        elif previous.get("expiry") != current_expiry:
            lineage_reason = "PREVIOUS_OI_EXPIRY_MISMATCH"
        elif (
            not isinstance(previous_strike_scope, list)
            or not previous_strike_scope
            or any(strike is None for strike in previous_scope_normalized)
        ):
            lineage_reason = "PREVIOUS_OI_STRIKE_SCOPE_UNAVAILABLE"
        elif sorted(previous_scope_normalized) != current_strike_scope:
            lineage_reason = "PREVIOUS_OI_STRIKE_SCOPE_MISMATCH"
        elif current_dt is None or previous_dt is None:
            lineage_reason = "PREVIOUS_OI_TIMESTAMP_UNAVAILABLE"
        elif previous_dt >= current_dt:
            lineage_reason = "PREVIOUS_OI_TIMESTAMP_NOT_ORDERED"
        elif _session_date(previous_observation) != _session_date(current_observation):
            lineage_reason = "PREVIOUS_OI_SESSION_BOUNDARY"
        elif _number(previous.get("aggregate_intraday_ce_change")) is None or _number(
            previous.get("aggregate_intraday_pe_change")
        ) is None:
            lineage_reason = "PREVIOUS_OI_DIRECTIONAL_HISTORY_INCOMPLETE"

        previous_ce = _number(previous.get("aggregate_intraday_ce_change"))
        previous_pe = _number(previous.get("aggregate_intraday_pe_change"))
        migration = {
            "call": ArgusTacticalEdgeEngine._migration(previous.get("call_wall"), call_wall),
            "put": ArgusTacticalEdgeEngine._migration(previous.get("put_wall"), put_wall),
        }
        acceleration = {
            "call": ArgusTacticalEdgeEngine._acceleration(previous_ce, ce_intraday),
            "put": ArgusTacticalEdgeEngine._acceleration(previous_pe, pe_intraday),
        }
        direction, direction_evidence = ArgusTacticalEdgeEngine._previous_oi_direction(
            rows
        )
        available = lineage_reason is None and direction != "UNAVAILABLE"
        return {
            "status": "AVAILABLE" if available else "UNAVAILABLE",
            "reason": lineage_reason or (
                "PREVIOUS_OI_DIRECTIONAL_CLASSIFICATION_UNAVAILABLE"
                if direction == "UNAVAILABLE"
                else None
            ),
            "direction": direction if available else "UNAVAILABLE",
            "direction_evidence": direction_evidence if available else [],
            "current_scope": {
                "symbol": current_symbol,
                "expiry": current_expiry,
                "strike_scope": current_strike_scope,
                "observation_timestamp": current_observation,
                "session_date": _session_date(current_observation),
            },
            "previous_scope": {
                "symbol": previous.get("symbol"),
                "expiry": previous.get("expiry"),
                "strike_scope": previous_strike_scope,
                "observation_timestamp": previous_observation,
                "session_date": _session_date(previous_observation),
            },
            "previous_day_basis": "DHAN_PREVIOUS_OI",
            "session_delta_basis": "PERSISTED_ARGUS_SESSION_BASELINE",
            "call_wall": call_wall,
            "put_wall": put_wall,
            "aggregate_day_ce_change": _number(totals.get("day_ce_change_oi")),
            "aggregate_day_pe_change": _number(totals.get("day_pe_change_oi")),
            "aggregate_intraday_ce_change": ce_intraday,
            "aggregate_intraday_pe_change": pe_intraday,
            "wall_state": {
                "call": ArgusTacticalEdgeEngine._wall_state(rows, call_wall, "ce"),
                "put": ArgusTacticalEdgeEngine._wall_state(rows, put_wall, "pe"),
            },
            "migration": migration,
            "acceleration": acceleration,
            "prior_snapshot_available": bool(previous),
            "lineage_valid": available,
        }

    @staticmethod
    def _previous_oi_direction(
        rows: Sequence[Mapping[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Classify CE/PE OI quadrants only when their labels are explicit."""

        call_support = {
            ("CE", "LONG_BUILDUP"),
            ("CE", "SHORT_COVERING"),
            ("PE", "SHORT_BUILDUP"),
            ("PE", "LONG_UNWINDING"),
        }
        put_support = {
            ("CE", "SHORT_BUILDUP"),
            ("CE", "LONG_UNWINDING"),
            ("PE", "LONG_BUILDUP"),
            ("PE", "SHORT_COVERING"),
        }
        call_count = 0
        put_count = 0
        evidence: list[dict[str, Any]] = []
        for row in rows:
            for side in ("CE", "PE"):
                leg = row.get(side.lower()) if isinstance(row, Mapping) else None
                if not isinstance(leg, Mapping):
                    continue
                state = str(leg.get("positioning") or "").upper()
                key = (side, state)
                if key in call_support:
                    call_count += 1
                    evidence.append({"side": side, "positioning": state, "direction": "CALL"})
                elif key in put_support:
                    put_count += 1
                    evidence.append({"side": side, "positioning": state, "direction": "PUT"})
        if not evidence:
            return "UNAVAILABLE", []
        if call_count == put_count:
            return "BALANCED", evidence
        return ("CALL" if call_count > put_count else "PUT"), evidence

    @staticmethod
    def _wall_state(
        rows: Sequence[Mapping[str, Any]], strike: Any, side: str
    ) -> str:
        row = next(
            (item for item in rows if _number(item.get("strike")) == _number(strike)),
            None,
        )
        leg = row.get(side) if isinstance(row, Mapping) and isinstance(row.get(side), Mapping) else {}
        delta = _number(leg.get("intraday_change_oi"))
        if delta is None:
            return "UNAVAILABLE"
        return "BUILDING" if delta > 0 else "WEAKENING" if delta < 0 else "UNCHANGED"

    @staticmethod
    def _migration(previous: Any, current: Any) -> str:
        before, after = _number(previous), _number(current)
        if before is None or after is None:
            return "UNAVAILABLE"
        if before == after:
            return "STABLE"
        return "HIGHER_STRIKE" if after > before else "LOWER_STRIKE"

    @staticmethod
    def _acceleration(previous: Any, current: Any) -> str:
        before, after = _number(previous), _number(current)
        if before is None or after is None:
            return "UNAVAILABLE"
        return "ACCELERATING" if abs(after) > abs(before) else "DECELERATING" if abs(after) < abs(before) else "UNCHANGED"

    @staticmethod
    def _breadth(pressure: Mapping[str, Any]) -> dict[str, Any]:
        strikes = pressure.get("strikes") or []
        call = sum(
            (_number(row.get("CE", {}).get("score")) or -1.0)
            >= BREADTH_CONFIRMATION_SCORE
            for row in strikes
        )
        put = sum(
            (_number(row.get("PE", {}).get("score")) or -1.0)
            >= BREADTH_CONFIRMATION_SCORE
            for row in strikes
        )
        available = sum(
            row.get(side, {}).get("score") is not None
            for row in strikes
            for side in ("CE", "PE")
        )
        expected = len(strikes) * 2
        direction = "CALL" if call > put else "PUT" if put > call else "BALANCED"
        return {
            "status": "AVAILABLE" if strikes else "UNAVAILABLE",
            "direction": direction,
            "call_confirming_strikes": call,
            "put_confirming_strikes": put,
            "sample_size": len(strikes),
            "coverage": round(100.0 * available / expected, 2) if expected else 0.0,
            "strikes": [
                {
                    "strike": row.get("strike"),
                    "CE": row.get("CE", {}).get("score"),
                    "PE": row.get("PE", {}).get("score"),
                }
                for row in strikes
            ],
        }

    @staticmethod
    def _persistence(
        direction: str,
        history: Sequence[Mapping[str, Any]],
        source_timestamp: Any,
        current_chain_id: str | None = None,
    ) -> dict[str, Any]:
        distinct_history: list[Mapping[str, Any]] = []
        seen_snapshots: set[str] = set()
        for item in history:
            cid = item.get("chain_snapshot_id")
            if cid:
                if cid not in seen_snapshots:
                    seen_snapshots.add(cid)
                    distinct_history.append(item)
            else:
                distinct_history.append(item)

        relevant = distinct_history[-12:]
        contiguous: list[Mapping[str, Any]] = []
        for item in reversed(relevant):
            if item.get("direction") != direction:
                break
            contiguous.append(item)

        last_counted_cid = contiguous[0].get("chain_snapshot_id") if contiguous else current_chain_id
        distinct_count = 1 + len(contiguous)

        first = (
            (
                contiguous[-1].get("observation_timestamp")
                or contiguous[-1].get("receipt_timestamp")
                or contiguous[-1].get("source_timestamp")
            )
            if contiguous
            else source_timestamp
        )
        duration = None
        try:
            duration = max(
                0.0,
                (
                    datetime.fromisoformat(str(source_timestamp))
                    - datetime.fromisoformat(str(first))
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            pass

        return {
            "status": "AVAILABLE",
            "candidate_direction": direction,
            "direction": direction,
            "distinct_confirmation_count": distinct_count,
            "consecutive_confirmations": distinct_count,
            "required_count": 3,
            "last_counted_chain_snapshot_id": last_counted_cid,
            "duration_seconds": duration,
            "timeline": [
                {
                    "calculation_id": item.get("calculation_id"),
                    "timestamp": (
                        item.get("observation_timestamp")
                        or item.get("receipt_timestamp")
                        or item.get("source_timestamp")
                    ),
                    "direction": item.get("direction"),
                    "chain_snapshot_id": item.get("chain_snapshot_id"),
                    "evidence_quality": item.get("evidence_quality"),
                }
                for item in relevant
            ],
            "restart_safe": True,
        }

    @staticmethod
    def _bs_price(spot: float, strike: float, t: float, r: float, sigma: float, option_type: str) -> float:
        import math
        def norm_cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

        if t <= 0 or sigma <= 0:
            return max(0.0, spot - strike) if option_type == "CE" else max(0.0, strike - spot)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        if option_type == "CE":
            return spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
        else:
            return strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)

    @staticmethod
    def _estimate_iv_bs(spot: float, strike: float, expiry: str, price: float, option_type: str, r: float = 0.07) -> tuple[float | None, str, str]:
        if not spot or not strike or not price or price <= 0:
            return None, "UNAVAILABLE", "INVALID_INPUTS"
        try:
            exp_date = datetime.fromisoformat(str(expiry)).date()
            today = datetime.now().date()
            days = max(1, (exp_date - today).days)
            t = days / 365.0
        except Exception:
            t = 4 / 365.0

        import math
        discounted_strike = strike * math.exp(-r * t)
        min_intrinsic = max(0.0, spot - discounted_strike) if option_type == "CE" else max(0.0, discounted_strike - spot)
        if price < min_intrinsic - 1e-2:
            return None, "UNAVAILABLE", "INTRINSIC_VIOLATION"

        low, high = 0.01, 3.0
        for _ in range(30):
            mid = (low + high) / 2.0
            p = ArgusTacticalEdgeEngine._bs_price(spot, strike, t, r, mid, option_type)
            if abs(p - price) < 1e-3:
                return round(mid * 100, 2), "ESTIMATED", "SOLVER_CONVERGED"
            if p < price:
                low = mid
            else:
                high = mid
        res_iv = round(((low + high) / 2.0) * 100, 2)
        if 1.0 <= res_iv <= 200.0:
            return res_iv, "ESTIMATED", "SOLVER_APPROXIMATED"
        return None, "UNAVAILABLE", "OUT_OF_BOUNDS"

    @staticmethod
    def _iv_intelligence(
        rows: Sequence[Mapping[str, Any]],
        selection: Mapping[str, Any],
        previous: Mapping[str, Any],
        underlying: Mapping[str, Any] = None,
    ) -> dict[str, Any]:
        spot = _number((underlying or {}).get("ltp"))
        expiry = (underlying or {}).get("expiry")

        ce_values, pe_values = [], []
        used_fallback = False
        strike_greeks_table = []

        for row in rows:
            strike = _number(row.get("strike"))
            ce_leg = row.get("ce") if isinstance(row.get("ce"), Mapping) else {}
            pe_leg = row.get("pe") if isinstance(row.get("pe"), Mapping) else {}

            ce_iv = _number(ce_leg.get("iv"))
            ce_ltp = _number(ce_leg.get("ltp")) or _number(ce_leg.get("last_price")) or 0.0
            ce_src = "DHAN"
            if (
                (ce_iv is None or ce_iv <= 0)
                and strike
                and ce_ltp > 0
                and spot is not None
                and expiry
            ):
                est_iv, est_src, _ = ArgusTacticalEdgeEngine._estimate_iv_bs(spot, strike, expiry, ce_ltp, "CE")
                if est_iv:
                    ce_iv, ce_src = est_iv, est_src
                    used_fallback = True

            pe_iv = _number(pe_leg.get("iv"))
            pe_ltp = _number(pe_leg.get("ltp")) or _number(pe_leg.get("last_price")) or 0.0
            pe_src = "DHAN"
            if (
                (pe_iv is None or pe_iv <= 0)
                and strike
                and pe_ltp > 0
                and spot is not None
                and expiry
            ):
                est_iv, est_src, _ = ArgusTacticalEdgeEngine._estimate_iv_bs(spot, strike, expiry, pe_ltp, "PE")
                if est_iv:
                    pe_iv, pe_src = est_iv, est_src
                    used_fallback = True

            if ce_iv is not None:
                ce_values.append(ce_iv)
            if pe_iv is not None:
                pe_values.append(pe_iv)

            if strike:
                strike_greeks_table.append({
                    "strike": strike,
                    "ce_iv": ce_iv,
                    "ce_delta": _number(ce_leg.get("delta")),
                    "ce_gamma": _number(ce_leg.get("gamma")),
                    "ce_theta": _number(ce_leg.get("theta")),
                    "ce_vega": _number(ce_leg.get("vega")),
                    "pe_iv": pe_iv,
                    "pe_delta": _number(pe_leg.get("delta")),
                    "pe_gamma": _number(pe_leg.get("gamma")),
                    "pe_theta": _number(pe_leg.get("theta")),
                    "pe_vega": _number(pe_leg.get("vega")),
                    "iv_source": ce_src if ce_src == pe_src else "MIXED",
                })

        native_ce_present = any(_number(r.get("ce", {}).get("iv")) is not None for r in rows if isinstance(r.get("ce"), Mapping))
        native_pe_present = any(_number(r.get("pe", {}).get("iv")) is not None for r in rows if isinstance(r.get("pe"), Mapping))

        ce_median, pe_median = _median(ce_values), _median(pe_values)
        coverage = (
            sum(value is not None for value in ce_values + pe_values)
            / max(1, len(ce_values + pe_values))
            * 100
        )
        if ce_median is None or pe_median is None or not native_ce_present or not native_pe_present:
            return {
                "status": "UNAVAILABLE",
                "reason": "AUTHORITATIVE_IV_FIELDS_INCOMPLETE",
                "ce_median": ce_median,
                "pe_median": pe_median,
                "coverage": round(coverage, 2),
                "direction": "UNAVAILABLE",
                "crush_risk": "UNAVAILABLE",
                "iv_source": "ESTIMATED" if used_fallback else "UNAVAILABLE",
                "strike_greeks_table": strike_greeks_table,
            }

        prior_values = [
            _number(previous.get("ce_iv_median")),
            _number(previous.get("pe_iv_median")),
        ]
        prior = _median(prior_values)
        current = median([ce_median, pe_median])
        direction = (
            "UNAVAILABLE"
            if prior is None
            else "RISING"
            if current > prior * 1.01
            else "FALLING"
            if current < prior * 0.99
            else "STABLE"
        )
        skew = pe_median - ce_median
        breadth = sum(
            value is not None and value >= current for value in ce_values + pe_values
        )
        distortion = abs(skew) / current if current else None
        crush = (
            "UNAVAILABLE"
            if direction == "UNAVAILABLE"
            else "ELEVATED"
            if direction == "FALLING" and current > prior
            else "PRESENT"
            if direction == "FALLING"
            else "LOW"
        )
        return {
            "status": "AVAILABLE",
            "ce_median": round(ce_median, 4),
            "pe_median": round(pe_median, 4),
            "skew": round(skew, 4),
            "breadth_above_median": breadth,
            "coverage": round(coverage, 2),
            "distortion": None if distortion is None else round(distortion, 4),
            "direction": direction,
            "crush_risk": crush,
            "iv_source": "ESTIMATED" if used_fallback else "DHAN",
            "prior_snapshot_available": prior is not None,
            "greeks": "AVAILABLE" if strike_greeks_table else "UNAVAILABLE",
            "strike_greeks_table": strike_greeks_table,
        }

    @staticmethod
    def _premium_attribution(
        rows: Sequence[Mapping[str, Any]],
        underlying: Mapping[str, Any],
        selection: Mapping[str, Any],
    ) -> dict[str, Any]:
        spot = _number(underlying.get("ltp"))
        result: dict[str, Any] = {
            "status": "PARTIAL" if spot is not None else "UNAVAILABLE",
            "greek_attribution": "UNAVAILABLE",
            "unavailable": [
                "OPTION_PREMIUM_HISTORY_UNAVAILABLE",
                "GREEK_MOVE_ATTRIBUTION_UNAVAILABLE",
            ],
        }
        for side in ("CE", "PE"):
            contract = selection.get(side) if isinstance(selection.get(side), Mapping) else {}
            strike, premium = _number(contract.get("strike")), _number(contract.get("premium"))
            intrinsic = None
            if spot is not None and strike is not None:
                intrinsic = max(0.0, spot - strike) if side == "CE" else max(0.0, strike - spot)
            extrinsic = (
                max(0.0, premium - intrinsic)
                if premium is not None and intrinsic is not None
                else None
            )
            leg = next(
                (
                    row.get(side.lower())
                    for row in rows
                    if _number(row.get("strike")) == strike
                    and isinstance(row.get(side.lower()), Mapping)
                ),
                {},
            )
            delta = _number(leg.get("delta"))
            spot_change = _number(underlying.get("spot_change"))
            actual_move = _number(leg.get("intraday_price_change"))
            delta_attr = (
                delta * spot_change
                if delta is not None and spot_change is not None
                else None
            )
            residual_move = (
                round(actual_move - delta_attr, 2)
                if actual_move is not None and delta_attr is not None
                else None
            )

            stretch_score, stretch_state = ArgusTacticalEdgeEngine._compute_stretch(premium)

            result[side] = {
                "premium": premium,
                "intrinsic": None if intrinsic is None else round(intrinsic, 4),
                "extrinsic": None if extrinsic is None else round(extrinsic, 4),
                "intrinsic_percentage": (
                    None
                    if premium in (None, 0) or intrinsic is None
                    else round(intrinsic / premium * 100, 2)
                ),
                "extrinsic_percentage": (
                    None
                    if premium in (None, 0) or extrinsic is None
                    else round(extrinsic / premium * 100, 2)
                ),
                "activity": leg.get("activity"),
                "intraday_price_change": leg.get("intraday_price_change"),
                "intraday_oi_change": leg.get("intraday_change_oi"),
                "vwap_deviation_pct": None,
                "rolling_mean_pct": None,
                "ema_distance_atr": None,
                "rolling_z_score": None,
                "actual_move": actual_move,
                "delta_expected_move": (
                    round(delta_attr, 2) if delta_attr is not None else None
                ),
                "residual_move": residual_move,
                "iv_contribution": None,
                "range_percentile": None,
                "stretch_score": stretch_score,
                "stretch_state": stretch_state,
                "attribution_status": (
                    "PARTIAL"
                    if delta_attr is not None and actual_move is not None
                    else "UNAVAILABLE"
                ),
            }
        return result

    @staticmethod
    def _ose_direction(
        ose: Mapping[str, Any], selection: Mapping[str, Any], side: str
    ) -> str:
        contracts = ose.get("contracts") if isinstance(ose.get("contracts"), Mapping) else {}
        contract = contracts.get(side) if isinstance(contracts.get(side), Mapping) else {}
        composite = contract.get("composite") if isinstance(contract.get("composite"), Mapping) else {}
        label = str(composite.get("label") or contract.get("vob", {}).get("state") or "")
        if "BULLISH" in label:
            return "CALL" if side == "CE" else "PUT"
        if "BEARISH" in label:
            return "PUT" if side == "CE" else "CALL"
        return "BALANCED"

    def _continuation_reversal(
        self,
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        iv: Mapping[str, Any],
        ose: Mapping[str, Any],
        selection: Mapping[str, Any],
        history: Sequence[Mapping[str, Any]],
        source_timestamp: Any,
    ) -> dict[str, Any]:
        direction = pressure.get("direction")
        selected_side = "CE" if direction == "CALL" else "PE" if direction == "PUT" else None
        ose_direction = (
            self._ose_direction(ose, selection, selected_side)
            if selected_side
            else "BALANCED"
        )
        reasons: list[str] = []
        contributions = {
            "pressure_context": 0.0,
            "breadth": 0.0,
            "ose_structure": 0.0,
            "persistence": 0.0,
            "iv_context": 0.0,
        }
        if direction == "BALANCED":
            reasons.append("PRESSURE_BALANCED")
        else:
            pressure_delta = abs(_number(pressure.get("delta")) or 0.0)
            contributions["pressure_context"] = round(
                min(
                    REGIME_WEIGHTS["pressure_context"],
                    pressure_delta / 100.0 * REGIME_WEIGHTS["pressure_context"],
                ),
                2,
            )
            reasons.append("PRESSURE_DIRECTIONAL_CONTEXT")
            if breadth.get("direction") == direction:
                contributions["breadth"] = REGIME_WEIGHTS["breadth"]
                reasons.append("BREADTH_CONFIRMS")
            elif breadth.get("direction") not in {direction, "BALANCED"}:
                contributions["breadth"] = -REGIME_WEIGHTS["breadth"]
                reasons.append("BREADTH_OPPOSES")
            else:
                reasons.append("BREADTH_BALANCED")
            if ose_direction == direction:
                contributions["ose_structure"] = REGIME_WEIGHTS["ose_structure"]
                reasons.append("OSE_STRUCTURE_CONFIRMS")
            elif ose_direction not in {direction, "BALANCED"}:
                contributions["ose_structure"] = -REGIME_WEIGHTS["ose_structure"]
                reasons.append("OSE_STRUCTURE_OPPOSES")
            else:
                reasons.append("OSE_STRUCTURE_BALANCED")
            if (
                persistence.get("direction") == direction
                and (
                    (persistence.get("consecutive_confirmations") or 0)
                    >= REGIME_CONFIRMATION_SNAPSHOTS
                    or (_number(persistence.get("duration_seconds")) or 0.0)
                    >= REGIME_CONFIRMATION_SECONDS
                )
            ):
                contributions["persistence"] = REGIME_WEIGHTS["persistence"]
                reasons.append("PERSISTENCE_CONFIRMS")
            else:
                reasons.append("PERSISTENCE_PENDING")

        if iv.get("direction") == "FALLING":
            reasons.append("IV_FALLING_CONTEXT_ONLY")
        elif iv.get("direction") == "UNAVAILABLE":
            reasons.append("IV_DIRECTION_UNAVAILABLE")

        raw_compass = round(
            _clamp(sum(contributions.values()), -100.0, 100.0),
            2,
        )
        raw_state = (
            "CONTINUATION"
            if direction != "BALANCED" and raw_compass >= REGIME_BALANCED_LIMIT
            else "REVERSAL"
            if direction != "BALANCED" and raw_compass <= -REGIME_BALANCED_LIMIT
            else "BALANCED"
        )
        extreme_break = self._extreme_break(
            raw_state, pressure, breadth, ose, selected_side, ose_direction
        )
        transition = self._stabilize_regime(
            raw_state,
            raw_compass,
            history,
            source_timestamp,
            extreme_break,
        )
        return {
            "status": "AVAILABLE",
            "state": transition["confirmed_state"],
            "confirmed_state": transition["confirmed_state"],
            "raw_state": raw_state,
            "compass": transition["confirmed_compass"],
            "raw_compass": raw_compass,
            "continuation_points": round(
                sum(max(0.0, value) for value in contributions.values()), 2
            ),
            "reversal_points": round(
                sum(abs(min(0.0, value)) for value in contributions.values()), 2
            ),
            "contributions": contributions,
            "direction": direction,
            "market_direction": direction,
            "regime_character": transition["confirmed_state"],
            "ose_direction": ose_direction,
            "pending_state": transition["pending_state"],
            "pending_count": transition["pending_count"],
            "pending_since": transition["pending_since"],
            "pending_seconds": transition["pending_seconds"],
            "state_change_pending": transition["pending_state"] is not None,
            "transition_reason": transition["transition_reason"],
            "extreme_break_override": extreme_break,
            "reason_codes": reasons,
        }

    @staticmethod
    def _extreme_break(
        raw_state: str,
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        ose: Mapping[str, Any],
        selected_side: str | None,
        ose_direction: str,
    ) -> bool:
        if raw_state == "BALANCED" or selected_side is None:
            return False
        contracts = (
            ose.get("contracts")
            if isinstance(ose.get("contracts"), Mapping)
            else {}
        )
        contract = (
            contracts.get(selected_side)
            if isinstance(contracts.get(selected_side), Mapping)
            else {}
        )
        structures = (
            contract.get("structures")
            if isinstance(contract.get("structures"), Mapping)
            else {}
        )
        five = (
            structures.get("5m")
            if isinstance(structures.get("5m"), Mapping)
            else {}
        )
        direction = pressure.get("direction")
        breadth_count = (
            breadth.get("call_confirming_strikes", 0)
            if direction == "CALL"
            else breadth.get("put_confirming_strikes", 0)
        )
        strong_context = (
            abs(_number(pressure.get("delta")) or 0.0)
            >= EXTREME_BREAK_PRESSURE_DELTA
            and breadth.get("direction") == direction
            and breadth_count >= EXTREME_BREAK_BREADTH_CONFIRMATIONS
            and five.get("completed_bucket") is True
        )
        if raw_state == "CONTINUATION":
            return bool(
                strong_context
                and ose_direction == direction
                and five.get("supply_break") is True
            )
        return bool(
            strong_context
            and ose_direction not in {direction, "BALANCED"}
            and five.get("demand_break") is True
        )

    @staticmethod
    def _stabilize_regime(
        raw_state: str,
        raw_compass: float,
        history: Sequence[Mapping[str, Any]],
        source_timestamp: Any,
        extreme_break: bool,
    ) -> dict[str, Any]:
        previous = history[-1] if history else {}
        confirmed = str(previous.get("confirmed_regime_state") or "BALANCED")
        confirmed_compass = _number(previous.get("confirmed_compass"))
        if confirmed_compass is None:
            confirmed_compass = 0.0
        pending_state: str | None = None
        pending_since: Any = None
        pending_count = 0
        pending_seconds = 0.0
        transition_reason = "CONFIRMED_STATE_RETAINED"

        candidate = raw_state
        if confirmed == "CONTINUATION":
            candidate = (
                "CONTINUATION"
                if raw_compass >= REGIME_EXIT_LIMIT
                else "REVERSAL"
                if raw_compass <= -REGIME_BALANCED_LIMIT
                else "BALANCED"
            )
        elif confirmed == "REVERSAL":
            candidate = (
                "REVERSAL"
                if raw_compass <= -REGIME_EXIT_LIMIT
                else "CONTINUATION"
                if raw_compass >= REGIME_BALANCED_LIMIT
                else "BALANCED"
            )

        if candidate == confirmed:
            confirmed_compass = raw_compass
            transition_reason = "RAW_MATCHES_CONFIRMED"
        else:
            previous_pending = previous.get("pending_regime_state")
            if previous_pending == candidate:
                pending_state = candidate
                pending_since = previous.get("pending_regime_since")
                pending_count = int(previous.get("pending_regime_count") or 0) + 1
            else:
                pending_state = candidate
                pending_since = source_timestamp
                pending_count = 1
            try:
                pending_seconds = max(
                    0.0,
                    (
                        datetime.fromisoformat(str(source_timestamp))
                        - datetime.fromisoformat(str(pending_since))
                    ).total_seconds(),
                )
            except (TypeError, ValueError):
                pending_seconds = 0.0
            if extreme_break:
                confirmed = candidate
                confirmed_compass = raw_compass
                pending_state = None
                pending_since = None
                pending_count = 0
                transition_reason = "CENTRALIZED_EXTREME_BREAK_OVERRIDE"
            elif (
                pending_count >= REGIME_CONFIRMATION_SNAPSHOTS
                or pending_seconds >= REGIME_CONFIRMATION_SECONDS
            ):
                confirmed = candidate
                confirmed_compass = raw_compass
                pending_state = None
                pending_since = None
                pending_count = 0
                transition_reason = "HYSTERESIS_CONFIRMATION_COMPLETE"
            else:
                transition_reason = "HYSTERESIS_CONFIRMATION_PENDING"
        return {
            "confirmed_state": confirmed,
            "confirmed_compass": round(confirmed_compass, 2),
            "pending_state": pending_state,
            "pending_since": pending_since,
            "pending_count": pending_count,
            "pending_seconds": round(pending_seconds, 2),
            "transition_reason": transition_reason,
        }

    def _entry_lifecycle(
        self,
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        continuation: Mapping[str, Any],
        ose: Mapping[str, Any],
        selection: Mapping[str, Any],
        previous: Mapping[str, Any],
    ) -> dict[str, Any]:
        direction = pressure.get("direction")
        side = "CE" if direction == "CALL" else "PE" if direction == "PUT" else None
        contracts = ose.get("contracts") if isinstance(ose.get("contracts"), Mapping) else {}
        contract = contracts.get(side) if side and isinstance(contracts.get(side), Mapping) else {}
        structures = contract.get("structures") if isinstance(contract.get("structures"), Mapping) else {}
        five = structures.get("5m") if isinstance(structures.get("5m"), Mapping) else {}
        state = "CONTEXT"
        hard_invalidation = False
        evidence_cancelled = False
        reasons: list[str] = []
        previous_state = str(previous.get("entry_state") or "")
        if side is None:
            state, evidence_cancelled = "WAIT", True
            reasons.append("NO_DIRECTIONAL_PRESSURE")
        elif not five or five.get("completed_bucket") is not True:
            state = "CONTEXT"
            reasons.append("COMPLETED_5M_CONTEXT_UNAVAILABLE")
        elif five.get("bearish_retest"):
            state, hard_invalidation = "REJECTION", True
            reasons.append("DEMAND_BREAK_RETEST_REJECTED")
        elif str(five.get("state")) == "BEARISH":
            state, hard_invalidation = "INVALIDATED", True
            reasons.append("SELECTED_CONTRACT_5M_BEARISH")
        elif previous_state in {"REJECTION", "INVALIDATED"} and (
            five.get("bullish_retest") or str(five.get("state")) == "BULLISH"
        ):
            state = "RESUMPTION"
            reasons.append("STRUCTURE_RECOVERED_AFTER_REJECTION")
        elif previous_state == "RETEST" and five.get("bullish_retest") and continuation.get("state") == "CONTINUATION":
            state = "READY"
            reasons.append("RETEST_PERSISTED_WITH_CONTINUATION")
        elif five.get("bullish_retest"):
            state = "RETEST"
            reasons.append("SUPPLY_BREAK_RETEST_HELD")
        elif five.get("supply_break"):
            state = "ACCEPTANCE"
            reasons.append("SUPPLY_CLOSE_BREAK_ACCEPTED")
        elif str(five.get("state")) == "BULLISH":
            state = "ESCAPE"
            reasons.append("STRUCTURE_ESCAPING_RANGE")
        elif continuation.get("state") == "CONTINUATION" and breadth.get("direction") == direction:
            state = "READY"
            reasons.append("DIRECTIONAL_EVIDENCE_ALIGNED")
        else:
            state, evidence_cancelled = "WAIT", True
            reasons.append("EVIDENCE_NOT_YET_ALIGNED")
        assert state in ENTRY_STATES
        return {
            "status": "AVAILABLE",
            "state": state,
            "side": side or "NONE",
            "hard_invalidation": hard_invalidation,
            "evidence_cancelled": evidence_cancelled,
            "reason_codes": reasons,
            "spine": [
                {
                    "state": name,
                    "active": name == state,
                    "complete": ENTRY_STATES.index(name) < ENTRY_STATES.index(state),
                }
                for name in ENTRY_STATES
            ],
        }

    @staticmethod
    def _quality_dimensions(
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        iv: Mapping[str, Any],
        continuation: Mapping[str, Any],
        selection: Mapping[str, Any],
        ose: Mapping[str, Any],
    ) -> dict[str, Any]:
        coverage = (
            (_number(pressure.get("evidence_quality")) or 0.0)
            + (_number(breadth.get("coverage")) or 0.0)
            + (_number(iv.get("coverage")) or 0.0)
        ) / 3.0
        freshness = 100.0
        completeness = (
            100.0
            if selection.get("status") == "AVAILABLE"
            and ose.get("status") == "LIVE"
            else 0.0
        )
        data_quality = (
            coverage * DATA_QUALITY_WEIGHTS["coverage"]
            + freshness * DATA_QUALITY_WEIGHTS["freshness"]
            + completeness * DATA_QUALITY_WEIGHTS["completeness"]
        )
        direction = pressure.get("direction")
        breadth_direction = breadth.get("direction")
        ose_direction = continuation.get("ose_direction")
        if direction == "BALANCED":
            agreement = 0.0
            agreement_status = "NO_DIRECTIONAL_EVIDENCE"
        else:
            aligned = sum(
                value == direction for value in (breadth_direction, ose_direction)
            )
            opposed = sum(
                value not in {direction, "BALANCED"}
                for value in (breadth_direction, ose_direction)
            )
            agreement = _clamp(50.0 + aligned * 25.0 - opposed * 25.0)
            agreement_status = (
                "ALIGNED"
                if agreement >= 75.0
                else "MIXED"
                if agreement >= 40.0
                else "CONTRADICTORY"
            )
        pending_count = int(continuation.get("pending_count") or 0)
        pending_seconds = _number(continuation.get("pending_seconds")) or 0.0
        if continuation.get("state_change_pending"):
            stability = min(
                99.0,
                max(
                    pending_count / REGIME_CONFIRMATION_SNAPSHOTS * 100.0,
                    pending_seconds / REGIME_CONFIRMATION_SECONDS * 100.0,
                ),
            )
            stability_status = "PENDING"
        else:
            stability = 100.0
            stability_status = "STABLE"
        return {
            "data_quality": {
                "score": round(_clamp(data_quality), 2),
                "status": "HIGH" if data_quality >= 80.0 else "PARTIAL",
                "components": {
                    "coverage": round(_clamp(coverage), 2),
                    "freshness": freshness,
                    "completeness": completeness,
                },
            },
            "evidence_agreement": {
                "score": round(_clamp(agreement), 2),
                "status": agreement_status,
                "market_direction": direction,
                "breadth_direction": breadth_direction,
                "ose_direction": ose_direction,
            },
            "signal_stability": {
                "score": round(_clamp(stability), 2),
                "status": stability_status,
                "confirmed_state": continuation.get("confirmed_state"),
                "raw_state": continuation.get("raw_state"),
                "pending_count": pending_count,
                "pending_seconds": pending_seconds,
            },
            "actionability": {
                "score": 0.0,
                "status": "NOT_EVALUATED",
            },
        }

    def _setups(
        self,
        quality: Mapping[str, Any],
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        entry: Mapping[str, Any],
        continuation: Mapping[str, Any],
        selection: Mapping[str, Any],
        ose: Mapping[str, Any],
    ) -> dict[str, Any]:
        base_failures: list[str] = []
        if selection.get("status") != "AVAILABLE":
            base_failures.append("CONTRACT_IDENTITY_UNAVAILABLE")
        if ose.get("status") != "LIVE":
            base_failures.append("OSE_INPUT_NOT_LIVE")
        if entry.get("hard_invalidation"):
            base_failures.append("UNRESOLVED_HARD_INVALIDATION")
        standard = {
            "class": "STANDARD_DIRECTIONAL",
            "status": "AVAILABLE" if not base_failures else "UNAVAILABLE",
            "qualified": not base_failures and pressure.get("direction") != "BALANCED",
            "mandatory_failures": base_failures,
            "scoring_only": [
                "PRESSURE", "PREVIOUS_OI", "BREADTH", "PERSISTENCE",
                "IV", "PREMIUM_ATTRIBUTION", "VOB", "TREND",
            ],
        }
        agreement = (
            pressure.get("direction") != "BALANCED"
            and pressure.get("direction") == breadth.get("direction")
            and pressure.get("direction") == continuation.get("ose_direction")
        )
        scoring_misses: list[str] = []
        if not agreement:
            scoring_misses.append("PRESSURE_BREADTH_OSE_NOT_ALIGNED")
        data_quality = _number(
            (quality.get("data_quality") or {}).get("score")
        ) or 0.0
        evidence_agreement = _number(
            (quality.get("evidence_agreement") or {}).get("score")
        ) or 0.0
        stability = quality.get("signal_stability") or {}
        if data_quality < HIGH_CONVICTION_EVIDENCE_QUALITY:
            scoring_misses.append("DATA_QUALITY_BELOW_THRESHOLD")
        if evidence_agreement < HIGH_CONVICTION_EVIDENCE_QUALITY:
            scoring_misses.append("EVIDENCE_AGREEMENT_BELOW_THRESHOLD")
        if (
            stability.get("status") != "STABLE"
            or continuation.get("confirmed_state") == "BALANCED"
        ):
            scoring_misses.append("SIGNAL_STABILITY_NOT_CONFIRMED")
        high = {
            "class": "HIGH_CONVICTION",
            "status": "AVAILABLE" if not base_failures else "UNAVAILABLE",
            "qualified": not base_failures and not scoring_misses,
            "mandatory_failures": base_failures,
            "scoring_misses": scoring_misses,
            "data_quality_threshold": HIGH_CONVICTION_EVIDENCE_QUALITY,
            "evidence_agreement_threshold": HIGH_CONVICTION_EVIDENCE_QUALITY,
        }
        gamma = {
            "class": "GAMMA_BLAST",
            "status": "UNAVAILABLE",
            "qualified": False,
            "reason": GAMMA_UNAVAILABLE_REASON,
            "normal_trade_gate": False,
            "expiry_only_specialist_overlay": True,
        }
        return {
            "STANDARD_DIRECTIONAL": standard,
            "HIGH_CONVICTION": high,
            "GAMMA_BLAST": gamma,
        }

    @staticmethod
    def _melt_risk(
        iv: Mapping[str, Any],
        premium: Mapping[str, Any],
        pressure: Mapping[str, Any],
    ) -> dict[str, Any]:
        if iv.get("status") != "AVAILABLE":
            return {"status": "UNAVAILABLE", "state": "UNAVAILABLE", "reason": iv.get("reason")}
        ratios = []
        for side in ("CE", "PE"):
            values = premium.get(side) if isinstance(premium.get(side), Mapping) else {}
            premium_value = _number(values.get("premium"))
            extrinsic = _number(values.get("extrinsic"))
            if premium_value and extrinsic is not None:
                ratios.append(extrinsic / premium_value)
        if not ratios:
            return {"status": "UNAVAILABLE", "state": "UNAVAILABLE", "reason": "PREMIUM_ATTRIBUTION_UNAVAILABLE"}
        extrinsic_ratio = median(ratios)
        state = (
            "ELEVATED"
            if iv.get("direction") == "FALLING" and extrinsic_ratio >= 0.5
            else "WATCH"
            if extrinsic_ratio >= 0.5
            else "LOW"
        )
        return {
            "status": "AVAILABLE",
            "state": state,
            "extrinsic_ratio": round(extrinsic_ratio, 4),
            "iv_direction": iv.get("direction"),
            "pressure_state": pressure.get("state"),
        }

    @staticmethod
    def _compute_entry_zone(
        side: str,
        selection: Mapping[str, Any],
        premium: Mapping[str, Any],
    ) -> tuple[float | None, float | None, bool]:
        active_side = "CE" if side in ("CALL", "CE") else "PE" if side in ("PUT", "PE") else None
        if not active_side or selection.get("status") != "AVAILABLE":
            return None, None, False

        side_prem = premium.get(active_side) if isinstance(premium.get(active_side), Mapping) else {}
        premium_val = _number(side_prem.get("premium"))
        intrinsic = _number(side_prem.get("intrinsic"))
        extrinsic = _number(side_prem.get("extrinsic"))

        if premium_val is None or premium_val <= 0:
            return None, None, False

        reference_prem = (intrinsic + extrinsic) if (intrinsic is not None and extrinsic is not None) else premium_val
        stretch_pct = ((premium_val - reference_prem) / premium_val) * 100.0 if reference_prem > 0 else 0.0
        is_stretched = stretch_pct > 3.0

        # Objective premium bounds from top-of-book bid/ask if available in selection
        contract_data = selection.get(active_side) if isinstance(selection.get(active_side), Mapping) else {}
        top_bid = _number(contract_data.get("top_bid_price"))
        top_ask = _number(contract_data.get("top_ask_price"))

        if top_bid is not None and top_ask is not None and top_bid > 0 and top_ask >= top_bid:
            low = round(top_bid, 1)
            high = round(top_ask, 1)
        else:
            # Without objective bid/ask or premium structure, mark entry zone bounds unavailable
            low, high = None, None

        return low, high, is_stretched

    @staticmethod
    def _compute_timing_guidance(
        side: str,
        gate: str,
        entry_state: str,
        is_stretched: bool,
        hard_invalidation: bool,
        evidence_cancelled: bool,
        current_premium: float | None,
        entry_high: float | None,
    ) -> str:
        if hard_invalidation or evidence_cancelled or entry_state == "INVALIDATED":
            return "EXIT"
        if side in ("CALL", "PUT"):
            if is_stretched:
                return "WAIT FOR PULLBACK"
            if entry_state in ("RETEST", "READY"):
                if current_premium is not None and entry_high is not None and current_premium > entry_high:
                    return "WAIT FOR PULLBACK"
                return "WAIT FOR RETEST"
            if entry_state in ("ACCEPTANCE", "ESCAPE", "BUILDING", "CONTEXT"):
                return "WAIT FOR CONFIRMATION"
            if entry_state == "RESUMPTION":
                return "MANAGE EXISTING POSITION"
            return "WAIT FOR CONFIRMATION"
        if side == "BALANCED":
            if entry_state == "RETEST":
                return "WAIT FOR RETEST"
            return "NO TRADE"
        return "UNAVAILABLE"

    @staticmethod
    def _compute_hold_guidance(
        timing_guidance: str,
        entry_state: str,
        entry_low: float | None,
        entry_high: float | None,
    ) -> str:
        if timing_guidance == "WAIT FOR PULLBACK":
            if entry_low is not None and entry_high is not None:
                return f"Wait for pullback to entry zone ({entry_low:g}–{entry_high:g}) before entry"
            return "Wait for pullback to reference premium before entry"
        if timing_guidance == "WAIT FOR RETEST":
            return "Hold off entry until retest level confirms structural support"
        if timing_guidance == "MANAGE EXISTING POSITION":
            return "Trail stop after confirmed continuation"
        if timing_guidance == "EXIT":
            return "Exit immediately on invalidation"
        return "No open position to hold"

    @staticmethod
    def _compute_invalidation_level(
        side: str,
        spot: float | None,
        previous_oi: Mapping[str, Any],
    ) -> str:
        if side in ("CALL", "CE"):
            put_wall = _number(previous_oi.get("put_wall"))
            if put_wall is not None and spot is not None and put_wall < spot:
                return f"Spot < {put_wall:,.0f}"
        elif side in ("PUT", "PE"):
            call_wall = _number(previous_oi.get("call_wall"))
            if call_wall is not None and spot is not None and call_wall > spot:
                return f"Spot > {call_wall:,.0f}"
        # Without an objective wall or structural level, return UNAVAILABLE rather than arbitrary %
        return "UNAVAILABLE"

    @staticmethod
    def _compute_risk_reward(
        side: str,
        current_premium: float | None,
        entry_high: float | None,
    ) -> str:
        # Require objective option target and stop levels rather than arbitrary percentages
        # If target or stop level in option premium terms is not explicitly defined by option structure, return UNAVAILABLE
        return "UNAVAILABLE"

    @staticmethod
    def _compute_evidence_and_readiness(
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        continuation: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        iv: Mapping[str, Any],
        premium_attribution: Mapping[str, Any],
        entry: Mapping[str, Any],
        selection: Mapping[str, Any],
        is_stretched: bool,
        status: str,
    ) -> tuple[int, int, int, str]:
        """Compute readiness score from 6 independent, capped evidence groups."""
        direction = pressure.get("direction")
        side = "CE" if direction == "CALL" else "PE" if direction == "PUT" else None

        groups = {}

        # Group 1: Directional Pressure (pressure direction only; acceleration is context only)
        groups["directional_pressure"] = {
            "available": pressure.get("status") == "LIVE",
            "supportive": direction in ("CALL", "PUT"),
        }

        # Group 2: Participation & Persistence (breadth + persistence)
        consec = persistence.get("consecutive_confirmations") or 0
        breadth_supp = breadth.get("direction") == direction if direction != "BALANCED" else False
        groups["participation"] = {
            "available": breadth.get("status") == "AVAILABLE" or persistence.get("status") == "AVAILABLE",
            "supportive": breadth_supp or consec >= 3,
        }

        # Group 3: Structure & Lifecycle (regime continuation + entry state)
        entry_st = entry.get("state")
        groups["structure_lifecycle"] = {
            "available": continuation.get("status") == "AVAILABLE" or entry.get("status") == "AVAILABLE",
            "supportive": continuation.get("confirmed_state") in ("CONTINUATION", "REVERSAL") or entry_st in ("READY", "RETEST", "ACCEPTANCE"),
        }

        # Group 4: Positioning & Walls (OI wall state + aggregate change)
        wall_st = previous_oi.get("wall_state", {}) if isinstance(previous_oi.get("wall_state"), Mapping) else {}
        active_wall_st = wall_st.get("call" if direction == "CALL" else "put") if side else None
        ce_chg = _number(previous_oi.get("aggregate_intraday_ce_change"))
        pe_chg = _number(previous_oi.get("aggregate_intraday_pe_change"))
        oi_supp = (ce_chg > 0 if direction == "CALL" else pe_chg > 0 if direction == "PUT" else False) if (ce_chg is not None or pe_chg is not None) else False
        groups["positioning"] = {
            "available": previous_oi.get("status") == "AVAILABLE",
            "supportive": active_wall_st == "BUILDING" or oi_supp,
        }

        # Group 5: Volatility & Stretch (IV stability + stretch quality)
        iv_dir = iv.get("direction")
        crush = iv.get("crush_risk")
        iv_supp = iv_dir in ("STABLE", "EXPANDING") and crush != "ELEVATED"
        groups["volatility_stretch"] = {
            "available": iv.get("status") == "AVAILABLE" or premium_attribution.get("status") == "AVAILABLE",
            "supportive": iv_supp and not is_stretched,
        }

        # Group 6: Contract Execution (contract selection status)
        groups["contract_execution"] = {
            "available": selection.get("status") == "AVAILABLE",
            "supportive": selection.get("status") == "AVAILABLE",
        }

        eligible = [g for g in groups.values() if g["available"]]
        evidence_total = len(eligible)
        evidence_count = sum(1 for g in eligible if g["supportive"])

        if evidence_total == 0:
            return 0, 0, 0, "NO EDGE"

        raw_score = (evidence_count / evidence_total) * 100.0

        penalties = 0.0
        if breadth.get("direction") not in (direction, "BALANCED"):
            penalties += 15.0
        if is_stretched:
            penalties += 15.0
        if status != "LIVE":
            penalties += 25.0
        if entry.get("hard_invalidation") or entry.get("evidence_cancelled"):
            penalties += 50.0

        readiness_score = int(round(_clamp(raw_score - penalties, 0.0, 100.0)))

        if readiness_score >= 85:
            readiness_label = "STRONG CONTEXT ALIGNMENT"
        elif readiness_score >= 70:
            readiness_label = "READY WITH CONDITIONS"
        elif readiness_score >= 50:
            readiness_label = "WATCH"
        elif readiness_score >= 25:
            readiness_label = "DEVELOPING"
        else:
            readiness_label = "NO EDGE"

        return evidence_count, evidence_total, readiness_score, readiness_label

    @staticmethod
    def _decision(
        pressure: Mapping[str, Any],
        entry: Mapping[str, Any],
        setups: Mapping[str, Any],
        quality: Mapping[str, Any],
        continuation: Mapping[str, Any],
        premium: Mapping[str, Any] | None = None,
        selection: Mapping[str, Any] | None = None,
        breadth: Mapping[str, Any] | None = None,
        persistence: Mapping[str, Any] | None = None,
        iv: Mapping[str, Any] | None = None,
        previous_oi: Mapping[str, Any] | None = None,
        underlying: Mapping[str, Any] | None = None,
        status: str = "LIVE",
    ) -> dict[str, Any]:
        prem = premium or {}
        sel = selection or {}
        brd = breadth or {}
        pst = persistence or {}
        iv_dict = iv or {}
        poi = previous_oi or {}
        und = underlying or {}

        # 1. Pressure (0.25)
        press_imb = _number(pressure.get("pressure_imbalance")) or _number(pressure.get("net_edge")) or _number(pressure.get("delta")) or 0.0
        press_norm = round(_clamp(50.0 - press_imb / 2.0), 2)
        p_call = round(0.25 * press_norm, 2)
        p_put = round(0.25 * (100.0 - press_norm), 2)
        
        # 2. Strike activity (0.15)
        poi_available = str(poi.get("status") or "").upper() == "AVAILABLE"
        poi_dir = poi.get("direction") if poi_available else "UNAVAILABLE"
        s_call = 15.0 if poi_dir == "CALL" else 0.0 if poi_dir == "PUT" else 7.5 if poi_dir == "BALANCED" else 0.0
        s_put = 15.0 if poi_dir == "PUT" else 0.0 if poi_dir == "CALL" else 7.5 if poi_dir == "BALANCED" else 0.0

        # 3. Breadth (0.15)
        brd_dir = brd.get("direction", "BALANCED")
        b_call = 15.0 if brd_dir == "CALL" else 0.0 if brd_dir == "PUT" else 7.5
        b_put = 15.0 if brd_dir == "PUT" else 0.0 if brd_dir == "CALL" else 7.5

        # 4. Persistence (0.10)
        pst_dir = pst.get("direction", "BALANCED")
        pst_call = 10.0 if pst_dir == "CALL" else 0.0 if pst_dir == "PUT" else 5.0
        pst_put = 10.0 if pst_dir == "PUT" else 0.0 if pst_dir == "CALL" else 5.0

        # 5. Structure (0.10)
        str_dir = continuation.get("ose_direction", "BALANCED")
        str_call = 10.0 if str_dir == "CALL" else 0.0 if str_dir == "PUT" else 5.0
        str_put = 10.0 if str_dir == "PUT" else 0.0 if str_dir == "CALL" else 5.0

        # 6. Retest (0.10)
        entry_st = entry.get("state", "WAIT")
        ret_dir = str_dir if entry_st in ("RETEST", "ACCEPTANCE", "READY") else "BALANCED"
        ret_call = 10.0 if ret_dir == "CALL" else 0.0 if ret_dir == "PUT" else 5.0
        ret_put = 10.0 if ret_dir == "PUT" else 0.0 if ret_dir == "CALL" else 5.0

        # 7. IV intelligence (0.05)
        iv_dir = iv_dict.get("direction", "BALANCED")
        iv_call = 5.0 if iv_dir == "CALL" else 0.0 if iv_dir == "PUT" else 2.5
        iv_put = 5.0 if iv_dir == "PUT" else 0.0 if iv_dir == "CALL" else 2.5

        # 8. Gamma intelligence (0.05)
        g_call = 0.0
        g_put = 0.0
        
        # 9. Premium behaviour (0.05)
        pr_dir = "UNAVAILABLE"
        pr_call = 0.0
        pr_put = 0.0

        ledger_components = {
            "pressure": {"raw_value": press_imb, "normalized_score": press_norm, "direction": pressure.get("direction", "BALANCED"), "weight": 0.25, "call_contribution": p_call, "put_contribution": p_put, "freshness": und.get("fetched_at"), "availability": "AVAILABLE" if pressure.get("status") == "LIVE" else "UNAVAILABLE", "reason": "Option chain net delta"},
            "strike_activity": {"raw_value": poi.get("call_wall"), "normalized_score": 100.0 if poi_dir == "CALL" else 0.0 if poi_dir == "PUT" else 50.0 if poi_dir == "BALANCED" else None, "direction": poi_dir, "weight": 0.15, "call_contribution": s_call if poi_available else None, "put_contribution": s_put if poi_available else None, "freshness": und.get("receipt_timestamp") or und.get("fetched_at"), "availability": "AVAILABLE" if poi_available else "UNAVAILABLE", "reason": "ATM strike OI shifts" if poi_available else str(poi.get("reason") or "PREVIOUS_OI_DIRECTIONAL_CLASSIFICATION_UNAVAILABLE")},
            "breadth": {"raw_value": brd.get("coverage"), "normalized_score": 100.0 if brd_dir == "CALL" else 0.0 if brd_dir == "PUT" else 50.0, "direction": brd_dir, "weight": 0.15, "call_contribution": b_call, "put_contribution": b_put, "freshness": und.get("fetched_at"), "availability": brd.get("status"), "reason": "Strike participation agreement"},
            "persistence": {"raw_value": pst.get("distinct_confirmation_count"), "normalized_score": 100.0 if pst_dir == "CALL" else 0.0 if pst_dir == "PUT" else 50.0, "direction": pst_dir, "weight": 0.10, "call_contribution": pst_call, "put_contribution": pst_put, "freshness": und.get("fetched_at"), "availability": "AVAILABLE", "reason": "Distinct snapshot confirmations"},
            "structure": {"raw_value": continuation.get("confirmed_state"), "normalized_score": 100.0 if str_dir == "CALL" else 0.0 if str_dir == "PUT" else 50.0, "direction": str_dir, "weight": 0.10, "call_contribution": str_call, "put_contribution": str_put, "freshness": und.get("fetched_at"), "availability": "AVAILABLE", "reason": "OSE trend alignment"},
            "retest": {"raw_value": entry.get("state"), "normalized_score": 100.0 if ret_dir == "CALL" else 0.0 if ret_dir == "PUT" else 50.0, "direction": ret_dir, "weight": 0.10, "call_contribution": ret_call, "put_contribution": ret_put, "freshness": und.get("fetched_at"), "availability": "AVAILABLE", "reason": "Lifecycle retest verification"},
            "iv": {"raw_value": iv_dict.get("skew"), "normalized_score": 100.0 if iv_dir == "CALL" else 0.0 if iv_dir == "PUT" else 50.0, "direction": iv_dir, "weight": 0.05, "call_contribution": iv_call, "put_contribution": iv_put, "freshness": und.get("fetched_at"), "availability": iv_dict.get("status"), "reason": "Implied volatility skew"},
            "gamma": {"raw_value": None, "normalized_score": None, "direction": "UNAVAILABLE", "weight": 0.05, "call_contribution": g_call, "put_contribution": g_put, "freshness": und.get("fetched_at"), "availability": "UNAVAILABLE", "reason": GAMMA_UNAVAILABLE_REASON},
            "premium_behaviour": {"raw_value": None, "normalized_score": None, "direction": pr_dir, "weight": 0.05, "call_contribution": pr_call, "put_contribution": pr_put, "freshness": und.get("fetched_at"), "availability": "UNAVAILABLE", "reason": "PREMIUM_DIRECTIONAL_ATTRIBUTION_UNAVAILABLE"},
        }

        call_pre = round(
            sum(
                contribution
                for component in ledger_components.values()
                if (contribution := _number(component.get("call_contribution")))
                is not None
            ),
            2,
        )
        put_pre = round(
            sum(
                contribution
                for component in ledger_components.values()
                if (contribution := _number(component.get("put_contribution")))
                is not None
            ),
            2,
        )
        norm_denom = round(call_pre + put_pre, 2)
        call_fin = round((call_pre / norm_denom) * 100.0, 2) if norm_denom > 0 else 50.0
        put_fin = round(100.00 - call_fin, 2)
        ledger_edge = round(put_fin - call_fin, 2)

        if abs(ledger_edge) <= PRESSURE_BALANCED_DELTA:
            side = "BALANCED"
        elif ledger_edge < -PRESSURE_BALANCED_DELTA:
            side = "CALL"
        else:
            side = "PUT"

        selected = (
            "HIGH_CONVICTION"
            if setups["HIGH_CONVICTION"]["qualified"]
            else "STANDARD_DIRECTIONAL"
            if setups["STANDARD_DIRECTIONAL"]["qualified"]
            else "NONE"
        )
        gate = (
            "ADVISORY_READY"
            if selected != "NONE"
            and entry.get("state") in {"READY", "RETEST", "ACCEPTANCE"}
            and continuation.get("confirmed_state") != "BALANCED"
            and not entry.get("hard_invalidation")
            and not entry.get("evidence_cancelled")
            else "ADVISORY_WAIT"
        )
        action = (
            f"Observe {side.lower()}-side {entry.get('state', 'context').lower()} conditions; advisory only."
            if side in {"CALL", "PUT"}
            else "Observe balanced participation; no clean tactical edge."
        )
        actionability = (
            100.0
            if gate == "ADVISORY_READY"
            else 0.0
            if selected == "NONE"
            or entry.get("hard_invalidation")
            or entry.get("evidence_cancelled")
            else 50.0
        )
        actionability_status = (
            "ACTIONABLE"
            if actionability == 100.0
            else "CONTEXT_ONLY"
            if actionability == 50.0
            else "NOT_ACTIONABLE"
        )
        finalized_quality = deepcopy(dict(quality))
        finalized_quality["actionability"] = {
            "score": actionability,
            "status": actionability_status,
            "entry_state": entry.get("state"),
            "setup_class": selected,
        }
        data_quality = _number(
            (finalized_quality.get("data_quality") or {}).get("score")
        ) or 0.0
        evidence_agreement = _number(
            (finalized_quality.get("evidence_agreement") or {}).get("score")
        ) or 0.0
        signal_stability = _number(
            (finalized_quality.get("signal_stability") or {}).get("score")
        ) or 0.0
        decision_state = (
            "NO_CLEAN_EDGE"
            if side == "BALANCED"
            else "READY"
            if gate == "ADVISORY_READY"
            else "WAIT"
        )
        if continuation.get("state_change_pending"):
            remaining_snapshots = max(
                0,
                REGIME_CONFIRMATION_SNAPSHOTS
                - int(continuation.get("pending_count") or 0),
            )
            remaining_seconds = max(
                0.0,
                REGIME_CONFIRMATION_SECONDS
                - (_number(continuation.get("pending_seconds")) or 0.0),
            )
            next_trigger = (
                f"Confirm {str(continuation.get('pending_state')).lower()} for "
                f"{remaining_snapshots} snapshots or {remaining_seconds:.1f}s"
            )
        elif side == "BALANCED":
            next_trigger = "Directional pressure must leave the balanced zone"
        elif gate == "ADVISORY_READY":
            next_trigger = "Maintain confirmed agreement and valid entry context"
        else:
            next_trigger = (
                f"Entry lifecycle must advance from "
                f"{str(entry.get('state') or 'context').lower()}"
            )
        why_line = (
            f"{str(pressure.get('state') or 'unavailable').replace('_', ' ').title()}; "
            f"breadth {str((quality.get('evidence_agreement') or {}).get('status') or 'unavailable').replace('_', ' ').lower()}; "
            f"confirmed regime {str(continuation.get('confirmed_state') or 'unavailable').replace('_', ' ').lower()}."
        )

        low, high, is_stretched = ArgusTacticalEdgeEngine._compute_entry_zone(
            side, sel, prem
        )
        current_premium = None
        active_leg = "CE" if side == "CALL" else "PE" if side == "PUT" else None
        if active_leg and prem.get(active_leg) and isinstance(prem.get(active_leg), Mapping):
            current_premium = _number(prem[active_leg].get("premium"))

        timing = ArgusTacticalEdgeEngine._compute_timing_guidance(
            side, gate, entry.get("state", "WAIT"), is_stretched,
            bool(entry.get("hard_invalidation")), bool(entry.get("evidence_cancelled")),
            current_premium, high
        )
        hold = ArgusTacticalEdgeEngine._compute_hold_guidance(
            timing, entry.get("state", "WAIT"), low, high
        )
        invalidation = ArgusTacticalEdgeEngine._compute_invalidation_level(
            side, und.get("ltp"), poi
        )
        rr = ArgusTacticalEdgeEngine._compute_risk_reward(
            side, current_premium, high
        )
        ev_count, ev_total, r_score, r_label = ArgusTacticalEdgeEngine._compute_evidence_and_readiness(
            pressure, brd, pst, continuation, poi, iv_dict,
            prem, entry, sel, is_stretched, status
        )

        return {
            "state": decision_state,
            "banner": continuation.get("state"),
            "raw_banner": continuation.get("raw_state"),
            "market_direction": side,
            "regime_character": continuation.get("confirmed_state"),
            "setup_class": selected,
            "gate": gate,
            "current_action": action,
            "action_enabled": gate == "ADVISORY_READY",
            "side": side,
            "evidence_quality": data_quality,
            "evidence_quality_label": "Data Quality",
            "data_quality": data_quality,
            "evidence_agreement": evidence_agreement,
            "signal_stability": signal_stability,
            "actionability": actionability,
            "next_trigger": next_trigger,
            "why_line": why_line,
            "quality": finalized_quality,
            "win_probability": None,
            "execution_authorization": False,
            "entry_zone_low": low,
            "entry_zone_high": high,
            "timing_guidance": timing,
            "hold_guidance": hold,
            "risk_reward": rr,
            "readiness_score": r_score,
            "readiness_label": r_label,
            "evidence_count": ev_count,
            "evidence_total": ev_total,
            "invalidation_level": invalidation,

            "explainability_ledger": {
                "call_score": call_fin,
                "put_score": put_fin,
                "call_pre_normalization": call_pre,
                "put_pre_normalization": put_pre,
                "call_raw": call_pre,
                "put_raw": put_pre,
                "normalization_denominator": norm_denom,
                "call_final": call_fin,
                "put_final": put_fin,
                "call_normalized": call_fin,
                "put_normalized": put_fin,
                "net_edge": ledger_edge,
                "min_activation_threshold": 10.0,
                "min_winning_margin": 15.0,
                "state_change_hysteresis": "3 consecutive distinct source snapshots required",
                "distinct_confirmation_count": pst.get("distinct_confirmation_count", 1),
                "required_count": 3,
                "last_counted_chain_snapshot_id": pst.get("last_counted_chain_snapshot_id"),
                "bias_direction": side,
                "reason_current_bias": f"Net edge {ledger_edge} pts; breadth {brd.get('call_confirming_strikes', 0)} CE / {brd.get('put_confirming_strikes', 0)} PE strikes",
                "reason_transition": f"Bias maintained as {side} (Delta: {ledger_edge} pts)",
                "reconciliation_equation": f"call_total ({call_fin}) + put_total ({put_fin}) = 100.00; net_edge = put_final - call_final ({ledger_edge} pts)",
                "components": ledger_components,
            },
            "why_winner": sel.get("why_winner"),
            "why_runners_up_lost": sel.get("why_runners_up_lost"),
            "all_candidate_ranks": sel.get("all_candidate_ranks", []),
            "spot_source_timestamp": und.get("fetched_at"),
            "option_chain_source_timestamp": und.get("fetched_at"),
            "pressure_computed_at": pressure.get("pressure_computed_at"),
            "chain_snapshot_id": pressure.get("chain_snapshot_id"),
            "computed_snapshot_id": pressure.get("chain_snapshot_id"),
            "universe_version": (
                f"{und.get('expiry')}_{int(atm)}_V1"
                if (atm := _number(und.get("atm_strike"))) is not None
                else f"{und.get('expiry')}_UNAVAILABLE_V1"
            ),
            "pressure_recomputed": pressure.get("pressure_recomputed", False),
            "chain_row_count": pressure.get("chain_row_count", 0),
            "pressure_status": pressure.get("pressure_status", "PRESSURE UNAVAILABLE"),
            "market_state": "MARKET_CLOSED" if und.get("market_state") in ("CLOSED", "POST_MARKET", "PRE_MARKET") else "STALE" if status in ("STALE", "LOCK") else "LIVE",
            "display_state": "LAST_VERIFIED_SETUP" if und.get("market_state") in ("CLOSED", "POST_MARKET", "PRE_MARKET") else "GUIDANCE_PAUSED" if status in ("STALE", "LOCK") else "NORMAL_DIRECTIVE",
            "last_verified": {
                "source_timestamp": und.get("fetched_at"),
                "directional_bias": side,
                "suggested_contract": (sel.get("CE" if side == "CALL" else "PE" if side == "PUT" else "PE") or {}).get("trading_symbol"),
                "timing_guidance": timing,
                "lifecycle": entry.get("state"),
                "invalidation": invalidation,
                "data_age_seconds": und.get("data_age_seconds"),
            },
        }
    @staticmethod
    def _gamma_unavailable() -> dict[str, Any]:
        return {
            "status": "UNAVAILABLE",
            "gamma": None,
            "pin": None,
            "readiness": "UNAVAILABLE",
            "blast_integrity": "UNAVAILABLE",
            "reason": GAMMA_UNAVAILABLE_REASON,
            "inferred_from_oi": False,
            "normal_trade_gate": False,
            "lifecycle": [
                {"step": "DIRECT_GREEKS", "status": "UNAVAILABLE"},
                {"step": "PIN_CONTEXT", "status": "UNAVAILABLE"},
                {"step": "READINESS", "status": "UNAVAILABLE"},
                {"step": "BLAST_INTEGRITY", "status": "UNAVAILABLE"},
            ],
        }

    @staticmethod
    def _why(
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        persistence: Mapping[str, Any],
        iv: Mapping[str, Any],
        premium: Mapping[str, Any],
        continuation: Mapping[str, Any],
        entry: Mapping[str, Any],
        selection: Mapping[str, Any],
        quality: Mapping[str, Any],
    ) -> dict[str, Any]:
        observed = [
            "DHAN_OPTION_CHAIN_SPOT_AND_CONTRACTS",
            "CURRENT_AND_PREVIOUS_OPEN_INTEREST",
            "PREMIUM_VOLUME_IV_AND_TOP_OF_BOOK",
            "OSE_SELECTED_PAIR_AND_COMPLETED_CANDLE_STATE",
        ]
        derived = [
            f"PRESSURE_{pressure.get('state')}",
            f"BREADTH_{breadth.get('direction')}",
            f"PERSISTENCE_{persistence.get('consecutive_confirmations')}",
            f"CONTINUATION_REVERSAL_{continuation.get('state')}",
            f"ENTRY_{entry.get('state')}",
            f"IV_{iv.get('direction')}",
            f"CONTRACT_SELECTION_{selection.get('status')}",
        ]
        unavailable_details = {
            "GAMMA": GAMMA_UNAVAILABLE_REASON,
            "GAMMA_PIN": GAMMA_UNAVAILABLE_REASON,
            "GAMMA_READINESS": GAMMA_UNAVAILABLE_REASON,
            "DELTA": "AUTHORITATIVE_DIRECT_DELTA_NOT_REPORTED",
            "THETA": "AUTHORITATIVE_DIRECT_THETA_NOT_REPORTED",
            "VEGA": "AUTHORITATIVE_DIRECT_VEGA_NOT_REPORTED",
        }
        if iv.get("direction") == "UNAVAILABLE":
            unavailable_details["IV_DIRECTION"] = (
                "PRIOR_AUTHORITATIVE_IV_SNAPSHOT_UNAVAILABLE"
                if iv.get("status") == "AVAILABLE"
                else str(iv.get("reason") or "AUTHORITATIVE_IV_FIELDS_INCOMPLETE")
            )
        if previous_oi.get("prior_snapshot_available") is not True:
            unavailable_details["OI_MIGRATION_ACCELERATION"] = (
                "PRIOR_AUTHORITATIVE_ARGUS_SNAPSHOT_UNAVAILABLE"
            )
        if pressure.get("spot_confirmation") == "UNAVAILABLE":
            unavailable_details["SPOT_CONFIRMATION"] = (
                "PRIOR_AUTHORITATIVE_SPOT_SNAPSHOT_UNAVAILABLE"
            )
        unavailable = list(unavailable_details)
        reasons = [
            f"{pressure.get('state')} across {breadth.get('sample_size')} strikes",
            f"{breadth.get('direction')} breadth confirms on {max(breadth.get('call_confirming_strikes', 0), breadth.get('put_confirming_strikes', 0))} strikes",
            (
                f"{continuation.get('confirmed_state')} confirmed regime; "
                f"raw {continuation.get('raw_state')} with entry {entry.get('state')}"
            ),
            (
                f"Data quality {(quality.get('data_quality') or {}).get('score')}; "
                f"agreement {(quality.get('evidence_agreement') or {}).get('score')}; "
                f"stability {(quality.get('signal_stability') or {}).get('score')}; "
                f"actionability {(quality.get('actionability') or {}).get('score')}"
            ),
            "Gamma overlay unavailable because authoritative direct Greeks are not reported",
        ]
        return {
            "observed": observed,
            "derived": derived,
            "approximated": [],
            "unavailable": unavailable,
            "unavailable_details": unavailable_details,
            "reason_codes": list(continuation.get("reason_codes") or []) + list(entry.get("reason_codes") or []),
            "reasons": reasons,
            "provenance": {
                "previous_oi": previous_oi.get("previous_day_basis"),
                "session_oi": previous_oi.get("session_delta_basis"),
                "premium": "EXACT_INTRINSIC_EXTRINSIC_DECOMPOSITION",
                "greeks": "NOT_REPORTED",
            },
        }
