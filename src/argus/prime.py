"""ARGUS PRIME: pure composition over one canonical ARGUS/OSE snapshot.

This module performs no provider I/O and has no execution authority.  It
packages the existing Tactical Edge evidence into a concise, explainable
projection while preserving unavailable inputs as unavailable.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from math import exp, isfinite
from typing import Any, Mapping, Sequence


PRIME_SCORE_WEIGHTS = {
    "smart_flow": 0.25,
    "futures_confirmation": 0.10,
    "pressure_to_price": 0.15,
    "wall_outcome": 0.15,
    "reversal": 0.10,
    "gamma_regime": 0.10,
    "gamma_blast": 0.15,
}

BLAST_SCORE_WEIGHTS = {
    "gamma_concentration": 0.25,
    "wall_break": 0.20,
    "smart_flow": 0.20,
    "breadth_persistence": 0.15,
    "premium_convexity": 0.10,
    "expiry_context": 0.10,
}

HERO_ENTER_SCORE = 55.0
HERO_EXIT_SCORE = 40.0
HERO_SWITCH_SCORE = 65.0
HERO_HARD_SWITCH_SCORE = 80.0
HERO_CONFIRMATION_SNAPSHOTS = 3
HERO_CONFIRMATION_SECONDS = 10.0
PCR_STABLE_ONE_MINUTE = 0.01
PCR_STABLE_FIVE_MINUTE = 0.02
PCR_EXTREME_HIGH = 1.5
PCR_EXTREME_LOW = 0.7
PCR_ONE_MINUTE_TOLERANCE_SECONDS = 25.0
PCR_FIVE_MINUTE_TOLERANCE_SECONDS = 45.0
PRIME_FORMULA_VERSION = "ARGUS_PRIME_V3_AUDITABLE"
# Explicit canonical policy: unavailable authoritative components are omitted
# from both score numerator and denominator; the effective denominator is
# published with every projection.  No neutral value is imputed.
PRIME_UNAVAILABLE_COMPONENT_POLICY = "AVAILABLE_COMPONENT_WEIGHT_RENORMALIZATION_V1"
LOAD_WEIGHTS = {
    "oi_concentration": 0.22,
    "gamma_oi_proxy": 0.18,
    "flow_importance": 0.18,
    "spot_proximity": 0.12,
    "liquidity": 0.12,
    "breadth": 0.08,
    "wall_relevance": 0.10,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _side(direction: Any) -> str:
    value = str(direction or "").upper()
    if value in {"CALL", "CE", "BULLISH"}:
        return "CALL"
    if value in {"PUT", "PE", "BEARISH"}:
        return "PUT"
    return "HOLD"


def _leg(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    value = row.get(side.lower())
    if not isinstance(value, Mapping):
        value = row.get(side.upper())
    return value if isinstance(value, Mapping) else {}


class ArgusPrimeProjection:
    """Build the canonical read-only ARGUS PRIME contract."""

    @classmethod
    def unavailable(
        cls, reason: str, *, source_timestamp: Any = None, snapshot_id: Any = None
    ) -> dict[str, Any]:
        return {
            "status": "UNAVAILABLE",
            "freshness": "UNAVAILABLE",
            "direction": "HOLD",
            "argus_prime_score": 0.0,
            "move_state": "QUIET",
            "entry_style": "UNAVAILABLE",
            "action": "HOLD",
            "trigger": None,
            "invalidation": None,
            "recommended_contract": None,
            "hero_state": "HOLD — DATA UNAVAILABLE",
            "tactical_summary": {
                "title": "NO CLEAN SIDE",
                "reasons": [reason],
                "state": "Unavailable",
            },
            "best_strike_stack": {
                "status": "UNAVAILABLE",
                "state": "MIXED STACK",
                "reason": reason,
            },
            "live_pcr": {
                "status": "UNAVAILABLE",
                "freshness": "UNAVAILABLE",
                "oi_pcr": None,
                "change_1m_state": "HISTORY_BUILDING",
                "change_5m_state": "HISTORY_BUILDING",
            },
            "selected_contract_technicals": {
                "status": "UNAVAILABLE",
                "reason": reason,
            },
            "chain_summary": [reason],
            "smart_flow_score": 0.0,
            "futures_confirmation_score": None,
            "pressure_price_state": "UNAVAILABLE",
            "wall_outcome_score": 0.0,
            "reversal_score": 0.0,
            "gamma_regime_score": 0.0,
            "gamma_blast_score": 0.0,
            "why": [reason],
            "full_evidence": {"unavailable": [reason]},
            "source_timestamp": source_timestamp,
            "snapshot_id": snapshot_id,
            "execution_influence": "ZERO",
            "strategy_influence": "ZERO",
            "order_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    @classmethod
    def compose(
        cls,
        *,
        source: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        pressure: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        iv: Mapping[str, Any],
        premium: Mapping[str, Any],
        continuation: Mapping[str, Any],
        entry: Mapping[str, Any],
        selection: Mapping[str, Any],
        quality: Mapping[str, Any],
        ose: Mapping[str, Any],
        snapshot_id: str,
        history: Sequence[Mapping[str, Any]] = (),
        previous_projection: Mapping[str, Any] | None = None,
        contract_technicals: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        underlying = (
            source.get("underlying")
            if isinstance(source.get("underlying"), Mapping)
            else {}
        )
        source_event_time = underlying.get("source_event_time")
        receipt_timestamp = (
            underlying.get("receipt_timestamp") or underlying.get("fetched_at")
        )
        observation_timestamp = receipt_timestamp
        timestamp_semantics = str(
            underlying.get("timestamp_semantics")
            or "LEGACY_RECEIPT_TIME_UNCLASSIFIED"
        )
        raw_direction = _side(
            (selection.get("directional_bias") or pressure.get("direction"))
        )
        smart_flow = cls._smart_flow(pressure, breadth, persistence, raw_direction)
        futures = cls._futures_confirmation(
            source.get("futures"),
            raw_direction,
            option_source_timestamp=underlying.get("fetched_at"),
        )
        pressure_price = cls._pressure_to_price(
            pressure, continuation, entry, raw_direction
        )
        wall = cls._wall_outcome(
            previous_oi, continuation, entry, ose, raw_direction
        )
        gamma = cls._gamma_regime(
            rows, underlying, previous_oi, entry, raw_direction
        )
        blast = cls._gamma_blast(
            gamma=gamma,
            wall=wall,
            smart_flow=smart_flow,
            breadth=breadth,
            persistence=persistence,
            premium=premium,
            underlying=underlying,
            direction=raw_direction,
            pressure_price=pressure_price,
        )
        reversal_score = _clamp(
            max(0.0, -(_number(continuation.get("raw_compass")) or 0.0))
        )

        component_scores = {
            "smart_flow": smart_flow["score"],
            "futures_confirmation": futures["score"],
            "pressure_to_price": pressure_price["score"],
            "wall_outcome": wall["score"],
            "reversal": reversal_score,
            "gamma_regime": gamma["score"],
            "gamma_blast": blast["score"],
        }
        component_status = {
            "smart_flow": smart_flow.get("status", "AVAILABLE"),
            "futures_confirmation": futures.get("status", "UNAVAILABLE"),
            "pressure_to_price": pressure_price.get("status", "AVAILABLE"),
            "wall_outcome": wall.get("status", "AVAILABLE"),
            "reversal": "AVAILABLE",
            "gamma_regime": gamma.get("status", "AVAILABLE"),
            "gamma_blast": blast.get("status", "AVAILABLE"),
        }
        score_breakdown = {
            name: {
                "raw_score": component_scores[name],
                "weight": weight,
                "contribution": (
                    round(component_scores[name] * weight, 2)
                    if component_scores[name] is not None
                    and component_status[name] == "AVAILABLE"
                    else None
                ),
                "availability": component_status[name],
                "scored": (
                    component_scores[name] is not None
                    and component_status[name] == "AVAILABLE"
                ),
                "neutral_imputation": False,
            }
            for name, weight in PRIME_SCORE_WEIGHTS.items()
        }
        available_weight = sum(
            weight
            for name, weight in PRIME_SCORE_WEIGHTS.items()
            if component_scores[name] is not None
            and component_status[name] == "AVAILABLE"
        )
        raw_score = _clamp(
            sum(
                component_scores[name] * weight
                for name, weight in PRIME_SCORE_WEIGHTS.items()
                if component_scores[name] is not None
                and component_status[name] == "AVAILABLE"
            )
            / available_weight
            if available_weight > 0
            else 0.0
        )
        if raw_direction == "HOLD":
            raw_score = min(raw_score, 59.0)
        score_state = cls._smooth_score(
            key="hero",
            raw_score=raw_score,
            source_timestamp=observation_timestamp,
            previous_projection=previous_projection,
        )
        final_score = score_state["display_score"]

        hard_blocks: list[str] = []
        if str(selection.get("status") or "").upper() != "AVAILABLE":
            hard_blocks.append(
                str(selection.get("reason") or "CONTRACT_SELECTION_UNAVAILABLE")
            )
        hard_directional_change = (
            raw_direction in {"CALL", "PUT"}
            and final_score >= HERO_HARD_SWITCH_SCORE
            and str(continuation.get("confirmed_state") or "").upper()
            in {"CONTINUATION", "REVERSAL"}
            and str(entry.get("state") or "").upper()
            in {"READY", "RESUMPTION"}
        )
        stability = cls._stabilize_direction(
            raw_direction=raw_direction,
            raw_score=final_score,
            source_timestamp=observation_timestamp,
            snapshot_id=snapshot_id,
            history=history,
            previous_projection=previous_projection,
            hard_directional_change=hard_directional_change,
        )
        direction = stability["confirmed_direction"]
        recommended = cls._recommended_contract(selection, direction)
        if direction != "HOLD" and not recommended:
            hard_blocks.append("LIQUID_CONTRACT_UNAVAILABLE")

        move_state = cls._move_state(blast, smart_flow, pressure_price)
        entry_style = cls._entry_style(entry, wall, blast)
        action = direction if direction != "HOLD" and not hard_blocks else "HOLD"
        trigger_detail = (
            (source.get("tactical_edge") or {}).get("decision", {}).get("next_trigger")
            if isinstance(source.get("tactical_edge"), Mapping)
            else None
        )
        if trigger_detail is None:
            trigger_detail = cls._trigger(entry, wall, direction)
        invalidation = cls._invalidation(
            underlying, previous_oi, direction, entry
        )
        retest_status = cls._retest_status(entry_style, entry, action)
        trigger = cls._action_text(
            action=action,
            direction=direction,
            entry_style=entry_style,
            entry=entry,
            wall=wall,
            hard_blocks=hard_blocks,
        )
        invalidation_text = cls._invalidation_text(direction, invalidation)
        why = cls._why(
            direction,
            smart_flow,
            futures,
            wall,
            gamma,
            blast,
            hard_blocks,
            stability,
        )
        field_audit = cls._field_audit(rows, source)
        strike_spine = cls._strike_spine(
            rows,
            pressure,
            previous_oi,
            breadth,
            gamma,
            blast,
            source=source,
            underlying=underlying,
            history=history,
            selection=selection,
        )
        live_pcr = cls._live_pcr(
            rows,
            history,
            observation_timestamp,
            source.get("totals") if isinstance(source.get("totals"), Mapping) else {},
            expiry=underlying.get("expiry"),
            underlying=underlying.get("symbol") or "NIFTY",
            snapshot_id=snapshot_id,
        )
        best_strike_stack = cls._best_strike_stack(
            direction=direction,
            recommended=recommended,
            strike_spine=strike_spine,
            history=history,
            underlying=underlying,
            futures=futures,
            entry=entry,
        )
        selected_technicals = cls._selected_contract_technicals(
            direction=direction,
            recommended=recommended,
            contract_technicals=contract_technicals or {},
            wall=wall,
        )
        tactical_summary = cls._tactical_summary(
            direction=direction,
            smart_flow=smart_flow,
            wall=wall,
            blast=blast,
            reversal_score=reversal_score,
            live_pcr=live_pcr,
            best_strike_stack=best_strike_stack,
        )
        chain_summary = cls._chain_summary(
            direction=direction,
            previous_oi=previous_oi,
            best_strike_stack=best_strike_stack,
            live_pcr=live_pcr,
        )
        hero_state = cls._hero_state(
            action=action,
            direction=direction,
            move_state=move_state,
            retest_status=retest_status,
            reversal_score=reversal_score,
            selected_technicals=selected_technicals,
        )
        outcomes = cls._outcome_engines(
            pressure=pressure,
            breadth=breadth,
            persistence=persistence,
            futures=futures,
            futures_source=source.get("futures"),
            wall=wall,
            gamma=gamma,
            blast=blast,
            premium=premium,
            continuation=continuation,
            selection=selection,
            ose=ose,
            source_timestamp=underlying.get("fetched_at"),
            previous_projection=previous_projection,
        )
        action_card = cls._action_card(
            direction=direction,
            entry_style=entry_style,
            trigger=trigger,
            invalidation_text=invalidation_text,
            recommended=recommended,
            selection=selection,
            hard_blocks=hard_blocks,
        )

        market_state = str(underlying.get("market_state") or "").upper()
        freshness = "FRESH" if market_state == "OPEN" else "STALE"
        if freshness != "FRESH":
            action = "HOLD"
            market_closed = market_state in {
                "CLOSED", "POST_MARKET", "PRE_MARKET", "WEEKEND", "HOLIDAY",
            }
            hard_blocks.append(
                "MARKET_CLOSED_LAST_GOOD"
                if market_closed
                else "LIVE_FEED_STALE_ACTION_LOCKED"
            )
            hero_state = (
                "MARKET CLOSED — LAST GOOD SNAPSHOT"
                if market_closed
                else "LIVE FEED STALE — ACTION LOCKED"
            )
            live_pcr["freshness"] = "STALE"
            futures = deepcopy(dict(futures))
            if futures.get("status") == "AVAILABLE":
                futures["status"] = "LAST_GOOD"
                futures["display_state"] = "LAST_GOOD"
                futures["as_of"] = futures.get("source_timestamp")
                futures["reason"] = (
                    "MARKET_CLOSED_LAST_COHERENT_FUTURES_CONFIRMATION"
                    if market_closed
                    else "LIVE_FEED_STALE_LAST_COHERENT_FUTURES_CONFIRMATION"
                )
        reversal_semantics = cls._reversal_semantics(
            score=reversal_score,
            market_state=market_state,
            futures=futures,
            pressure_price=pressure_price,
            continuation=continuation,
            source_timestamp=underlying.get("fetched_at"),
        )
        if isinstance(outcomes.get("reversal"), Mapping):
            outcomes["reversal"] = {
                **dict(outcomes["reversal"]),
                "state": reversal_semantics["label"],
                "semantic": reversal_semantics,
            }
        market_snapshot = (
            source.get("argus_market_snapshot")
            if isinstance(source.get("argus_market_snapshot"), Mapping)
            else {}
        )
        receive_timestamp = market_snapshot.get("fetched_at")
        now_timestamp = datetime.now(timezone.utc).isoformat()
        source_age = cls._age_seconds(source_event_time, now_timestamp)
        receipt_age = cls._age_seconds(receipt_timestamp, now_timestamp)
        available_components = sum(
            component_scores[name] is not None
            and component_status[name] == "AVAILABLE"
            for name in component_status
        )
        display_state = (
            "LIVE"
            if freshness == "FRESH"
            else "LAST_GOOD"
            if market_state in {"CLOSED", "POST_MARKET", "PRE_MARKET", "WEEKEND", "HOLIDAY"}
            else "STALE"
        )
        canonical_presentation = cls._canonical_presentation(
            display_state=display_state,
            direction=direction,
            strike_spine=strike_spine,
            tactical_summary=tactical_summary,
            why=why,
            smart_flow=smart_flow,
            blast=blast,
            wall=wall,
            best_strike_stack=best_strike_stack,
            recommended=recommended,
            snapshot_id=snapshot_id,
            source_event_time=source_event_time,
            receipt_timestamp=receipt_timestamp,
        )

        return {
            "status": "LIVE" if freshness == "FRESH" else "STALE",
            "freshness": freshness,
            "display_state": display_state,
            "market_state": market_state,
            "direction": direction,
            "raw_direction": raw_direction,
            "stability": stability,
            "argus_prime_score": final_score,
            "raw_score": raw_score,
            "smoothed_score": score_state["smoothed_score"],
            "display_score": score_state["display_score"],
            "score_update": score_state["update"],
            "score_weights": dict(PRIME_SCORE_WEIGHTS),
            "effective_weight": round(available_weight, 4),
            "normalization_policy": PRIME_UNAVAILABLE_COMPONENT_POLICY,
            "unavailable_components": sorted(
                name for name in PRIME_SCORE_WEIGHTS
                if not score_breakdown[name]["scored"]
            ),
            "component_scores": component_scores,
            "score_breakdown": score_breakdown,
            "score_formula_version": PRIME_FORMULA_VERSION,
            "evidence_coverage": {
                "available": available_components,
                "total": len(component_status),
                "percentage": round(
                    available_components / max(1, len(component_status)) * 100.0,
                    1,
                ),
            },
            "move_state": move_state,
            "entry_style": entry_style,
            "action": action,
            "trigger": trigger,
            "trigger_detail": trigger_detail,
            "invalidation": invalidation,
            "invalidation_text": invalidation_text,
            "retest_status": retest_status,
            "recommended_contract": recommended,
            "smart_flow_score": smart_flow["score"],
            "futures_confirmation_score": futures["score"],
            "pressure_price_state": pressure_price["state"],
            "wall_outcome_score": wall["score"],
            "reversal_score": reversal_score,
            "reversal_semantics": reversal_semantics,
            "gamma_regime_score": gamma["score"],
            "gamma_blast_score": blast["score"],
            "smart_money_flow": smart_flow,
            "futures_confirmation": futures,
            "pressure_to_price": pressure_price,
            "wall_outcome": wall,
            "gamma_regime": gamma,
            "expiry_gamma_blast": blast,
            "outcome_engines": outcomes,
            "action_card": action_card,
            "strike_spine": strike_spine,
            "hero_state": hero_state,
            "tactical_summary": tactical_summary,
            "best_strike_stack": best_strike_stack,
            "live_pcr": live_pcr,
            "selected_contract_technicals": selected_technicals,
            "chain_summary": chain_summary,
            "canonical_presentation": canonical_presentation,
            "hard_blocks": sorted(set(hard_blocks)),
            "warnings": (
                ["FUTURES_CONFIRMATION_UNAVAILABLE"]
                if futures["status"] == "UNAVAILABLE"
                else []
            ),
            "why": why,
            "full_evidence": {
                "pressure": deepcopy(dict(pressure)),
                "breadth": deepcopy(dict(breadth)),
                "persistence": deepcopy(dict(persistence)),
                "previous_oi": deepcopy(dict(previous_oi)),
                "iv": deepcopy(dict(iv)),
                "premium": deepcopy(dict(premium)),
                "continuation_reversal": deepcopy(dict(continuation)),
                "entry_lifecycle": deepcopy(dict(entry)),
                "quality": deepcopy(dict(quality)),
                "field_audit": field_audit,
                "score_is_probability": False,
                "gamma_is_proxy": True,
                "institutional_identity_confirmed": False,
                "score_breakdown": score_breakdown,
                "displayed_value_lineage": {
                    "outcome_engines": {
                        key: {
                            "raw_score": value.get("raw_score"),
                            "smoothed_score": value.get("smoothed_score"),
                            "display_score": value.get("display_score"),
                            "state": value.get("state"),
                            "components": value.get("components"),
                        }
                        for key, value in outcomes.items()
                        if isinstance(value, Mapping)
                    },
                    "money_flow": deepcopy(dict(smart_flow)),
                    "futures_confirmation": deepcopy(dict(futures)),
                    "wall_outcome": deepcopy(dict(wall)),
                    "gamma_regime": deepcopy(dict(gamma)),
                    "oi_pcr": deepcopy(dict(live_pcr)),
                    "strongest_structural_strike": deepcopy(
                        dict(best_strike_stack)
                    ),
                    "strike_spine": deepcopy(list(strike_spine)),
                    "authorized_best_contract": (
                        deepcopy(dict(recommended))
                        if isinstance(recommended, Mapping)
                        else None
                    ),
                },
            },
            "data_truth": {
                "source": "DHAN_V2_OPTION_CHAIN_PLUS_FULL_MARKET_QUOTE",
                "source_event_time": source_event_time,
                "receipt_timestamp": receipt_timestamp,
                "evaluation_timestamp": pressure.get("pressure_computed_at"),
                "snapshot_timestamp": receipt_timestamp,
                "freshness_timestamp": source_event_time,
                "freshness_basis": (
                    "PROVIDER_EVENT_TIME"
                    if source_event_time is not None
                    else "SOURCE_EVENT_TIME_UNAVAILABLE"
                ),
                "timestamp_semantics": timestamp_semantics,
                "source_timestamp": source_event_time,
                "receive_timestamp": receipt_timestamp,
                "market_quote_receive_timestamp": receive_timestamp,
                "age_seconds": source_age,
                "receipt_age_seconds": receipt_age,
                "freshness_threshold_seconds": 20.0,
                "snapshot_id": snapshot_id,
                "expiry": underlying.get("expiry"),
                "security_id": (
                    recommended.get("security_id")
                    if isinstance(recommended, Mapping)
                    else None
                ),
                "formula_version": PRIME_FORMULA_VERSION,
                "evidence_coverage": round(
                    available_components / max(1, len(component_status)) * 100.0,
                    1,
                ),
                "state": display_state,
            },
            "source_event_time": source_event_time,
            "receipt_timestamp": receipt_timestamp,
            "observation_timestamp": observation_timestamp,
            "snapshot_timestamp": receipt_timestamp,
            "timestamp_semantics": timestamp_semantics,
            "source_timestamp": source_event_time,
            "calculation_timestamp": pressure.get("pressure_computed_at"),
            "snapshot_id": snapshot_id,
            "execution_influence": "ZERO",
            "strategy_influence": "ZERO",
            "order_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    @staticmethod
    def _canonical_presentation(
        *,
        display_state: str,
        direction: str,
        strike_spine: Sequence[Mapping[str, Any]],
        tactical_summary: Mapping[str, Any],
        why: Sequence[Any],
        smart_flow: Mapping[str, Any],
        blast: Mapping[str, Any],
        wall: Mapping[str, Any],
        best_strike_stack: Mapping[str, Any],
        recommended: Mapping[str, Any] | None,
        snapshot_id: str,
        source_event_time: Any,
        receipt_timestamp: Any,
    ) -> dict[str, Any]:
        """Own Oracle/Workspace ARGUS presentation choices in the backend."""

        def strength(row: Mapping[str, Any]) -> float:
            return max(
                _number(_leg(row, "CE").get("load_intensity")) or -1.0,
                _number(_leg(row, "PE").get("load_intensity")) or -1.0,
            )

        def acceleration(row: Mapping[str, Any]) -> float:
            return max(
                abs(_number(_leg(row, "CE").get("oi_acceleration")) or 0.0),
                abs(_number(_leg(row, "PE").get("oi_acceleration")) or 0.0),
            )

        def role(row: Mapping[str, Any], fallback: str) -> str:
            values = []
            if row.get("is_atm") is True:
                values.append("CURRENT ATM")
            if row.get("is_probable_magnet") is True:
                values.append("MAGNET")
            if row.get("is_strongest_pressure") is True:
                values.append("STRONGEST PRESSURE")
            if row.get("is_strongest_gamma") is True:
                values.append("STRONGEST GAMMA")
            values.extend(
                str(value)
                for value in row.get("wall_types") or []
                if value
            )
            return " + ".join(dict.fromkeys(values)) or fallback

        def project(row: Mapping[str, Any] | None, label: str, fallback: str):
            if not isinstance(row, Mapping):
                return None
            ce = _leg(row, "CE")
            pe = _leg(row, "PE")
            return {
                "label": label,
                "strike": _number(row.get("strike")),
                "ce_load": _number(ce.get("load_intensity")),
                "pe_load": _number(pe.get("load_intensity")),
                "flow_state": row.get("breadth") or row.get("move_hint"),
                "structural_role": role(row, fallback),
                "ce_acceleration": _number(ce.get("oi_acceleration")),
                "pe_acceleration": _number(pe.get("oi_acceleration")),
                "ce_flow": (
                    ce.get("probable_flow")
                    if ce.get("flow_state") == "PROBABLE"
                    else None
                ),
                "pe_flow": (
                    pe.get("probable_flow")
                    if pe.get("flow_state") == "PROBABLE"
                    else None
                ),
            }

        rows = [row for row in strike_spine if isinstance(row, Mapping)]
        atm = next((row for row in rows if row.get("is_atm") is True), None)
        atm_strike = _number(atm.get("strike")) if isinstance(atm, Mapping) else None
        lower_rows = [
            row for row in rows
            if atm_strike is not None
            and (_number(row.get("strike")) or float("inf")) < atm_strike
        ]
        upper_rows = [
            row for row in rows
            if atm_strike is not None
            and (_number(row.get("strike")) or float("-inf")) > atm_strike
        ]
        lower = max(lower_rows, key=strength, default=None)
        upper = max(upper_rows, key=strength, default=None)
        highest = max(rows, key=strength, default=None)
        fastest = max(rows, key=acceleration, default=None)
        compact = [
            item for item in (
                project(atm, "ATM", "CURRENT ATM"),
                project(lower, "LOWER", "STRONGEST LOWER"),
                project(upper, "UPPER", "STRONGEST UPPER"),
            )
            if item is not None
        ]
        summary = " · ".join(
            str(value)
            for value in (
                tactical_summary.get("title"),
                tactical_summary.get("state"),
            )
            if value
        )
        best_wall = (
            best_strike_stack.get("wall")
            if isinstance(best_strike_stack.get("wall"), Mapping)
            else {}
        )
        return {
            "state": display_state,
            "verdict": direction if direction in {"CALL", "PUT"} else "NO CLEAN SIDE",
            "producer_revision": PRIME_FORMULA_VERSION,
            "snapshot_id": snapshot_id,
            "source_event_time": source_event_time,
            "observation_timestamp": receipt_timestamp,
            "compact_spine": compact,
            "full_spine": [
                project(
                    row,
                    (
                        f"STRIKE {strike:g}"
                        if (strike := _number(row.get("strike"))) is not None
                        else "STRIKE NOT REPORTED"
                    ),
                    "CHAIN STRIKE",
                )
                for row in rows
            ],
            "highest_load": project(highest, "HIGHEST LOAD", "STRONGEST LOAD"),
            "fastest_acceleration": project(
                fastest, "FASTEST ACCELERATION", "FASTEST ACCELERATION"
            ),
            "best_stack_strike": _number(best_strike_stack.get("strike")),
            "support_strike": None,
            "resistance_strike": None,
            "flow_type": smart_flow.get("label"),
            "gamma_strike": blast.get("wall"),
            "wall_magnet": {
                "wall": wall.get("wall"),
                "magnet": (
                    best_strike_stack.get("strike")
                    if best_wall.get("magnet") is True
                    else None
                ),
            },
            "gamma_blast": blast.get("state"),
            "proposed_contract": (
                recommended.get("trading_symbol") or recommended.get("security_id")
                if display_state == "LIVE" and isinstance(recommended, Mapping)
                else None
            ),
            "canonical_read": summary or None,
            "canonical_why": " ".join(str(item) for item in why if item) or None,
        }

    @staticmethod
    def _smart_flow(
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        direction: str,
    ) -> dict[str, Any]:
        edge = abs(_number(pressure.get("delta")) or 0.0)
        confirming = max(
            int(breadth.get("call_confirming_strikes") or 0),
            int(breadth.get("put_confirming_strikes") or 0),
        )
        sample = max(1, int(breadth.get("sample_size") or 0))
        persist = min(
            1.0, float(persistence.get("distinct_confirmation_count") or 0) / 3.0
        )
        score = _clamp(edge * 2.0 + (confirming / sample) * 30.0 + persist * 20.0)
        if direction == "HOLD":
            state = "QUIET" if edge <= 7 else "BUILDING"
            label = "BALANCED"
        else:
            acceleration = abs(_number(pressure.get("acceleration")) or 0.0)
            state = (
                "FADING"
                if str(pressure.get("source_state")) == "UNCHANGED_SOURCE_SNAPSHOT"
                else "STRONG"
                if score >= 70
                else "BUILDING"
                if score >= 40 or acceleration > 0
                else "QUIET"
            )
            label = "BULLISH" if direction == "CALL" else "BEARISH"
        return {
            "label": label,
            "direction": direction,
            "score": score,
            "state": state,
            "probable_only": True,
            "identity_claim": "PROBABLE FLOW — institutional identity not confirmed",
        }

    @staticmethod
    def _smooth_score(
        *,
        key: str,
        raw_score: float,
        source_timestamp: Any,
        previous_projection: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        previous_prime = (
            previous_projection.get("argus_prime")
            if isinstance(previous_projection, Mapping)
            and isinstance(previous_projection.get("argus_prime"), Mapping)
            else {}
        )
        if key == "hero":
            previous_state = previous_prime
        else:
            previous_state = (
                (previous_prime.get("outcome_engines") or {}).get(key) or {}
                if isinstance(previous_prime.get("outcome_engines"), Mapping)
                else {}
            )
        previous_smoothed = _number(previous_state.get("smoothed_score"))
        previous_displayed = _number(
            previous_state.get("display_score", previous_state.get("score"))
        )
        elapsed = None
        try:
            elapsed = max(
                0.0,
                (
                    datetime.fromisoformat(str(source_timestamp))
                    - datetime.fromisoformat(
                        str(
                            previous_prime.get("observation_timestamp")
                            or previous_prime.get("receipt_timestamp")
                            or previous_prime.get("source_timestamp")
                        )
                    )
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            pass
        if previous_smoothed is None or elapsed is None or elapsed > 30.0:
            smoothed = raw_score
            alpha = 1.0
        else:
            alpha = 1.0 - exp(-max(0.25, elapsed) / 8.0)
            smoothed = previous_smoothed + alpha * (raw_score - previous_smoothed)
        smoothed = round(_clamp(smoothed), 2)
        material = (
            previous_displayed is None
            or abs(smoothed - previous_displayed) >= 2.0
            or abs(raw_score - smoothed) >= 20.0
        )
        displayed = smoothed if material else previous_displayed
        return {
            "raw_score": round(_clamp(raw_score), 2),
            "smoothed_score": smoothed,
            "display_score": round(_clamp(displayed), 2),
            "update": "HARD" if abs(raw_score - smoothed) >= 20.0 else "SOFT" if material else "HELD",
            "alpha": round(alpha, 4),
            "elapsed_seconds": elapsed,
            "material_change_threshold": 2.0,
            "stale_reset_seconds": 30.0,
        }

    @staticmethod
    def _signed_support(value: Any, expected_sign: float) -> float | None:
        number = _number(value)
        if number is None or expected_sign == 0:
            return None
        if abs(number) < 1e-9:
            return 50.0
        return 100.0 if number * expected_sign > 0 else 0.0

    @classmethod
    def _futures_confirmation(
        cls,
        value: Any,
        direction: str,
        *,
        option_source_timestamp: Any = None,
        allow_last_good: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {
                "status": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "score": None,
                "reason": "CANONICAL_NIFTY_FUTURES_SNAPSHOT_NOT_SUPPLIED",
                "source": "ARGUS_CANONICAL_OPTION_CHAIN",
                "repair_status": "NO_SHARED_PRODUCTION_FUTURES_SNAPSHOT",
            }
        if str(value.get("status") or "").upper() != "AVAILABLE":
            return {
                "status": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "score": None,
                "reason": str(value.get("reason") or "FUTURES_QUOTE_UNAVAILABLE"),
                "source": "DHAN_V2_MARKETFEED_QUOTE",
            }
        source_age = _number(value.get("source_age_seconds"))
        if source_age is None or (
            source_age > 20.0 and not allow_last_good
        ):
            return {
                "status": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "score": None,
                "reason": "FUTURES_SOURCE_STALE",
                "source": "DHAN_V2_MARKETFEED_QUOTE",
                "source_age_seconds": source_age,
            }
        timestamp_skew = cls._absolute_time_delta_seconds(
            value.get("source_timestamp"), option_source_timestamp
        )
        if option_source_timestamp is not None and (
            timestamp_skew is None or timestamp_skew > 20.0
        ):
            return {
                "status": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "score": None,
                "reason": "NO_MATCHING_COHERENT_ARGUS_SNAPSHOT",
                "source": "DHAN_V2_MARKETFEED_QUOTE",
                "source_timestamp": value.get("source_timestamp"),
                "option_source_timestamp": option_source_timestamp,
                "timestamp_skew_seconds": timestamp_skew,
                "security_id": value.get("security_id"),
            }
        raw_coverage = sum(
            item is not None
            for item in (
                _number(value.get("price_change")),
                _number(value.get("price_acceleration_per_minute")),
                _number(value.get("quantity_imbalance_percentage")),
                _number(value.get("depth_imbalance_percentage")),
                _number(value.get("basis_change")),
                (
                    (_number(value.get("price_change")), _number(value.get("oi_change")))
                    if _number(value.get("price_change")) is not None
                    and _number(value.get("oi_change")) is not None
                    else None
                ),
            )
        )
        if direction == "HOLD":
            call = cls._futures_confirmation(
                value,
                "CALL",
                option_source_timestamp=option_source_timestamp,
                allow_last_good=allow_last_good,
            )
            put = cls._futures_confirmation(
                value,
                "PUT",
                option_source_timestamp=option_source_timestamp,
                allow_last_good=allow_last_good,
            )
            call_score = _number(call.get("score"))
            put_score = _number(put.get("score"))
            if call_score is None or put_score is None:
                state = "PARTIAL"
            elif call_score >= 67.0 and call_score - put_score >= 15.0:
                state = "BULLISH"
            elif put_score >= 67.0 and put_score - call_score >= 15.0:
                state = "BEARISH"
            else:
                state = "DIVERGENT"
            return {
                "status": "AVAILABLE",
                "state": state,
                "score": None,
                "direction": direction,
                "directional_score": {
                    "CALL": call_score,
                    "PUT": put_score,
                },
                "source_timestamp": value.get("source_timestamp"),
                "source_age_seconds": source_age,
                "timestamp_skew_seconds": timestamp_skew,
                "security_id": value.get("security_id"),
                "symbol": value.get("symbol"),
                "expiry": value.get("expiry"),
                "ltp": value.get("ltp"),
                "oi": value.get("oi"),
                "volume": value.get("volume"),
                "evidence": {},
                "evidence_coverage": raw_coverage,
                "source": "DHAN_V2_MARKETFEED_QUOTE",
                "reason": "LAST_COHERENT_FUTURES_DIRECTIONAL_READ",
            }
        sign = 1.0 if direction == "CALL" else -1.0 if direction == "PUT" else 0.0
        evidence = {
            "price_direction": cls._signed_support(value.get("price_change"), sign),
            "price_acceleration": cls._signed_support(
                value.get("price_acceleration_per_minute"), sign
            ),
            "quantity_imbalance": cls._signed_support(
                value.get("quantity_imbalance_percentage"), sign
            ),
            "depth_imbalance": cls._signed_support(
                value.get("depth_imbalance_percentage"), sign
            ),
            "basis_behavior": cls._signed_support(value.get("basis_change"), sign),
        }
        oi_delta = _number(value.get("oi_change"))
        price_delta = _number(value.get("price_change"))
        if oi_delta is None or price_delta is None or sign == 0:
            evidence["price_oi_structure"] = None
        else:
            # Long buildup and short covering both support the observed price side.
            evidence["price_oi_structure"] = 100.0 if price_delta * sign > 0 else 0.0
        present = [item for item in evidence.values() if item is not None]
        score = round(sum(present) / len(present), 2) if present else None
        if score is None:
            state = "PARTIAL"
        elif score >= 67.0 and len(present) >= 4:
            state = "CONFIRMED"
        elif score >= 45.0:
            state = "PARTIAL"
        else:
            state = "DIVERGENT"
        return {
            "status": "AVAILABLE",
            "state": state,
            "score": score,
            "direction": direction,
            "source_timestamp": value.get("source_timestamp"),
            "source_age_seconds": source_age,
            "timestamp_skew_seconds": timestamp_skew,
            "security_id": value.get("security_id"),
            "symbol": value.get("symbol"),
            "expiry": value.get("expiry"),
            "ltp": value.get("ltp"),
            "oi": value.get("oi"),
            "volume": value.get("volume"),
            "evidence": evidence,
            "evidence_coverage": len(present),
            "source": "DHAN_V2_MARKETFEED_QUOTE",
            "reason": f"{len(present)}/6 futures evidence components available",
        }

    @classmethod
    def _outcome_engines(
        cls,
        *,
        pressure: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        futures: Mapping[str, Any],
        futures_source: Any,
        wall: Mapping[str, Any],
        gamma: Mapping[str, Any],
        blast: Mapping[str, Any],
        premium: Mapping[str, Any],
        continuation: Mapping[str, Any],
        selection: Mapping[str, Any],
        ose: Mapping[str, Any],
        source_timestamp: Any,
        previous_projection: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Seven independent advisory outcomes; scores are evidence, not probability."""

        sample = max(1, int(breadth.get("sample_size") or 0))
        call_breadth = _clamp(
            float(breadth.get("call_confirming_strikes") or 0) / sample * 100.0
        )
        put_breadth = _clamp(
            float(breadth.get("put_confirming_strikes") or 0) / sample * 100.0
        )
        call_pressure = _clamp(_number(pressure.get("call_score")) or 0.0)
        put_pressure = _clamp(_number(pressure.get("put_score")) or 0.0)
        call_futures = cls._futures_confirmation(
            futures_source,
            "CALL",
            option_source_timestamp=source_timestamp,
        )
        put_futures = cls._futures_confirmation(
            futures_source,
            "PUT",
            option_source_timestamp=source_timestamp,
        )
        call_future_score = _number(call_futures.get("score"))
        put_future_score = _number(put_futures.get("score"))
        persistence_score = _clamp(
            float(persistence.get("distinct_confirmation_count") or 0) / 3.0
            * 100.0
        )

        def ose_side(side: str) -> float | None:
            contract = (
                (ose.get("contracts") or {}).get(side) or {}
                if isinstance(ose.get("contracts"), Mapping)
                else {}
            )
            text = str(
                (contract.get("composite") or {}).get("state")
                or (contract.get("composite") or {}).get("label")
                or ""
            ).upper()
            if "BULLISH" in text:
                return 100.0
            if "BEARISH" in text:
                return 0.0
            return 50.0 if text else None

        def optional_score(value: Any) -> float | None:
            score = _number(value)
            return _clamp(score) if score is not None else None

        wall_score = optional_score(wall.get("score"))
        gamma_available = str(gamma.get("status") or "").upper() == "AVAILABLE"
        wall_available = str(wall.get("status") or "AVAILABLE").upper() == "AVAILABLE"

        call_components = {
            "call_pressure": (call_pressure, 0.25),
            "call_breadth": (call_breadth, 0.15),
            "ce_structure": (ose_side("CE"), 0.15),
            "futures": (call_future_score, 0.15),
            "put_writing_proxy": (
                100.0
                if any(
                    "PUT_WRITING" in str(_leg(row, "pe").get("activity"))
                    for row in pressure.get("strikes") or []
                    if isinstance(row, Mapping)
                )
                else put_pressure,
                0.10,
            ),
            "wall_escape": (wall_score if wall_available else None, 0.10),
            "persistence": (persistence_score, 0.10),
        }
        put_components = {
            "put_pressure": (put_pressure, 0.25),
            "put_breadth": (put_breadth, 0.15),
            "pe_structure": (ose_side("PE"), 0.15),
            "futures": (put_future_score, 0.15),
            "call_writing_proxy": (
                100.0
                if any(
                    "CALL_WRITING" in str(_leg(row, "ce").get("activity"))
                    for row in pressure.get("strikes") or []
                    if isinstance(row, Mapping)
                )
                else call_pressure,
                0.10,
            ),
            "wall_escape": (wall_score if wall_available else None, 0.10),
            "persistence": (persistence_score, 0.10),
        }

        def weighted(
            components: Mapping[str, tuple[float | None, float]],
        ) -> float:
            observed = [
                (value, weight)
                for value, weight in components.values()
                if value is not None
            ]
            observed_weight = sum(weight for _, weight in observed)
            if observed_weight <= 0:
                return 0.0
            return _clamp(
                sum(value * weight for value, weight in observed)
                / observed_weight
            )

        call_raw = weighted(call_components)
        put_raw = weighted(put_components)
        conflict = 100.0 - min(100.0, abs(call_raw - put_raw) * 2.5)
        hold_components = {
            "directional_conflict": (conflict, 0.25),
            "low_separation": (100.0 - min(100.0, abs(call_raw - put_raw) * 4.0), 0.20),
            "gamma_pin": (
                100.0 if gamma.get("state") == "PINNING" else 35.0
                if gamma_available else None,
                0.15,
            ),
            "wall_containment": (
                100.0 if wall.get("outcome") == "PIN" else 25.0
                if wall_available else None,
                0.15,
            ),
            "fragmented_breadth": (100.0 - max(call_breadth, put_breadth), 0.10),
            "poor_persistence": (100.0 - persistence_score, 0.10),
            "futures_uncertainty": (
                80.0 if futures.get("state") == "DIVERGENT" else 10.0
                if futures.get("status") == "AVAILABLE" else None,
                0.05,
            ),
        }
        hold_raw = weighted(hold_components)

        theta_values = []
        for contract in (selection.get("all_candidate_ranks") or []):
            if isinstance(contract, Mapping):
                theta = _number(contract.get("theta"))
                if theta is not None:
                    theta_values.append(abs(theta))
        theta_burden = (
            min(100.0, max(theta_values) * 5.0) if theta_values else None
        )
        premium_direction = str(premium.get("direction") or "").upper()
        premium_available = (
            str(premium.get("status") or "").upper() == "AVAILABLE"
            and premium_direction not in {"", "UNAVAILABLE"}
        )
        directive_contract = selection.get("directive_contract")
        spread_pct = (
            _number(directive_contract.get("spread_pct"))
            if isinstance(directive_contract, Mapping)
            else None
        )
        decay_components = {
            "theta_burden": (theta_burden, 0.30),
            "gamma_pin": (
                100.0 if gamma.get("state") == "PINNING" else 25.0
                if gamma_available else None,
                0.20,
            ),
            "premium_non_response": (
                75.0 if premium_direction == "BALANCED" else 25.0
                if premium_available else None,
                0.20,
            ),
            "spread": (
                min(100.0, spread_pct * 20.0)
                if spread_pct is not None else None,
                0.15,
            ),
            "containment": (
                100.0 if wall.get("outcome") == "PIN" else 20.0
                if wall_available else None,
                0.15,
            ),
        }
        decay_raw = weighted(decay_components)
        acceleration = abs(_number(pressure.get("acceleration")) or 0.0)
        big_components = {
            "directional_edge": (max(call_raw, put_raw), 0.25),
            "flow_acceleration": (min(100.0, acceleration * 5.0), 0.15),
            "breadth": (max(call_breadth, put_breadth), 0.15),
            "wall_escape": (wall_score if wall_available else None, 0.15),
            "futures": (
                max(
                    score
                    for score in (call_future_score, put_future_score)
                    if score is not None
                )
                if any(
                    score is not None
                    for score in (call_future_score, put_future_score)
                )
                else None,
                0.15,
            ),
            "persistence": (persistence_score, 0.15),
        }
        big_raw = weighted(big_components)
        reversal_raw = _clamp(
            max(
                0.0,
                -(_number(continuation.get("raw_compass")) or 0.0),
            )
            * 0.55
            + (35.0 if wall.get("outcome") == "REVERSAL_FORMING" else 55.0 if wall.get("outcome") == "REVERSAL_CONFIRMED" else 0.0)
            + (15.0 if str(pressure.get("spot_confirmation")) == "ABSORBED" else 0.0)
        )

        definitions = {
            "call_edge": (call_raw, call_components, "CALL"),
            "put_edge": (put_raw, put_components, "PUT"),
            "hold_edge": (hold_raw, hold_components, "HOLD"),
            "decay_risk": (decay_raw, decay_components, "DECAY"),
            "big_move": (big_raw, big_components, "MOVE"),
            "gamma_blast": (_number(blast.get("score")) or 0.0, blast.get("components") or {}, "GAMMA"),
            "reversal": (reversal_raw, {"canonical_reversal_evidence": reversal_raw}, "REVERSAL"),
        }
        result = {}
        for key, (raw, components, kind) in definitions.items():
            smooth = cls._smooth_score(
                key=key,
                raw_score=raw,
                source_timestamp=source_timestamp,
                previous_projection=previous_projection,
            )
            score = smooth["display_score"]
            if key in {"call_edge", "put_edge", "hold_edge"}:
                state = "STRONG" if score >= 70 else "BUILDING" if score >= 45 else "WEAK"
            elif key == "decay_risk":
                state = "EXTREME" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"
            elif key == "big_move":
                state = (
                    "EXHAUSTING" if blast.get("state") == "EXHAUSTING"
                    else "FIRING" if score >= 85
                    else "TRIGGERED" if score >= 72
                    else "ARMED" if score >= 60
                    else "LOADING" if score >= 38
                    else "SLEEPING"
                )
            elif key == "gamma_blast":
                state = blast.get("state") or "NO_BLAST"
            else:
                state = "CONFIRMED" if score >= 80 else "STRONG" if score >= 60 else "FORMING" if score >= 35 else "WEAK"
            result[key] = {
                **smooth,
                "score": score,
                "state": state,
                "kind": kind,
                "trend": "RISING" if raw > smooth["smoothed_score"] + 1 else "FALLING" if raw < smooth["smoothed_score"] - 1 else "STABLE",
                "persistence": persistence_score,
                "acceleration": acceleration,
                "freshness": "FRESH",
                "components": {
                    name: (
                        {
                            "score": value[0],
                            "weight": value[1],
                            "availability": (
                                "AVAILABLE"
                                if value[0] is not None
                                else "UNAVAILABLE"
                            ),
                            "scored": value[0] is not None,
                        }
                        if isinstance(value, tuple) and len(value) == 2
                        else deepcopy(value)
                    )
                    for name, value in dict(components).items()
                },
                "score_is_probability": False,
            }
        return result

    @staticmethod
    def _stabilize_direction(
        *,
        raw_direction: str,
        raw_score: float,
        source_timestamp: Any,
        snapshot_id: str,
        history: Sequence[Mapping[str, Any]],
        previous_projection: Mapping[str, Any] | None,
        hard_directional_change: bool,
    ) -> dict[str, Any]:
        previous_prime = (
            previous_projection.get("argus_prime")
            if isinstance(previous_projection, Mapping)
            and isinstance(previous_projection.get("argus_prime"), Mapping)
            else {}
        )
        previous_stability = (
            previous_prime.get("stability")
            if isinstance(previous_prime.get("stability"), Mapping)
            else {}
        )
        confirmed = _side(previous_prime.get("direction"))
        if not previous_prime and history:
            confirmed = _side(history[-1].get("prime_direction"))

        candidate = confirmed
        if confirmed == "HOLD":
            candidate = (
                raw_direction
                if raw_direction in {"CALL", "PUT"}
                and raw_score >= HERO_ENTER_SCORE
                else "HOLD"
            )
        elif raw_direction == confirmed and raw_score >= HERO_EXIT_SCORE:
            candidate = confirmed
        elif (
            raw_direction in {"CALL", "PUT"}
            and raw_direction != confirmed
            and raw_score >= HERO_SWITCH_SCORE
        ):
            candidate = raw_direction
        elif raw_direction == "HOLD" or raw_score < HERO_EXIT_SCORE:
            candidate = "HOLD"

        pending_direction = None
        pending_count = 0
        pending_since = None
        pending_seconds = 0.0
        transition = "STABLE"

        if candidate != confirmed:
            previous_pending = previous_stability.get("pending_direction")
            previous_snapshot = previous_stability.get("last_snapshot_id")
            if (
                previous_pending == candidate
                and str(previous_snapshot or "") != str(snapshot_id)
            ):
                pending_count = int(
                    previous_stability.get("pending_count") or 0
                ) + 1
                pending_since = previous_stability.get("pending_since")
            else:
                pending_count = 1
                pending_since = source_timestamp
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
            if hard_directional_change and candidate in {"CALL", "PUT"}:
                confirmed = candidate
                transition = "HARD_EXTREME_CONFIRMATION"
            elif (
                pending_count >= HERO_CONFIRMATION_SNAPSHOTS
                or pending_seconds >= HERO_CONFIRMATION_SECONDS
            ):
                confirmed = candidate
                transition = "HARD_PERSISTENCE_CONFIRMED"
            else:
                pending_direction = candidate
                transition = "SOFT_CHANGE_PENDING"
        if transition.startswith("HARD_"):
            pending_count = 0
            pending_since = None
            pending_seconds = 0.0

        return {
            "confirmed_direction": confirmed,
            "raw_direction": raw_direction,
            "transition": transition,
            "pending_direction": pending_direction,
            "pending_count": pending_count,
            "pending_since": pending_since,
            "pending_seconds": round(pending_seconds, 2),
            "last_snapshot_id": snapshot_id,
            "thresholds": {
                "enter": HERO_ENTER_SCORE,
                "exit": HERO_EXIT_SCORE,
                "opposite_switch": HERO_SWITCH_SCORE,
                "hard_switch": HERO_HARD_SWITCH_SCORE,
                "snapshots": HERO_CONFIRMATION_SNAPSHOTS,
                "seconds": HERO_CONFIRMATION_SECONDS,
            },
        }

    @staticmethod
    def _pressure_to_price(
        pressure: Mapping[str, Any],
        continuation: Mapping[str, Any],
        entry: Mapping[str, Any],
        direction: str,
    ) -> dict[str, Any]:
        edge = abs(_number(pressure.get("delta")) or 0.0)
        spot = str(pressure.get("spot_confirmation") or "UNAVAILABLE").upper()
        expected = "UP" if direction == "CALL" else "DOWN" if direction == "PUT" else None
        response = expected is not None and spot == expected
        raw = str(continuation.get("raw_state") or "").upper()
        entry_state = str(entry.get("state") or "").upper()
        if direction == "HOLD":
            state = "ABSORPTION" if edge > 7 else "LATENT_PRESSURE"
        elif raw == "REVERSAL" or entry_state == "REJECTION":
            state = "REVERSAL_STRENGTHENING"
        elif response and edge >= 18:
            state = "IMPACT_EXPANSION"
        elif not response and edge >= 18:
            state = "ABSORPTION"
        elif str(pressure.get("state") or "").upper() == "FADING":
            state = "EXHAUSTION"
        else:
            state = "MOVE_LOADING"
        score = _clamp(edge * 2.5 + (30.0 if response else 0.0))
        return {
            "state": state,
            "score": score,
            "price_response": spot,
            "pressure_direction": direction,
            "absorbed": state == "ABSORPTION",
        }

    @staticmethod
    def _wall_outcome(
        previous_oi: Mapping[str, Any],
        continuation: Mapping[str, Any],
        entry: Mapping[str, Any],
        ose: Mapping[str, Any],
        direction: str,
    ) -> dict[str, Any]:
        side = "call" if direction == "CALL" else "put" if direction == "PUT" else None
        wall_state = (previous_oi.get("wall_state") or {}).get(side) if side else None
        migration = (previous_oi.get("migration") or {}).get(side) if side else None
        acceleration = (previous_oi.get("acceleration") or {}).get(side) if side else None
        entry_state = str(entry.get("state") or "").upper()
        raw = str(continuation.get("raw_state") or "").upper()
        if direction == "HOLD":
            outcome = "PIN"
        elif entry_state in {"ESCAPE", "RESUMPTION"}:
            outcome = "ESCAPE"
        elif raw == "REVERSAL" and entry_state == "REJECTION":
            outcome = "REVERSAL_CONFIRMED"
        elif raw == "REVERSAL":
            outcome = "REVERSAL_FORMING"
        elif entry_state in {"RETEST", "ACCEPTANCE", "READY"}:
            outcome = "CLEAN_BREAK"
        elif migration == "MIGRATING" and wall_state == "BUILDING":
            outcome = "FALSE_BREAK"
        else:
            outcome = "PIN"
        score = {
            "PIN": 35.0,
            "REVERSAL_FORMING": 55.0,
            "REVERSAL_CONFIRMED": 80.0,
            "FALSE_BREAK": 45.0,
            "CLEAN_BREAK": 80.0,
            "ESCAPE": 90.0,
        }[outcome]
        wall = (
            previous_oi.get("call_wall")
            if direction == "CALL"
            else previous_oi.get("put_wall")
            if direction == "PUT"
            else None
        )
        return {
            "outcome": outcome,
            "score": score,
            "wall": wall,
            "wall_state": wall_state or "BALANCED",
            "migration": migration or "UNAVAILABLE",
            "oi_velocity": acceleration or "UNAVAILABLE",
            "ose_source": ose.get("canonical_digest"),
        }

    @staticmethod
    def _gamma_regime(
        rows: Sequence[Mapping[str, Any]],
        underlying: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        entry: Mapping[str, Any],
        direction: str,
    ) -> dict[str, Any]:
        exposures: list[dict[str, Any]] = []
        for row in rows:
            strike = _number(row.get("strike"))
            for side in ("ce", "pe"):
                leg = _leg(row, side)
                gamma = _number(leg.get("gamma"))
                oi = _number(leg.get("oi"))
                if strike is not None and gamma is not None and gamma > 0 and oi is not None and oi > 0:
                    exposures.append(
                        {
                            "strike": strike,
                            "side": side.upper(),
                            "gamma": gamma,
                            "oi": oi,
                            "proxy_load": gamma * oi,
                        }
                    )
        total = sum(item["proxy_load"] for item in exposures)
        if not exposures or total <= 0:
            return {
                "status": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "score": None,
                "reason": "AUTHORITATIVE_DIRECT_GREEKS_UNAVAILABLE",
                "proxy": True,
                "dealer_ownership_claimed": False,
            }
        strongest = max(exposures, key=lambda item: item["proxy_load"])
        concentration = strongest["proxy_load"] / total
        entry_state = str(entry.get("state") or "").upper()
        if entry_state in {"ESCAPE", "RESUMPTION"} and direction != "HOLD":
            state = "ACCELERATION"
        elif entry_state in {"RETEST", "ACCEPTANCE", "READY"} and direction != "HOLD":
            state = "ESCAPE"
        elif concentration >= 0.22:
            state = "PINNING"
        else:
            state = "MOVE_SUPPRESSED"
        score = _clamp(concentration * 250.0 + (25.0 if state == "ACCELERATION" else 0.0))
        return {
            "status": "AVAILABLE",
            "state": state,
            "technical_state": (
                "DAMPING" if state == "MOVE_SUPPRESSED" else state
            ),
            "trader_explanation": (
                "Gamma conditions are likely slowing or pinning the move."
                if state == "MOVE_SUPPRESSED"
                else None
            ),
            "score": score,
            "proxy": True,
            "method": "DIRECT_DHAN_GAMMA_X_OPEN_INTEREST_CONCENTRATION",
            "dealer_ownership_claimed": False,
            "strongest_strike": strongest["strike"],
            "strongest_side": strongest["side"],
            "concentration_percentage": round(concentration * 100.0, 2),
            "direct_greeks_count": len(exposures),
        }

    @staticmethod
    def _gamma_blast(
        *,
        gamma: Mapping[str, Any],
        wall: Mapping[str, Any],
        smart_flow: Mapping[str, Any],
        breadth: Mapping[str, Any],
        persistence: Mapping[str, Any],
        premium: Mapping[str, Any],
        underlying: Mapping[str, Any],
        direction: str,
        pressure_price: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            expiry = date.fromisoformat(str(underlying.get("expiry")))
            trading_date = date.fromisoformat(str(underlying.get("trading_date")))
            dte = (expiry - trading_date).days
        except (TypeError, ValueError):
            dte = None
        expiry_score = 100.0 if dte == 0 else 60.0 if dte == 1 else 20.0 if dte is not None and dte <= 4 else 0.0
        confirming = max(
            int(breadth.get("call_confirming_strikes") or 0),
            int(breadth.get("put_confirming_strikes") or 0),
        )
        breadth_score = min(100.0, confirming / 5.0 * 70.0 + min(30.0, float(persistence.get("distinct_confirmation_count") or 0) * 10.0))
        gamma_score = _number(gamma.get("score")) or 0.0
        wall_score = _number(wall.get("score")) or 0.0
        flow_score = _number(smart_flow.get("score")) or 0.0
        premium_score = (
            80.0
            if str(pressure_price.get("state")) == "IMPACT_EXPANSION"
            else 55.0
            if str(premium.get("status")) == "AVAILABLE"
            else 0.0
        )
        components = {
            "gamma_concentration": gamma_score,
            "wall_break": wall_score,
            "smart_flow": flow_score,
            "breadth_persistence": breadth_score,
            "premium_convexity": premium_score,
            "expiry_context": expiry_score,
        }
        score = _clamp(
            sum(components[name] * weight for name, weight in BLAST_SCORE_WEIGHTS.items())
        )
        if direction == "HOLD" or dte is None or dte > 1:
            score = min(score, 34.0)
        state = (
            "EXHAUSTING"
            if smart_flow.get("state") == "FADING" and score >= 35
            else "ACTIVE"
            if score >= 85
            else "CONFIRMED"
            if score >= 70
            else "ARMED"
            if score >= 55
            else "LOADING"
            if score >= 35
            else "NO_BLAST"
        )
        return {
            "state": state,
            "score": score,
            "direction": direction,
            "wall": wall.get("wall"),
            "phase": state,
            "dte": dte,
            "expiry_specialist_overlay": True,
            "likely": state in {"ARMED", "CONFIRMED", "ACTIVE"},
            "chase_risk": (
                "HIGH"
                if state in {"ACTIVE", "EXHAUSTING"}
                else "MODERATE"
                if state == "CONFIRMED"
                else "LOW"
            ),
            "components": components,
            "weights": dict(BLAST_SCORE_WEIGHTS),
            "high_oi_alone_sufficient": False,
            "gamma_proxy": True,
        }

    @staticmethod
    def _live_pcr(
        rows: Sequence[Mapping[str, Any]],
        history: Sequence[Mapping[str, Any]],
        source_timestamp: Any,
        totals: Mapping[str, Any],
        *,
        expiry: Any = None,
        underlying: Any = "NIFTY",
        snapshot_id: Any = None,
    ) -> dict[str, Any]:
        reported_call_oi = _number(totals.get("ce_oi"))
        reported_put_oi = _number(totals.get("pe_oi"))
        full_chain = (
            reported_call_oi is not None
            and reported_put_oi is not None
            and reported_call_oi > 0
        )
        call_oi = (
            reported_call_oi
            if full_chain
            else sum(_number(_leg(row, "ce").get("oi")) or 0.0 for row in rows)
        )
        put_oi = (
            reported_put_oi
            if full_chain
            else sum(_number(_leg(row, "pe").get("oi")) or 0.0 for row in rows)
        )
        oi_pcr = round(put_oi / call_oi, 4) if call_oi > 0 else None
        try:
            current_time = datetime.fromisoformat(str(source_timestamp))
        except (TypeError, ValueError):
            current_time = None

        def normalized_observation(
            item: Mapping[str, Any],
        ) -> tuple[datetime, Mapping[str, Any]] | None:
            observation = item.get("pcr_observation")
            candidate = observation if isinstance(observation, Mapping) else item
            if str(candidate.get("expiry") or "") != str(expiry or ""):
                return None
            if str(candidate.get("underlying") or "").upper() != str(
                underlying or ""
            ).upper():
                return None
            if not candidate.get("snapshot_id"):
                return None
            try:
                stamp = datetime.fromisoformat(str(candidate.get("timestamp")))
            except (TypeError, ValueError):
                return None
            prior_call = _number(candidate.get("total_call_oi"))
            prior_put = _number(candidate.get("total_put_oi"))
            prior_pcr = _number(candidate.get("pcr"))
            if (
                prior_call is None
                or prior_call <= 0
                or prior_put is None
                or prior_pcr is None
            ):
                return None
            return stamp, candidate

        def prior(seconds: int, tolerance: float) -> Mapping[str, Any] | None:
            if current_time is None:
                return None
            target = current_time.timestamp() - seconds
            eligible: list[tuple[float, datetime, Mapping[str, Any]]] = []
            seen: set[str] = set()
            for item in history:
                if not isinstance(item, Mapping):
                    continue
                parsed = normalized_observation(item)
                if parsed is None:
                    continue
                stamp, candidate = parsed
                identity = str(candidate.get("snapshot_id"))
                if identity in seen or stamp >= current_time:
                    continue
                seen.add(identity)
                distance = abs(stamp.timestamp() - target)
                if distance <= tolerance:
                    eligible.append((distance, stamp, candidate))
            return (
                min(eligible, key=lambda value: (value[0], -value[1].timestamp()))[2]
                if eligible
                else None
            )

        previous_one = prior(60, PCR_ONE_MINUTE_TOLERANCE_SECONDS)
        previous_five = prior(300, PCR_FIVE_MINUTE_TOLERANCE_SECONDS)
        one_change = (
            round(oi_pcr - float(previous_one["pcr"]), 4)
            if oi_pcr is not None
            and isinstance(previous_one, Mapping)
            and _number(previous_one.get("pcr")) is not None
            else None
        )
        five_change = (
            round(oi_pcr - float(previous_five["pcr"]), 4)
            if oi_pcr is not None
            and isinstance(previous_five, Mapping)
            and _number(previous_five.get("pcr")) is not None
            else None
        )
        movement = five_change if five_change is not None else one_change
        stable_limit = (
            PCR_STABLE_FIVE_MINUTE
            if five_change is not None
            else PCR_STABLE_ONE_MINUTE
        )
        trend = (
            "HISTORY_BUILDING"
            if movement is None
            else "STABLE"
            if abs(movement) < stable_limit
            else "RISING"
            if movement > 0
            else "FALLING"
        )
        extreme = (
            "EXTREME_HIGH"
            if oi_pcr is not None and oi_pcr >= PCR_EXTREME_HIGH
            else "EXTREME_LOW"
            if oi_pcr is not None and oi_pcr <= PCR_EXTREME_LOW
            else "NORMAL"
            if oi_pcr is not None
            else "UNAVAILABLE"
        )
        historical_values = sorted(
            value
            for item in history
            if isinstance(item, Mapping)
            and (parsed := normalized_observation(item)) is not None
            and (value := _number(parsed[1].get("pcr"))) is not None
        )
        percentile = (
            round(
                sum(value <= oi_pcr for value in historical_values)
                / len(historical_values)
                * 100.0,
                1,
            )
            if oi_pcr is not None and len(historical_values) >= 20
            else None
        )
        return {
            "status": "AVAILABLE" if oi_pcr is not None else "UNAVAILABLE",
            "current_state": "AVAILABLE" if oi_pcr is not None else "UNAVAILABLE",
            "oi_pcr": oi_pcr,
            "total_call_oi": call_oi if oi_pcr is not None else None,
            "total_put_oi": put_oi if oi_pcr is not None else None,
            "change_1m": one_change,
            "change_5m": five_change,
            "change_1m_state": (
                "AVAILABLE" if one_change is not None else "HISTORY_BUILDING"
            ),
            "change_5m_state": (
                "AVAILABLE" if five_change is not None else "HISTORY_BUILDING"
            ),
            "session_percentile": percentile,
            "session_percentile_state": (
                "AVAILABLE" if percentile is not None else "HISTORY_INSUFFICIENT"
            ),
            "trend": trend,
            "extreme_state": extreme,
            "warning": (
                "EXTREME / REVERSAL-RISK"
                if extreme in {"EXTREME_HIGH", "EXTREME_LOW"}
                else None
            ),
            "source_timestamp": source_timestamp,
            "expiry": expiry,
            "underlying": underlying,
            "snapshot_id": snapshot_id,
            "source_age_seconds": 0.0,
            "freshness": "FRESH",
            "source": (
                "ARGUS_DHAN_FULL_CHAIN_TOTALS"
                if full_chain
                else "ARGUS_SEVEN_STRIKE_DHAN_OPTION_CHAIN"
            ),
            "formula": "TOTAL_PUT_OI_DIVIDED_BY_TOTAL_CALL_OI",
            "history_formula": (
                "NEAREST_SAME_EXPIRY_COMPLETE_SNAPSHOT_AT_T_MINUS_WINDOW"
            ),
            "history_tolerance_seconds": {
                "1m": PCR_ONE_MINUTE_TOLERANCE_SECONDS,
                "5m": PCR_FIVE_MINUTE_TOLERANCE_SECONDS,
            },
            "classification_thresholds": {
                "stable_1m": PCR_STABLE_ONE_MINUTE,
                "stable_5m": PCR_STABLE_FIVE_MINUTE,
                "extreme_high": PCR_EXTREME_HIGH,
                "extreme_low": PCR_EXTREME_LOW,
            },
            "direction_is_not_trade_signal": True,
        }

    @staticmethod
    def _best_strike_stack(
        *,
        direction: str,
        recommended: Mapping[str, Any] | None,
        strike_spine: Sequence[Mapping[str, Any]],
        history: Sequence[Mapping[str, Any]],
        underlying: Mapping[str, Any],
        futures: Mapping[str, Any] | None = None,
        entry: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        bullish_primary = {"CALL_BUYING", "CALL_SHORT_COVERING"}
        bullish_defence = {"PUT_WRITING", "PUT_LONG_UNWINDING"}
        bearish_primary = {"PUT_BUYING", "PUT_SHORT_COVERING"}
        bearish_defence = {"CALL_WRITING", "CALL_LONG_UNWINDING"}
        rows = [
            item
            for item in strike_spine
            if isinstance(item, Mapping) and _number(item.get("strike")) is not None
        ]
        if not rows:
            return {
                "status": "UNAVAILABLE",
                "state": "STRUCTURE UNAVAILABLE",
                "direction": "HOLD",
                "strike": None,
                "strongest_structural_strike": None,
                "atm_observation": _number(underlying.get("atm_strike")),
                "authorized_contract": False,
                "reason": "STRIKE_SPINE_ROW_UNAVAILABLE",
                "migration": {
                    "state": "SCATTERED",
                    "path": [],
                    "label": "No clean migration",
                },
            }

        def flow_pair(row: Mapping[str, Any], side: str) -> bool:
            ce_flow = str((row.get("CE") or {}).get("probable_flow") or "")
            pe_flow = str((row.get("PE") or {}).get("probable_flow") or "")
            return (
                ce_flow in bullish_primary and pe_flow in bullish_defence
                if side == "CALL"
                else pe_flow in bearish_primary and ce_flow in bearish_defence
            )

        bullish_count = sum(flow_pair(item, "CALL") for item in rows)
        bearish_count = sum(flow_pair(item, "PUT") for item in rows)
        max_acceleration = max(
            (
                abs(_number((item.get("CE") or {}).get("oi_acceleration")) or 0.0)
                + abs(_number((item.get("PE") or {}).get("oi_acceleration")) or 0.0)
                for item in rows
            ),
            default=0.0,
        )
        structural_weights = {
            "paired_directional_flow": 0.30,
            "ce_pe_load": 0.20,
            "oi_acceleration": 0.15,
            "wall_strength": 0.15,
            "breadth": 0.10,
            "pressure_concentration": 0.10,
        }

        def structural_candidate(
            row: Mapping[str, Any], side: str
        ) -> dict[str, Any]:
            primary_key, defence_key = (
                ("CE", "PE") if side == "CALL" else ("PE", "CE")
            )
            primary = row.get(primary_key) or {}
            defence = row.get(defence_key) or {}
            paired = flow_pair(row, side)
            load_score = (
                (_number(primary.get("load_intensity")) or 0.0)
                + (_number(defence.get("load_intensity")) or 0.0)
            ) / 2.0
            acceleration_total = (
                abs(_number(primary.get("oi_acceleration")) or 0.0)
                + abs(_number(defence.get("oi_acceleration")) or 0.0)
            )
            acceleration_score = (
                acceleration_total / max_acceleration * 100.0
                if max_acceleration > 0
                else 0.0
            )
            wall_type = str(row.get("wall_strength") or "")
            wall_score = (
                100.0
                if (side == "CALL" and "SUPPORT" in wall_type)
                or (side == "PUT" and "RESISTANCE" in wall_type)
                else 30.0
                if wall_type in {"", "NONE"}
                else 0.0
            )
            breadth_count = bullish_count if side == "CALL" else bearish_count
            breadth_score = breadth_count / max(1, len(rows)) * 100.0
            pressure_score = (
                (_number(primary.get("pressure_score")) or 0.0)
                + (_number(defence.get("pressure_score")) or 0.0)
            ) / 2.0
            paired_confidence = (
                (
                    (_number(primary.get("flow_confidence")) or 100.0)
                    + (_number(defence.get("flow_confidence")) or 100.0)
                )
                / 2.0
                if paired
                else 0.0
            )
            raw = {
                "paired_directional_flow": paired_confidence,
                "ce_pe_load": load_score,
                "oi_acceleration": acceleration_score,
                "wall_strength": wall_score,
                "breadth": breadth_score,
                "pressure_concentration": pressure_score,
            }
            contributions = {
                key: {
                    "score": round(value, 2),
                    "weight": structural_weights[key],
                    "contribution": round(value * structural_weights[key], 2),
                }
                for key, value in raw.items()
            }
            return {
                "row": row,
                "direction": side,
                "score": round(
                    sum(value["contribution"] for value in contributions.values()),
                    1,
                ),
                "paired": paired,
                "contributions": contributions,
            }

        candidates = [
            structural_candidate(item, side)
            for item in rows
            for side in ("CALL", "PUT")
        ]
        selected = max(
            candidates,
            key=lambda item: (
                item["score"],
                -abs(
                    (_number(item["row"].get("strike")) or 0.0)
                    - (_number(underlying.get("ltp")) or 0.0)
                ),
            ),
        )
        row = selected["row"]
        structural_direction = selected["direction"]
        target_strike = _number(row.get("strike"))
        clean = bool(selected["paired"])
        side = "CE" if structural_direction == "CALL" else "PE"
        opposite = "PE" if side == "CE" else "CE"
        leg = row.get(side) or {}
        opposite_leg = row.get(opposite) or {}
        historical = [
            _number(item.get("best_stack_strike"))
            for item in history
            if isinstance(item, Mapping)
            and item.get("best_stack_direction") == structural_direction
            and _number(item.get("best_stack_strike")) is not None
        ]
        path = [*historical[-2:], target_strike] if target_strike is not None else []
        path = [
            value
            for index, value in enumerate(path)
            if index == 0 or value != path[index - 1]
        ]
        if len(path) >= 2 and all(right > left for left, right in zip(path, path[1:])):
            migration_state = "BULLISH_SHIFT_UP"
            migration_label = "Upward migration visible"
        elif len(path) >= 2 and all(right < left for left, right in zip(path, path[1:])):
            migration_state = "BEARISH_SHIFT_DOWN"
            migration_label = "Downward migration visible"
        else:
            migration_state = "SCATTERED"
            migration_label = "No clean migration"
        migration_score = 100.0 if migration_state != "SCATTERED" else 0.0
        price_response = max(
            _number(leg.get("pressure_score")) or 0.0,
            _number(opposite_leg.get("pressure_score")) or 0.0,
        )
        liquidity_score = max(
            _number(leg.get("liquidity_score")) or 0.0,
            _number(opposite_leg.get("liquidity_score")) or 0.0,
        )
        future_values = futures or {}
        directional_scores = (
            future_values.get("directional_score")
            if isinstance(future_values.get("directional_score"), Mapping)
            else {}
        )
        futures_score = _number(future_values.get("score"))
        if futures_score is None:
            futures_score = _number(directional_scores.get(structural_direction))
        market_open = str(underlying.get("market_state") or "").upper() == "OPEN"
        entry_state = str((entry or {}).get("state") or "").upper()
        live_trigger_score = (
            100.0
            if market_open and entry_state in {"READY", "RETEST", "RESUMPTION", "ACCEPTANCE"}
            else 0.0
        )
        authorized = (
            market_open
            and isinstance(recommended, Mapping)
        )
        authorization_aligned = bool(
            authorized
            and str(recommended.get("side") or "").upper() == side
            and _number(recommended.get("strike")) == target_strike
        )
        readiness_weights = {
            "freshness": 0.20,
            "migration": 0.15,
            "futures_confirmation": 0.15,
            "price_response": 0.15,
            "live_trigger": 0.15,
            "liquidity": 0.10,
            "authorized_contract": 0.10,
        }
        readiness_raw = {
            "freshness": 100.0 if market_open else 0.0,
            "migration": migration_score,
            "futures_confirmation": futures_score or 0.0,
            "price_response": price_response,
            "live_trigger": live_trigger_score,
            "liquidity": liquidity_score,
            "authorized_contract": 100.0 if authorized else 0.0,
        }
        readiness_contributions = {
            key: {
                "score": round(value, 2),
                "weight": readiness_weights[key],
                "contribution": round(value * readiness_weights[key], 2),
            }
            for key, value in readiness_raw.items()
        }
        readiness_score = round(
            sum(value["contribution"] for value in readiness_contributions.values()),
            1,
        )
        readiness_reasons = []
        if not market_open:
            readiness_reasons.append("MARKET_CLOSED_OR_STALE_ACTION_DATA")
        if migration_state == "SCATTERED":
            readiness_reasons.append("NO_CLEAN_OI_MIGRATION")
        if live_trigger_score == 0:
            readiness_reasons.append("NO_LIVE_PRICE_TRIGGER")
        if not authorized:
            readiness_reasons.append("NO_AUTHORIZED_CONTRACT")
        return {
            "status": "AVAILABLE",
            "state": (
                f"{'BULLISH' if structural_direction == 'CALL' else 'BEARISH'} STRUCTURE"
                if clean
                else "MIXED OBSERVATION"
            ),
            "direction": structural_direction,
            "strike": target_strike,
            "strongest_structural_strike": target_strike,
            "atm_observation": _number(underlying.get("atm_strike")),
            "score": selected["score"],
            "structural_strength": {
                "score": selected["score"],
                "formula": "WEIGHTED_SIX_COMPONENT_STRUCTURAL_STACK_V1",
                "contributions": selected["contributions"],
            },
            "trade_readiness": {
                "score": readiness_score,
                "formula": "WEIGHTED_SEVEN_COMPONENT_TRADE_READINESS_V1",
                "contributions": readiness_contributions,
                "reasons": readiness_reasons,
            },
            "authorized_contract": authorized,
            "authorized_contract_detail": (
                deepcopy(dict(recommended)) if authorized else None
            ),
            "authorized_contract_matches_structure": authorization_aligned,
            "authorization_reason": (
                "AUTHORIZED_CURRENT_CONTRACT"
                if authorized
                else "NONE_MARKET_CLOSED_OR_ACTION_LOCKED"
                if not market_open
                else "NO_CONTRACT_PASSED_AUTHORIZATION"
            ),
            "strike_role": "STRONGEST_STRUCTURAL_STRIKE",
            "score_formula": "WEIGHTED_SIX_COMPONENT_STRUCTURAL_STACK_V1",
            "score_contributions": selected["contributions"],
            "primary_flow": (
                {
                    "label": leg.get("probable_flow"),
                    "velocity": leg.get("oi_velocity"),
                    "acceleration": leg.get("oi_acceleration"),
                    "arrow": leg.get("velocity_arrow"),
                    "load": leg.get("load_intensity"),
                    "evidence": leg.get("flow_evidence"),
                }
            ),
            "defence_flow": (
                {
                    "label": opposite_leg.get("probable_flow"),
                    "velocity": opposite_leg.get("oi_velocity"),
                    "acceleration": opposite_leg.get("oi_acceleration"),
                    "arrow": opposite_leg.get("velocity_arrow"),
                    "load": opposite_leg.get("load_intensity"),
                    "evidence": opposite_leg.get("flow_evidence"),
                }
            ),
            "wall": {
                "role": row.get("wall_strength"),
                "condition": row.get("wall_condition"),
                "magnet": bool(row.get("is_probable_magnet")),
            },
            "breadth": {
                "bullish_pairs": bullish_count,
                "bearish_pairs": bearish_count,
                "sample_size": len(rows),
            },
            "interpretation": (
                "STRONG SUPPORT + FRESH UPSIDE POSITIONING"
                if clean and structural_direction == "CALL"
                else "STRONG RESISTANCE + FRESH DOWNSIDE POSITIONING"
                if clean and structural_direction == "PUT"
                else "NO CLEAN STRIKE DOMINANCE"
            ),
            "next_strength": (
                (
                    _number(underlying.get("atm_strike")) or target_strike or 0
                )
                + (50.0 if structural_direction == "CALL" else -50.0)
            ),
            "migration": {
                "state": migration_state,
                "path": path,
                "label": migration_label,
            },
        }

    @staticmethod
    def _selected_contract_technicals(
        *,
        direction: str,
        recommended: Mapping[str, Any] | None,
        contract_technicals: Mapping[str, Any],
        wall: Mapping[str, Any],
    ) -> dict[str, Any]:
        if direction == "HOLD":
            return {
                "status": "UNAVAILABLE",
                "reason": "NO_CONFIRMED_DIRECTION",
                "pullback_state": "WAITING_FOR_5M_PULLBACK",
            }
        side = "CE" if direction == "CALL" else "PE"
        technicals = contract_technicals.get(side)
        if not isinstance(technicals, Mapping):
            return {
                "status": "UNAVAILABLE",
                "reason": "SELECTED_CONTRACT_5M_UNAVAILABLE",
                "pullback_state": "WAITING_FOR_5M_PULLBACK",
            }
        if (
            not isinstance(recommended, Mapping)
            or str(technicals.get("security_id") or "")
            != str(recommended.get("security_id") or "")
        ):
            return {
                "status": "UNAVAILABLE",
                "reason": "SELECTED_CONTRACT_TECHNICAL_ID_MISMATCH",
                "pullback_state": "WAITING_FOR_5M_PULLBACK",
            }
        result = deepcopy(dict(technicals))
        trend = result.get("trend") if isinstance(result.get("trend"), Mapping) else {}
        vob = result.get("vob_3m") if isinstance(result.get("vob_3m"), Mapping) else {}
        premium = _number(result.get("current_premium"))
        spread_pct = _number(recommended.get("spread_pct"))
        spread_width = (
            premium * spread_pct / 100.0
            if premium is not None and spread_pct is not None
            else 0.0
        )
        mutable_trend = deepcopy(dict(trend))
        for zone_name in ("ema_21_zone", "ema_50_zone", "supertrend_zone"):
            zone = mutable_trend.get(zone_name)
            level_name = {
                "ema_21_zone": "ema_21",
                "ema_50_zone": "ema_50",
                "supertrend_zone": "supertrend_value",
            }[zone_name]
            level = _number(mutable_trend.get(level_name))
            if not isinstance(zone, Mapping) or level is None:
                continue
            existing_half = max(
                abs(level - (_number(zone.get("low")) or level)),
                abs((_number(zone.get("high")) or level) - level),
            )
            half_width = max(existing_half, spread_width, 0.10)
            half_width = round((int(half_width / 0.05 + 0.999999)) * 0.05, 2)
            mutable_trend[zone_name] = {
                "low": round(level - half_width, 2),
                "high": round(level + half_width, 2),
            }
        result["trend"] = mutable_trend
        trend = mutable_trend
        result["distances"] = {
            "ema_21": (
                round(premium - float(trend["ema_21"]), 2)
                if premium is not None and _number(trend.get("ema_21")) is not None
                else None
            ),
            "ema_50": (
                round(premium - float(trend["ema_50"]), 2)
                if premium is not None and _number(trend.get("ema_50")) is not None
                else None
            ),
            "supertrend": (
                round(premium - float(trend["supertrend_value"]), 2)
                if premium is not None
                and _number(trend.get("supertrend_value")) is not None
                else None
            ),
        }
        result["invalidation_premium"] = trend.get("supertrend_value")
        result["next_strength_premium"] = (
            vob.get("breakout_trigger")
            if _number(vob.get("breakout_trigger")) is not None
            else None
        )
        result["underlying_strength_level"] = wall.get("wall")
        result["zone_width_formula"] = (
            "MAX(2_TICKS,ATR10_X_0.08,TOP_OF_BOOK_SPREAD)_EACH_SIDE"
        )
        result["zone_width_inputs"] = {
            "tick_size": 0.05,
            "atr_10": trend.get("atr"),
            "spread_pct": spread_pct,
            "spread_absolute": round(spread_width, 4),
        }
        return result

    @staticmethod
    def _reversal_semantics(
        *,
        score: float,
        market_state: str,
        futures: Mapping[str, Any],
        pressure_price: Mapping[str, Any],
        continuation: Mapping[str, Any],
        source_timestamp: Any,
    ) -> dict[str, Any]:
        missing = []
        if _number(continuation.get("raw_compass")) is None:
            missing.append("CONTINUATION_REVERSAL_HISTORY")
        if str(pressure_price.get("status") or "").upper() == "UNAVAILABLE":
            missing.append("LIVE_PRICE_RESPONSE")
        if str(futures.get("status") or "").upper() == "UNAVAILABLE":
            missing.append("FUTURES")
        market_closed = market_state in {"CLOSED", "POST_MARKET", "PRE_MARKET"}
        coverage_total = 3
        coverage_available = coverage_total - len(missing)
        if market_closed:
            return {
                "status": "LAST_GOOD",
                "label": f"LAST GOOD REVERSAL · {score:.0f}",
                "score": score,
                "as_of": source_timestamp,
                "description": (
                    "No reversal detected in the last coherent snapshot."
                    if score == 0
                    else "Last coherent reversal evidence retained."
                ),
                "evidence_coverage": {
                    "available": coverage_available,
                    "total": coverage_total,
                },
                "missing": missing,
            }
        if missing:
            return {
                "status": "NOT_SCORED",
                "label": "REVERSAL NOT SCORED",
                "score": None,
                "as_of": source_timestamp,
                "description": "Required reversal evidence is incomplete.",
                "evidence_coverage": {
                    "available": coverage_available,
                    "total": coverage_total,
                },
                "missing": missing,
            }
        return {
            "status": "AVAILABLE",
            "label": (
                f"NO REVERSAL DETECTED · {score:.0f}"
                if score == 0
                else f"REVERSAL EVIDENCE · {score:.0f}"
            ),
            "score": score,
            "as_of": source_timestamp,
            "description": (
                "Full required evidence coverage."
                if score == 0
                else "Reversal evidence is present."
            ),
            "evidence_coverage": {
                "available": coverage_available,
                "total": coverage_total,
            },
            "missing": [],
        }

    @staticmethod
    def _tactical_summary(
        *,
        direction: str,
        smart_flow: Mapping[str, Any],
        wall: Mapping[str, Any],
        blast: Mapping[str, Any],
        reversal_score: float,
        live_pcr: Mapping[str, Any],
        best_strike_stack: Mapping[str, Any],
    ) -> dict[str, Any]:
        structural_direction = str(
            best_strike_stack.get("direction") or "HOLD"
        ).upper()
        authorized = bool(best_strike_stack.get("authorized_contract"))
        title = (
            f"{'BULLISH' if structural_direction == 'CALL' else 'BEARISH'} "
            f"CHAIN STRUCTURE — {'ENTRY AUTHORIZED' if authorized else 'NO LIVE ENTRY'}"
            if structural_direction in {"CALL", "PUT"}
            and "MIXED" not in str(best_strike_stack.get("state") or "")
            else "NO CLEAN SIDE"
        )
        primary_label = str(
            (best_strike_stack.get("primary_flow") or {}).get("label")
            or "unavailable"
        ).replace("_", " ")
        defence_label = str(
            (best_strike_stack.get("defence_flow") or {}).get("label")
            or "unavailable"
        ).replace("_", " ")
        flow_is_observed = (
            primary_label.lower() != "unavailable"
            and defence_label.lower() != "unavailable"
        )
        reasons = [
            (
                f"Probable flow: {primary_label} + {defence_label} agree"
                if structural_direction in {"CALL", "PUT"} and flow_is_observed
                else "Probable flow: insufficient independent leg evidence"
                if structural_direction in {"CALL", "PUT"}
                else f"Probable flow: {str(smart_flow.get('label') or 'unavailable').replace('_', ' ')}"
            ),
            f"Reversal risk {'low' if reversal_score < 35 else 'elevated'}",
            f"Big move {str(blast.get('state') or 'unavailable').replace('_', ' ').lower()}",
        ]
        if best_strike_stack.get("strike") is not None:
            reasons.append(
                f"{float(best_strike_stack['strike']):,.0f} "
                "is the strongest structural strike"
            )
        readiness = best_strike_stack.get("trade_readiness")
        if isinstance(readiness, Mapping):
            reasons.append(
                f"Trade readiness {float(readiness.get('score') or 0):.0f}/100"
            )
        if live_pcr.get("trend") not in {None, "UNAVAILABLE", "STABLE"}:
            reasons.append(
                f"OI PCR {str(live_pcr.get('trend')).lower()}"
            )
        return {
            "title": title,
            "reasons": reasons[:5],
            "state": (
                "Actionable"
                if authorized
                else "Structure observed · action locked"
                if structural_direction in {"CALL", "PUT"}
                else "Balanced"
            ),
            "directional_posture": structural_direction,
            "trade_authorized": authorized,
        }

    @staticmethod
    def _chain_summary(
        *,
        direction: str,
        previous_oi: Mapping[str, Any],
        best_strike_stack: Mapping[str, Any],
        live_pcr: Mapping[str, Any],
    ) -> list[str]:
        structural_direction = str(
            best_strike_stack.get("direction") or "HOLD"
        ).upper()
        authorized = bool(best_strike_stack.get("authorized_contract"))
        posture = (
            f"Bullish chain posture — {'entry authorized' if authorized else 'action locked'}"
            if structural_direction == "CALL"
            else f"Bearish chain posture — {'entry authorized' if authorized else 'action locked'}"
            if structural_direction == "PUT"
            else "No clean chain edge"
        )
        wall = best_strike_stack.get("strongest_structural_strike")
        breadth = (
            best_strike_stack.get("breadth")
            if isinstance(best_strike_stack.get("breadth"), Mapping)
            else {}
        )
        confirming = (
            breadth.get("bullish_pairs")
            if structural_direction == "CALL"
            else breadth.get("bearish_pairs")
            if structural_direction == "PUT"
            else 0
        )
        concentrated = (
            f"{'Support' if structural_direction == 'CALL' else 'Resistance'} "
            f"concentrated at {float(wall):,.0f}"
            if _number(wall) is not None
            and structural_direction in {"CALL", "PUT"}
            else "Wall concentration mixed"
        )
        migration = (
            (best_strike_stack.get("migration") or {}).get("label")
            if isinstance(best_strike_stack.get("migration"), Mapping)
            else "No clean migration"
        )
        pcr = (
            f"OI PCR {float(live_pcr['oi_pcr']):.2f} · "
            f"{str(live_pcr.get('trend') or 'UNAVAILABLE').lower()}"
            if _number(live_pcr.get("oi_pcr")) is not None
            else "OI PCR unavailable"
        )
        breadth_text = (
            f"CE buying + PE writing breadth {confirming}/{int(breadth.get('sample_size') or 0)}"
            if structural_direction == "CALL"
            else f"PE buying + CE writing breadth {confirming}/{int(breadth.get('sample_size') or 0)}"
            if structural_direction == "PUT"
            else "Directional breadth mixed"
        )
        return [posture, breadth_text, concentrated, str(migration), pcr]

    @staticmethod
    def _hero_state(
        *,
        action: str,
        direction: str,
        move_state: str,
        retest_status: str,
        reversal_score: float,
        selected_technicals: Mapping[str, Any],
    ) -> str:
        pullback = str(selected_technicals.get("pullback_state") or "")
        if action == "CALL":
            if pullback == "PULLBACK_CONFIRMED" or retest_status == "RETEST_CONFIRMED":
                return "BUY CALL"
            return "CALL SIDE BUILDING"
        if action == "PUT":
            if pullback == "PULLBACK_CONFIRMED" or retest_status == "RETEST_CONFIRMED":
                return "BUY PUT"
            return "PUT SIDE BUILDING"
        if reversal_score >= 55:
            return "REVERSAL WATCH"
        if move_state == "ARMED":
            return "BIG MOVE ARMED"
        return "HOLD — BIG MOVE QUIET"

    @staticmethod
    def _recommended_contract(
        selection: Mapping[str, Any], direction: str
    ) -> dict[str, Any] | None:
        if direction == "HOLD":
            return None
        directive = selection.get("directive_contract")
        if isinstance(directive, Mapping):
            return deepcopy(dict(directive))
        side = "CE" if direction == "CALL" else "PE"
        candidates = [
            item
            for item in selection.get("all_candidate_ranks") or []
            if isinstance(item, Mapping)
            and item.get("side") == side
            and item.get("status") == "CANDIDATE"
        ]
        return deepcopy(dict(candidates[0])) if candidates else None

    @staticmethod
    def _move_state(
        blast: Mapping[str, Any],
        smart_flow: Mapping[str, Any],
        pressure_price: Mapping[str, Any],
    ) -> str:
        if blast.get("state") == "EXHAUSTING" or pressure_price.get("state") == "EXHAUSTION":
            return "EXHAUSTING"
        if blast.get("state") in {"ACTIVE", "CONFIRMED"}:
            return "FIRING"
        if blast.get("state") == "ARMED":
            return "ARMED"
        if smart_flow.get("state") in {"BUILDING", "STRONG"}:
            return "LOADING"
        return "QUIET"

    @staticmethod
    def _action_card(
        *,
        direction: str,
        entry_style: str,
        trigger: str,
        invalidation_text: str,
        recommended: Mapping[str, Any] | None,
        selection: Mapping[str, Any],
        hard_blocks: Sequence[str],
    ) -> dict[str, Any]:
        if direction == "HOLD":
            reason = "NO_DIRECTIONAL_EDGE"
        elif hard_blocks:
            reason = str(sorted(set(hard_blocks))[0])
        elif entry_style in {"UNAVAILABLE", "WAITING_FOR_RETEST"}:
            reason = "WAITING_FOR_RETEST"
        elif recommended is None:
            reason = str(selection.get("reason") or "NO_LIQUID_CONTRACT")
        else:
            reason = None
        return {
            "status": "AVAILABLE" if reason is None else "WAIT",
            "reason": reason,
            "entry_style": entry_style if reason is None else reason,
            "trigger": trigger,
            "invalidation": invalidation_text,
            "contract": deepcopy(dict(recommended)) if recommended else None,
            "spread": (
                recommended.get("spread_pct")
                if isinstance(recommended, Mapping)
                else None
            ),
            "liquidity": (
                {
                    "volume": recommended.get("volume"),
                    "oi": recommended.get("oi"),
                }
                if isinstance(recommended, Mapping)
                else None
            ),
        }

    @staticmethod
    def _entry_style(
        entry: Mapping[str, Any], wall: Mapping[str, Any], blast: Mapping[str, Any]
    ) -> str:
        state = str(entry.get("state") or "").upper()
        if blast.get("state") in {"CONFIRMED", "ACTIVE"} and state == "ESCAPE":
            return "EARLY"
        if state in {"RETEST", "ACCEPTANCE", "READY"}:
            return "RETEST"
        if wall.get("outcome") in {"REVERSAL_FORMING", "REVERSAL_CONFIRMED"}:
            return "REVERSAL"
        return "WAITING_FOR_RETEST" if state in {"WAIT", "CONTEXT"} else "UNAVAILABLE"

    @staticmethod
    def _trigger(
        entry: Mapping[str, Any], wall: Mapping[str, Any], direction: str
    ) -> str | None:
        if direction == "HOLD":
            return "Directional pressure and breadth must align"
        if entry.get("state") in {"RETEST", "ACCEPTANCE", "READY"}:
            return f"{direction} retest must hold with persistent breadth"
        if wall.get("wall") is not None:
            return f"Close and hold beyond {wall.get('wall')}"
        return None

    @staticmethod
    def _retest_status(
        entry_style: str, entry: Mapping[str, Any], action: str
    ) -> str:
        if entry_style != "RETEST":
            return "NOT_ACTIVE"
        state = str(entry.get("state") or "").upper()
        if action in {"CALL", "PUT"} and state in {"READY", "RESUMPTION"}:
            return "RETEST_CONFIRMED"
        if state in {"RETEST", "ACCEPTANCE"}:
            return "RETEST_ACTIVE"
        return "WAIT_RETEST"

    @staticmethod
    def _action_text(
        *,
        action: str,
        direction: str,
        entry_style: str,
        entry: Mapping[str, Any],
        wall: Mapping[str, Any],
        hard_blocks: Sequence[str],
    ) -> str:
        if hard_blocks:
            return f"WAIT — {str(sorted(set(hard_blocks))[0]).replace('_', ' ')}"
        if direction == "HOLD":
            return "WAIT — NEED STABLE DIRECTIONAL PRESSURE"
        side = "CE" if direction == "CALL" else "PE"
        level = _number(wall.get("wall"))
        level_text = f"{level:,.0f}" if level is not None else None
        state = str(entry.get("state") or "").upper()
        if entry_style == "RETEST":
            if action == direction and state in {"READY", "RESUMPTION"}:
                relation = "ABOVE" if direction == "CALL" else "BELOW"
                level_clause = (
                    f" {relation} {level_text}" if level_text else ""
                )
                return f"BUY {side}{level_clause} AFTER RETEST HOLD"
            level_clause = f" {level_text}" if level_text else ""
            return f"WAIT — {side} RETEST{level_clause} MUST HOLD"
        if entry_style == "EARLY":
            relation = "ABOVE" if direction == "CALL" else "BELOW"
            level_clause = f" {relation} {level_text}" if level_text else ""
            return f"BUY {side}{level_clause} AFTER 5M HOLD"
        return f"WAIT — {side} STRUCTURE MUST CONFIRM"

    @staticmethod
    def _invalidation_text(direction: str, invalidation: float | None) -> str:
        if invalidation is None or direction == "HOLD":
            return "INVALIDATION NOT REPORTED"
        relation = "BELOW" if direction == "CALL" else "ABOVE"
        return f"INVALID {relation} {invalidation:,.0f}"

    @staticmethod
    def _invalidation(
        underlying: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        direction: str,
        entry: Mapping[str, Any],
    ) -> float | None:
        if direction == "CALL":
            return _number(previous_oi.get("put_wall"))
        if direction == "PUT":
            return _number(previous_oi.get("call_wall"))
        return None

    @staticmethod
    def _why(
        direction: str,
        smart_flow: Mapping[str, Any],
        futures: Mapping[str, Any],
        wall: Mapping[str, Any],
        gamma: Mapping[str, Any],
        blast: Mapping[str, Any],
        hard_blocks: Sequence[str],
        stability: Mapping[str, Any],
    ) -> list[str]:
        reasons = [
            f"Probable flow is {smart_flow.get('label')} at {smart_flow.get('score')}/100.",
            f"Wall outcome is {str(wall.get('outcome')).replace('_', ' ')} at {wall.get('wall') or 'an unreported level'}.",
            (
                f"Gamma proxy is {gamma.get('state')} and expiry blast is {blast.get('state')}."
                if gamma.get("status") == "AVAILABLE"
                else "Direct Gamma evidence is unavailable; blast cannot be confirmed."
            ),
        ]
        if futures.get("status") == "UNAVAILABLE":
            reasons[1] += " Futures confirmation is unavailable and reduces confidence."
        if stability.get("transition") == "SOFT_CHANGE_PENDING":
            reasons[0] = (
                f"Stable {stability.get('confirmed_direction')} retained; "
                f"raw {stability.get('raw_direction')} needs "
                f"{HERO_CONFIRMATION_SNAPSHOTS} snapshots or "
                f"{int(HERO_CONFIRMATION_SECONDS)} seconds."
            )
        if hard_blocks:
            reasons[0] = f"Action held: {', '.join(sorted(set(hard_blocks)))}."
        return reasons[:3]

    @staticmethod
    def _field_audit(
        rows: Sequence[Mapping[str, Any]], source: Mapping[str, Any]
    ) -> dict[str, Any]:
        legs = [
            _leg(row, side)
            for row in rows
            for side in ("ce", "pe")
            if _leg(row, side)
        ]
        fields = {
            "security_id": "USED",
            "ltp": "USED",
            "previous_close": "USED",
            "volume": "USED",
            "oi": "USED",
            "previous_oi": "USED",
            "intraday_change_oi": "USED",
            "iv": "USED",
            "delta": "USED",
            "gamma": "USED_AS_PROXY",
            "theta": "RECEIVED",
            "vega": "RECEIVED",
            "top_bid_price": "USED",
            "top_ask_price": "USED",
            "top_bid_quantity": "USED",
            "top_ask_quantity": "USED",
            "average_price": "RECEIVED",
            "previous_volume": "RECEIVED",
            "intraday_oi_high": "UNAVAILABLE_IN_OPTION_CHAIN",
            "intraday_oi_low": "UNAVAILABLE_IN_OPTION_CHAIN",
            "iv_change": "DERIVED_WHEN_PRIOR_SNAPSHOT_EXISTS",
            "total_buy_quantity": "UNAVAILABLE_IN_OPTION_CHAIN",
            "total_sell_quantity": "UNAVAILABLE_IN_OPTION_CHAIN",
            "last_trade_quantity": "UNAVAILABLE_IN_OPTION_CHAIN",
            "last_trade_time": "UNAVAILABLE_IN_OPTION_CHAIN",
            "five_level_depth": "UNAVAILABLE_IN_OPTION_CHAIN",
            "deeper_depth": "UNAVAILABLE",
            "futures": (
                "RECEIVED" if isinstance(source.get("futures"), Mapping) else "UNAVAILABLE"
            ),
        }
        option_depth = (
            source.get("option_market_depth")
            if isinstance(source.get("option_market_depth"), Mapping)
            else {}
        )
        if option_depth:
            fields.update(
                {
                    "intraday_oi_high": "RECEIVED_FULL_QUOTE",
                    "intraday_oi_low": "RECEIVED_FULL_QUOTE",
                    "total_buy_quantity": "USED_FULL_QUOTE",
                    "total_sell_quantity": "USED_FULL_QUOTE",
                    "last_trade_quantity": "RECEIVED_FULL_QUOTE",
                    "last_trade_time": "USED_FULL_QUOTE",
                    "five_level_depth": "USED_FULL_QUOTE",
                }
            )
        for field, status in list(fields.items()):
            if field != "futures" and status in {"USED", "USED_AS_PROXY", "RECEIVED"} and not any(
                leg.get(field) is not None for leg in legs
            ):
                fields[field] = "UNAVAILABLE"
        return {
            "fields": fields,
            "received": sorted(k for k, v in fields.items() if v in {"USED", "USED_AS_PROXY", "RECEIVED", "RECEIVED_FULL_QUOTE", "USED_FULL_QUOTE"}),
            "used": sorted(k for k, v in fields.items() if v in {"USED", "USED_AS_PROXY", "USED_FULL_QUOTE"}),
            "ignored": sorted(k for k, v in fields.items() if v == "RECEIVED"),
            "unavailable": sorted(k for k, v in fields.items() if v.startswith("UNAVAILABLE")),
        }

    @staticmethod
    def _difference(left: Any, right: Any) -> float | None:
        a = _number(left)
        b = _number(right)
        return round(a - b, 3) if a is not None and b is not None else None

    @staticmethod
    def _age_seconds(source: Any, received: Any) -> float | None:
        try:
            return round(
                max(
                    0.0,
                    (
                        datetime.fromisoformat(str(received))
                        - datetime.fromisoformat(str(source))
                    ).total_seconds(),
                ),
                3,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _absolute_time_delta_seconds(left: Any, right: Any) -> float | None:
        if left is None or right is None:
            return None
        try:
            return round(
                abs(
                    (
                        datetime.fromisoformat(str(left))
                        - datetime.fromisoformat(str(right))
                    ).total_seconds()
                ),
                3,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _oi_velocity(current: Any, previous: Any, seconds: float) -> float | None:
        delta = ArgusPrimeProjection._difference(current, previous)
        return round(delta * 60.0 / seconds, 2) if delta is not None and seconds > 0 else None

    @staticmethod
    def _oi_acceleration(
        current_velocity: Any, previous_velocity: Any, seconds: float
    ) -> float | None:
        delta = ArgusPrimeProjection._difference(
            current_velocity, previous_velocity
        )
        return (
            round(delta * 60.0 / seconds, 2)
            if delta is not None and seconds > 0
            else None
        )

    @staticmethod
    def _probable_flow(
        leg: Mapping[str, Any],
        depth: Mapping[str, Any],
        *,
        source_timestamp: Any,
        allow_last_good: bool = False,
    ) -> dict[str, Any]:
        quadrant = str(leg.get("activity") or leg.get("positioning") or "").upper()
        valid = {
            "CALL_BUYING",
            "CALL_SHORT_COVERING",
            "CALL_WRITING",
            "CALL_LONG_UNWINDING",
            "PUT_BUYING",
            "PUT_SHORT_COVERING",
            "PUT_WRITING",
            "PUT_LONG_UNWINDING",
        }
        if quadrant not in valid:
            return {
                "label": "UNAVAILABLE",
                "state": "UNAVAILABLE",
                "confidence": 0.0,
                "reasons": ["PRICE_OI_QUADRANT_UNAVAILABLE"],
            }
        age = ArgusPrimeProjection._age_seconds(
            depth.get("source_timestamp"), depth.get("fetched_at")
        )
        source_skew = ArgusPrimeProjection._absolute_time_delta_seconds(
            depth.get("source_timestamp"), source_timestamp
        )
        if age is not None and age > 20.0 and not allow_last_good:
            return {
                "label": "STALE",
                "state": "STALE",
                "confidence": 0.0,
                "reasons": ["OPTION_DEPTH_SOURCE_STALE"],
            }
        if source_skew is not None and source_skew > 20.0:
            return {
                "label": "INTERNALLY_INCONSISTENT",
                "state": "INCONSISTENT",
                "confidence": 0.0,
                "reasons": ["OPTION_CHAIN_DEPTH_TIMESTAMP_MISMATCH"],
            }
        depth_imbalance = _number(depth.get("depth_imbalance_percentage"))
        buying_quadrant = "BUYING" in quadrant or "SHORT_COVERING" in quadrant
        aggressor_agrees = (
            depth_imbalance is not None
            and abs(depth_imbalance) >= 5.0
            and (
                (buying_quadrant and depth_imbalance > 0)
                or (not buying_quadrant and depth_imbalance < 0)
            )
        )
        depth_conflict = (
            depth_imbalance is not None
            and abs(depth_imbalance) >= 25.0
            and ((buying_quadrant and depth_imbalance < 0) or (
                not buying_quadrant and depth_imbalance > 0
            ))
        )
        oi_change = (
            leg.get("oi_change")
            if leg.get("oi_change") is not None
            else leg.get("intraday_change_oi")
        )
        if oi_change is None:
            oi_change = ArgusPrimeProjection._difference(
                leg.get("oi"), leg.get("previous_oi")
            )
        previous_volume = (
            depth.get("previous_volume")
            if depth.get("previous_volume") is not None
            else leg.get("previous_volume")
        )
        evidence = {
            "premium_change": leg.get("price_change"),
            "oi_change": oi_change,
            "incremental_volume": (
                ArgusPrimeProjection._difference(
                    leg.get("volume"), previous_volume
                )
                if previous_volume is not None
                else None
            ),
            "bid_ask_aggressor_proxy": depth_imbalance,
            "five_level_depth_agreement": aggressor_agrees,
            "best_bid_quantity": (
                depth.get("top_bid_quantity")
                if depth.get("top_bid_quantity") is not None
                else leg.get("top_bid_quantity")
            ),
            "best_ask_quantity": (
                depth.get("top_ask_quantity")
                if depth.get("top_ask_quantity") is not None
                else leg.get("top_ask_quantity")
            ),
            "atp": (
                depth.get("average_price")
                if depth.get("average_price") is not None
                else leg.get("average_price")
            ),
            "underlying_direction": "NOT_SUPPLIED_TO_ROW_CLASSIFIER",
            "futures_agreement": "NOT_SUPPLIED_TO_ROW_CLASSIFIER",
            "persistence": "AVAILABLE_IN_CHAIN_AGGREGATE",
            "timestamp_skew_seconds": source_skew,
        }
        coverage_fields = (
            "premium_change",
            "oi_change",
            "incremental_volume",
            "bid_ask_aggressor_proxy",
            "atp",
            "timestamp_skew_seconds",
        )
        available = sum(evidence[field] is not None for field in coverage_fields)
        confidence = round(available / len(coverage_fields) * 100.0, 1)
        if depth_conflict:
            return {
                "label": "MIXED_CONTRADICTORY",
                "state": "CONTRADICTORY",
                "confidence": min(confidence, 49.0),
                "quadrant": quadrant,
                "evidence": evidence,
                "evidence_coverage": {
                    "available": available,
                    "total": len(coverage_fields),
                },
                "reasons": ["PRICE_OI_QUADRANT_CONFLICTS_WITH_DEPTH"],
            }
        weak_aggressor = depth_imbalance is None or abs(depth_imbalance) < 5.0
        opposed_aggressor = (
            depth_imbalance is not None
            and abs(depth_imbalance) >= 5.0
            and not aggressor_agrees
        )
        state = (
            "LOW_CONFIDENCE"
            if weak_aggressor
            else "PARTIAL"
            if opposed_aggressor
            else "PROBABLE"
        )
        if weak_aggressor:
            confidence = min(confidence, 49.0)
        elif opposed_aggressor:
            confidence = min(confidence, 59.0)
        return {
            "label": quadrant,
            "state": state,
            "confidence": confidence,
            "quadrant": quadrant,
            "evidence": evidence,
            "evidence_coverage": {
                "available": available,
                "total": len(coverage_fields),
            },
            "reasons": [
                "PROBABLE_FLOW_NOT_INSTITUTIONAL_IDENTITY",
                (
                    "AGGRESSOR_PROXY_SUPPORTS_QUADRANT"
                    if aggressor_agrees
                    else "AGGRESSOR_PROXY_WEAK_OR_OPPOSED"
                ),
                (
                    "INCREMENTAL_VOLUME_AVAILABLE"
                    if depth.get("previous_volume") is not None
                    else "INCREMENTAL_VOLUME_HISTORY_UNAVAILABLE"
                ),
            ],
        }

    @staticmethod
    def _liquidity_score(leg: Mapping[str, Any]) -> float:
        bid = _number(leg.get("bid_price") or leg.get("top_bid_price"))
        ask = _number(leg.get("ask_price") or leg.get("top_ask_price"))
        mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
        spread_pct = (
            (ask - bid) / mid * 100.0
            if mid is not None and mid > 0 and ask >= bid
            else None
        )
        spread_score = (
            max(0.0, 100.0 - spread_pct * 20.0)
            if spread_pct is not None
            else 0.0
        )
        volume_score = min(100.0, (_number(leg.get("volume")) or 0.0) / 5_000.0)
        return round(spread_score * 0.7 + volume_score * 0.3, 2)

    @staticmethod
    def _load_breakdown(
        leg: Mapping[str, Any],
        *,
        max_oi: float,
        max_gamma_oi: float,
        spot_distance: float,
        strike_step: float,
        flow_confidence: float,
        breadth_match: bool,
        wall_relevant: bool,
    ) -> dict[str, Any]:
        oi = _number(leg.get("oi")) or 0.0
        gamma_oi = (_number(leg.get("gamma")) or 0.0) * oi
        liquidity = ArgusPrimeProjection._liquidity_score(leg)
        components = {
            "oi_concentration": _clamp(oi / max_oi * 100.0) if max_oi else 0.0,
            "gamma_oi_proxy": (
                _clamp(gamma_oi / max_gamma_oi * 100.0) if max_gamma_oi else 0.0
            ),
            "flow_importance": _clamp(flow_confidence),
            "spot_proximity": _clamp(
                max(0.0, 100.0 - spot_distance / max(strike_step, 1.0) * 20.0)
            ),
            "liquidity": liquidity,
            "breadth": 100.0 if breadth_match else 35.0,
            "wall_relevance": 100.0 if wall_relevant else 20.0,
        }
        contributions = {
            name: round(components[name] * weight, 2)
            for name, weight in LOAD_WEIGHTS.items()
        }
        return {
            "score": round(sum(contributions.values()), 2),
            "components": components,
            "weights": dict(LOAD_WEIGHTS),
            "contributions": contributions,
            "formula": "WEIGHTED_STRUCTURAL_LOAD_V1",
            "raw_oi_is_not_load": True,
        }

    @staticmethod
    def _velocity_arrow(value: Any) -> str:
        number = _number(value)
        if number is None:
            return "→"
        if number >= 5_000:
            return "↑↑"
        if number > 250:
            return "↑"
        if number <= -5_000:
            return "↓↓"
        if number < -250:
            return "↓"
        return "→"

    @staticmethod
    def _strike_spine(
        rows: Sequence[Mapping[str, Any]],
        pressure: Mapping[str, Any],
        previous_oi: Mapping[str, Any],
        breadth: Mapping[str, Any],
        gamma: Mapping[str, Any],
        blast: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
        underlying: Mapping[str, Any],
        history: Sequence[Mapping[str, Any]],
        selection: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        pressure_rows = {
            _number(item.get("strike")): item
            for item in pressure.get("strikes") or []
            if isinstance(item, Mapping)
        }
        call_wall = _number(previous_oi.get("call_wall"))
        put_wall = _number(previous_oi.get("put_wall"))
        result = []
        strongest_gamma = _number(gamma.get("strongest_strike"))
        strongest_pressure = None
        if pressure_rows:
            strongest_pressure = max(
                pressure_rows,
                key=lambda strike: max(
                    _number((pressure_rows[strike].get("CE") or {}).get("score"))
                    or 0.0,
                    _number((pressure_rows[strike].get("PE") or {}).get("score"))
                    or 0.0,
                ),
            )
        direction = _side(pressure.get("direction"))
        previous_record = history[-1] if history else {}
        previous_rows = {
            _number(item.get("strike")): item
            for item in previous_record.get("prime_strike_state") or []
            if isinstance(item, Mapping)
        }
        try:
            elapsed = max(
                0.0,
                (
                    datetime.fromisoformat(str(underlying.get("fetched_at")))
                    - datetime.fromisoformat(str(previous_record.get("source_timestamp")))
                ).total_seconds(),
            )
        except (TypeError, ValueError):
            elapsed = 0.0
        depth_by_security = (
            source.get("option_market_depth")
            if isinstance(source.get("option_market_depth"), Mapping)
            else {}
        )
        gamma_oi_values = [
            (_number(_leg(row, side).get("gamma")) or 0.0)
            * (_number(_leg(row, side).get("oi")) or 0.0)
            for row in rows
            for side in ("ce", "pe")
        ]
        oi_values = [
            _number(_leg(row, side).get("oi")) or 0.0
            for row in rows
            for side in ("ce", "pe")
        ]
        max_gamma_oi = max(gamma_oi_values, default=0.0)
        max_oi = max(oi_values, default=0.0)
        ordered_strikes = sorted(
            value
            for row in rows
            if (value := _number(row.get("strike"))) is not None
        )
        strike_step = min(
            (
                right - left
                for left, right in zip(ordered_strikes, ordered_strikes[1:])
                if right > left
            ),
            default=50.0,
        )
        spot = _number(underlying.get("ltp")) or _number(underlying.get("spot"))
        selected_ids = {
            str(item.get("security_id"))
            for item in (selection.get("all_candidate_ranks") or [])
            if isinstance(item, Mapping) and item.get("status") == "CANDIDATE"
        }
        for row in rows:
            strike = _number(row.get("strike"))
            if strike is None:
                continue
            computed = pressure_rows.get(strike) or {}
            ce = _leg(row, "ce")
            pe = _leg(row, "pe")
            prior = previous_rows.get(strike) or {}
            ce_depth = deepcopy(
                dict(depth_by_security.get(str(ce.get("security_id"))) or {})
            )
            pe_depth = deepcopy(
                dict(depth_by_security.get(str(pe.get("security_id"))) or {})
            )
            ce_flow = ArgusPrimeProjection._probable_flow(
                ce, ce_depth, source_timestamp=underlying.get("fetched_at")
            )
            pe_flow = ArgusPrimeProjection._probable_flow(
                pe, pe_depth, source_timestamp=underlying.get("fetched_at")
            )
            leg_timestamp_skew = ArgusPrimeProjection._absolute_time_delta_seconds(
                ce_depth.get("source_timestamp"),
                pe_depth.get("source_timestamp"),
            )
            if (
                ce_depth
                and pe_depth
                and (leg_timestamp_skew is None or leg_timestamp_skew > 20.0)
            ):
                inconsistent = {
                    "label": "INTERNALLY_INCONSISTENT",
                    "state": "INCONSISTENT",
                    "confidence": 0.0,
                    "reasons": ["CE_PE_SOURCE_TIMESTAMP_MISMATCH"],
                    "evidence": {
                        "timestamp_skew_seconds": leg_timestamp_skew
                    },
                    "evidence_coverage": {"available": 0, "total": 1},
                }
                ce_flow = inconsistent
                pe_flow = inconsistent
            ce_velocity = ArgusPrimeProjection._oi_velocity(
                ce.get("oi"), (prior.get("CE") or {}).get("oi"), elapsed
            )
            pe_velocity = ArgusPrimeProjection._oi_velocity(
                pe.get("oi"), (prior.get("PE") or {}).get("oi"), elapsed
            )
            ce_acceleration = ArgusPrimeProjection._oi_acceleration(
                ce_velocity, (prior.get("CE") or {}).get("oi_velocity"), elapsed
            )
            pe_acceleration = ArgusPrimeProjection._oi_acceleration(
                pe_velocity, (prior.get("PE") or {}).get("oi_velocity"), elapsed
            )
            wall_types = []
            if strike == put_wall:
                wall_types.append("SUPPORT")
            if strike == call_wall:
                wall_types.append("RESISTANCE")
            breadth_direction = str(breadth.get("direction") or "").upper()
            ce_load = ArgusPrimeProjection._load_breakdown(
                ce,
                max_oi=max_oi,
                max_gamma_oi=max_gamma_oi,
                spot_distance=abs(strike - spot) if spot is not None else strike_step * 5,
                strike_step=strike_step,
                flow_confidence=_number(ce_flow.get("confidence")) or 0.0,
                breadth_match=breadth_direction in {"CALL", "BULLISH"},
                wall_relevant=strike in {call_wall, put_wall},
            )
            pe_load = ArgusPrimeProjection._load_breakdown(
                pe,
                max_oi=max_oi,
                max_gamma_oi=max_gamma_oi,
                spot_distance=abs(strike - spot) if spot is not None else strike_step * 5,
                strike_step=strike_step,
                flow_confidence=_number(pe_flow.get("confidence")) or 0.0,
                breadth_match=breadth_direction in {"PUT", "BEARISH"},
                wall_relevant=strike in {call_wall, put_wall},
            )
            result.append(
                {
                    "strike": strike,
                    "CE": {
                        "probable_flow": ce_flow["label"],
                        "flow_state": ce_flow["state"],
                        "flow_confidence": ce_flow["confidence"],
                        "flow_reasons": ce_flow["reasons"],
                        "flow_evidence": ce_flow.get("evidence"),
                        "flow_evidence_coverage": ce_flow.get(
                            "evidence_coverage"
                        ),
                        "flow_quadrant": ce_flow.get("quadrant"),
                        "oi": ce.get("oi"),
                        "oi_velocity": ce_velocity,
                        "oi_acceleration": ce_acceleration,
                        "oi_velocity_unit": "OI_PER_MINUTE",
                        "oi_acceleration_unit": "OI_PER_MINUTE_SQUARED",
                        "covering_unwind": (
                            ce.get("positioning")
                            if "COVER" in str(ce.get("positioning"))
                            or "UNWIND" in str(ce.get("positioning"))
                            else "NONE"
                        ),
                        "gamma_load": (
                            (_number(ce.get("gamma")) or 0.0)
                            * (_number(ce.get("oi")) or 0.0)
                        ),
                        "load_intensity": ce_load["score"],
                        "load_breakdown": ce_load,
                        "liquidity_score": ce_load["components"]["liquidity"],
                        "velocity_arrow": ArgusPrimeProjection._velocity_arrow(
                            ce_velocity
                        ),
                        "depth": ce_depth,
                        "pressure_score": ((computed.get("CE") or {}).get("score")),
                    },
                    "PE": {
                        "probable_flow": pe_flow["label"],
                        "flow_state": pe_flow["state"],
                        "flow_confidence": pe_flow["confidence"],
                        "flow_reasons": pe_flow["reasons"],
                        "flow_evidence": pe_flow.get("evidence"),
                        "flow_evidence_coverage": pe_flow.get(
                            "evidence_coverage"
                        ),
                        "flow_quadrant": pe_flow.get("quadrant"),
                        "oi": pe.get("oi"),
                        "oi_velocity": pe_velocity,
                        "oi_acceleration": pe_acceleration,
                        "oi_velocity_unit": "OI_PER_MINUTE",
                        "oi_acceleration_unit": "OI_PER_MINUTE_SQUARED",
                        "covering_unwind": (
                            pe.get("positioning")
                            if "COVER" in str(pe.get("positioning"))
                            or "UNWIND" in str(pe.get("positioning"))
                            else "NONE"
                        ),
                        "gamma_load": (
                            (_number(pe.get("gamma")) or 0.0)
                            * (_number(pe.get("oi")) or 0.0)
                        ),
                        "load_intensity": pe_load["score"],
                        "load_breakdown": pe_load,
                        "liquidity_score": pe_load["components"]["liquidity"],
                        "velocity_arrow": ArgusPrimeProjection._velocity_arrow(
                            pe_velocity
                        ),
                        "depth": pe_depth,
                        "pressure_score": ((computed.get("PE") or {}).get("score")),
                    },
                    "wall_strength": (
                        "DUAL_WALL"
                        if len(wall_types) == 2
                        else f"{wall_types[0]}_WALL"
                        if wall_types
                        else "NONE"
                    ),
                    "wall_types": wall_types,
                    "blast_relevance": (
                        blast.get("state")
                        if strongest_gamma is not None and strike == strongest_gamma
                        else "LOW"
                    ),
                    "is_strongest_pressure": strike == strongest_pressure,
                    "is_strongest_gamma": (
                        strongest_gamma is not None and strike == strongest_gamma
                    ),
                    "directional_arrow": (
                        "UP" if direction == "CALL" else "DOWN"
                        if direction == "PUT" else "FLAT"
                    ),
                    "move_hint": (
                        "LIKELY_UPSIDE"
                        if direction == "CALL"
                        else "LIKELY_DOWNSIDE"
                        if direction == "PUT"
                        else "PIN_RISK"
                    ),
                    "breadth": breadth.get("direction") or "UNAVAILABLE",
                    "is_atm": strike == _number(underlying.get("atm_strike")),
                    "is_selected_contract": (
                        str(ce.get("security_id")) in selected_ids
                        or str(pe.get("security_id")) in selected_ids
                    ),
                    "is_probable_magnet": (
                        strongest_gamma is not None and strike == strongest_gamma
                    ),
                    "wall_condition": (
                        "WEAKENING"
                        if (
                            strike == call_wall
                            and (ArgusPrimeProjection._oi_velocity(
                                ce.get("oi"), (prior.get("CE") or {}).get("oi"), elapsed
                            ) or 0) < 0
                        )
                        or (
                            strike == put_wall
                            and (ArgusPrimeProjection._oi_velocity(
                                pe.get("oi"), (prior.get("PE") or {}).get("oi"), elapsed
                            ) or 0) < 0
                        )
                        else "STRENGTHENING"
                        if wall_types
                        else "NONE"
                    ),
                }
            )
        return result
