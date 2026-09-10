"""Three-question deterministic analyst over immutable authority snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.oracle.contracts.analysis import (
    AnalysisSnapshot, ExecutionEstimate, NaturalTarget, OptionCaptureAssessment,
    OptionContractQuote, StructuralInvalidation, StructuralTrigger,
    TimingAssessment, UnderlyingAssessment, seal,
)
from src.oracle.contracts.perception import Availability, FreshnessState


@dataclass(frozen=True)
class AnalystPolicy:
    version: str = "oracle-analyst-3.0.0"
    max_spread_pct: float = 2.5
    minimum_abs_delta: float = 0.30
    maximum_abs_delta: float = 0.75
    maximum_atm_distance: float = 100.0
    minimum_contract_score: float = 55.0
    maximum_daily_theta_fraction: float = 0.15
    minimum_rr: float = 1.5
    slippage_fraction_of_spread: float = 0.25
    round_trip_cost_buffer: float = 0.20


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class MarketAnalystCore:
    """Consumes upstream projections; it never calculates their indicators or rankings."""

    def __init__(self, policy: AnalystPolicy | None = None):
        self.policy = policy or AnalystPolicy()

    def assess(self, snapshot: AnalysisSnapshot):
        underlying = self.assess_underlying(snapshot)
        timing = self.assess_timing(snapshot, underlying)
        options = self.assess_option_capture(snapshot, underlying)
        return underlying, timing, options

    def _common(self, snapshot: AnalysisSnapshot, suffix: str, *, source_timestamp: str | None = None):
        return dict(
            correlation_id=snapshot.correlation_id, snapshot_id=snapshot.snapshot_id,
            decision_id=snapshot.decision_id, instrument_id=snapshot.instrument_id,
            security_id=snapshot.security_id, symbol=snapshot.symbol, timeframe="MULTI",
            source_timestamp=source_timestamp or snapshot.source_timestamp,
            generated_at=snapshot.generated_at, as_of=source_timestamp or snapshot.as_of,
            availability=snapshot.availability, freshness_state=snapshot.freshness_state,
            source_ids={"analysis_snapshot": snapshot.analysis_id, "record": suffix},
            source_hashes={"analysis_snapshot": snapshot.content_hash},
            dependency_versions={"analyst_policy": self.policy.version},
            provenance={"service": "MarketAnalystCore", "advisory_only": True,
                        "execution_influence": "ZERO"},
        )

    def assess_underlying(self, snapshot: AnalysisSnapshot) -> UnderlyingAssessment:
        records = _mapping(snapshot.source_records)
        vob = _mapping(records.get("vob"))
        oracle = _mapping(records.get("canonical_market_assessment"))
        features = _mapping(records.get("canonical_features"))
        timeframes = _mapping(vob.get("timeframes"))
        strongest = _mapping(vob.get("strongest_confluence"))
        votes: list[str] = []
        if strongest.get("bullish") and not strongest.get("bearish"):
            votes.append("BULLISH")
        if strongest.get("bearish") and not strongest.get("bullish"):
            votes.append("BEARISH")
        feature_direction = str(_mapping(features.get("supertrend")).get("direction") or "").upper()
        if feature_direction in {"BULLISH", "BEARISH"}:
            votes.append(feature_direction)
        oracle_direction = str(oracle.get("directional_bias") or "").upper()
        if oracle_direction in {"BULLISH", "BEARISH"}:
            votes.append(oracle_direction)
        bullish, bearish = votes.count("BULLISH"), votes.count("BEARISH")
        posture = "BULLISH" if bullish and not bearish else "BEARISH" if bearish and not bullish else "NEUTRAL"

        lane_records = _mapping(records.get("context_lanes"))
        mandatory = ("1D", "1H", "15m")
        lane_available = sum(str(_mapping(lane_records.get(tf)).get("availability")) in {"AVAILABLE", "HISTORICAL"} for tf in mandatory)
        blockers: list[str] = []
        if lane_available < len(mandatory):
            blockers.append("MANDATORY_HTF_CONTEXT_UNAVAILABLE")
        if str(_mapping(lane_records.get("4H")).get("availability")) != "AVAILABLE":
            blockers.append("4H_UNAVAILABLE_PARITY_UNPROVEN")
        if posture == "NEUTRAL":
            blockers.append("DIRECTIONAL_EVIDENCE_CONFLICT")

        five = _mapping(timeframes.get("5m"))
        spot = self._number(five.get("current_nifty_price")) or self._number(_mapping(records.get("argus_underlying")).get("ltp")) or self._number(vob.get("current_nifty_spot"))

        candidate_supports: list[tuple[dict[str, Any], float]] = []
        for s_dict in [
            _mapping(five.get("nearest_bullish_support")),
            _mapping(vob.get("nearest_support")),
            _mapping(_mapping(timeframes.get("3m")).get("nearest_bullish_support")),
            _mapping(_mapping(timeframes.get("15m")).get("nearest_bullish_support")),
            _mapping(vob.get("strongest_support")),
        ]:
            s_low = self._number(s_dict.get("zone_low")) or self._number(s_dict.get("zone_high"))
            if s_dict and s_low is not None and (spot is None or s_low <= spot):
                candidate_supports.append((s_dict, s_low))

        candidate_resistances: list[tuple[dict[str, Any], float]] = []
        for r_dict in [
            _mapping(five.get("nearest_bearish_resistance")),
            _mapping(vob.get("nearest_resistance")),
            _mapping(_mapping(timeframes.get("3m")).get("nearest_bearish_resistance")),
            _mapping(_mapping(timeframes.get("15m")).get("nearest_bearish_resistance")),
            _mapping(vob.get("strongest_resistance")),
        ]:
            r_high = self._number(r_dict.get("zone_high")) or self._number(r_dict.get("zone_low"))
            if r_dict and r_high is not None and (spot is None or r_high >= spot):
                candidate_resistances.append((r_dict, r_high))

        support, support_level = candidate_supports[0] if candidate_supports else ({}, None)
        resistance, resistance_level = candidate_resistances[0] if candidate_resistances else ({}, None)
        room = None
        if spot is not None and support_level is not None and resistance_level is not None and resistance_level > support_level:
            room = (spot - support_level) / (resistance_level - support_level)
        location = "FAVOURABLE" if room is not None and ((posture == "BULLISH" and room <= .55) or (posture == "BEARISH" and room >= .45)) else "MID_RANGE"
        if location == "MID_RANGE":
            blockers.append("NO_LOCATION_EDGE")

        triggers = self._triggers(snapshot, posture, timeframes)
        invalidations: list[StructuralInvalidation] = []
        targets: list[NaturalTarget] = []
        if posture == "BULLISH":
            if support_level is not None:
                invalidations.append(self._invalidation(snapshot, "VOB_SUPPORT_FAILURE", posture, support_level, support))
            if resistance_level is not None and spot is not None and resistance_level > spot:
                targets.append(self._target(snapshot, "VOB_RESISTANCE", posture, resistance_level, resistance))
        elif posture == "BEARISH":
            if resistance_level is not None:
                invalidations.append(self._invalidation(snapshot, "VOB_RESISTANCE_FAILURE", posture, resistance_level, resistance))
            if support_level is not None and spot is not None and support_level < spot:
                targets.append(self._target(snapshot, "VOB_SUPPORT", posture, support_level, support))
        if not invalidations:
            blockers.append("STRUCTURAL_INVALIDATION_UNAVAILABLE")
        if not targets:
            blockers.append("NATURAL_TARGET_UNAVAILABLE")

        score_components = {
            "htf_availability": round(lane_available / len(mandatory) * 100, 2),
            "directional_agreement": round(max(bullish, bearish) / max(1, len(votes)) * 100, 2),
            "location_quality": 100.0 if location == "FAVOURABLE" else 35.0,
            "structure_definition": 100.0 if invalidations and targets else 50.0 if invalidations or targets else 0.0,
        }
        setup_quality = round(
            score_components["htf_availability"] * .20
            + score_components["directional_agreement"] * .30
            + score_components["location_quality"] * .25
            + score_components["structure_definition"] * .25
        )
        return seal(UnderlyingAssessment(
            **self._common(snapshot, "underlying"), assessment_id=f"underlying_{snapshot.analysis_id}",
            directional_posture=posture, location_quality=location,
            permitted_thesis_types=("DIRECTIONAL_OPTION_BUY",) if posture != "NEUTRAL" else (),
            blockers=tuple(sorted(set(blockers))), triggers=tuple(triggers),
            invalidations=tuple(invalidations), natural_targets=tuple(targets),
            setup_quality=setup_quality, score_components=score_components,
            missing_evidence=tuple(item for item in blockers if "UNAVAILABLE" in item),
            contradictory_evidence=tuple(item for item in blockers if "CONFLICT" in item),
        ))

    def _triggers(self, snapshot, posture, timeframes):
        result = []
        three = _mapping(timeframes.get("3m"))
        lane = _mapping(_mapping(snapshot.source_records).get("context_lanes")).get("3m") or {}
        boundary = _mapping(lane).get("source_boundary")
        for zone in three.get("recently_broken") or ():
            if not isinstance(zone, Mapping) or str(zone.get("broken_at")) != str(boundary):
                continue
            direction = "BULLISH" if zone.get("role") == "RESISTANCE" else "BEARISH" if zone.get("role") == "SUPPORT" else "NEUTRAL"
            status = "SATISFIED" if direction == posture and snapshot.freshness_state is FreshnessState.FRESH else "EXPIRED"
            result.append(seal(StructuralTrigger(
                **self._common(snapshot, f"trigger:{zone.get('zone_id')}", source_timestamp=str(boundary)),
                trigger_id=f"trigger_{zone.get('zone_id')}", trigger_type="VOB_COMPLETED_CLOSE_BREAK",
                direction=direction, level=self._number(zone.get("zone_high") or zone.get("zone_low")),
                predicate={"broken_at": zone.get("broken_at"), "required_boundary": boundary}, status=status,
            )))
        for claim in snapshot.visual_claims:
            if claim.status != "VERIFIED":
                continue
            result.append(seal(StructuralTrigger(
                **self._common(snapshot, f"visual:{claim.claim_id}", source_timestamp=claim.source_timestamp),
                trigger_id=f"trigger_{claim.claim_id}", trigger_type=f"VERIFIED_VISUAL_{claim.claim_type}",
                direction=posture, level=self._number(claim.numerical_values.get("level")),
                predicate={"claim_hash": claim.content_hash},
                status="SATISFIED" if claim.freshness_state is FreshnessState.FRESH else "EXPIRED",
            )))
        return result

    def _invalidation(self, snapshot, kind, direction, level, source):
        return seal(StructuralInvalidation(
            **self._common(snapshot, f"invalidation:{source.get('zone_id') or kind}"),
            invalidation_id=f"invalidation_{source.get('zone_id') or kind.lower()}",
            invalidation_type=kind, direction=direction, level=level,
            predicate={"zone_id": source.get("zone_id"), "failure_level": level,
                       "requires_completed_close": True}, mapping_status="STRUCTURAL_SOFT_INVALIDATION",
        ))

    def _target(self, snapshot, kind, direction, level, source):
        return seal(NaturalTarget(
            **self._common(snapshot, f"target:{source.get('zone_id') or kind}"),
            target_id=f"target_{source.get('zone_id') or kind.lower()}", target_type=kind,
            direction=direction, level=level, authority="VOB",
        ))

    def assess_timing(self, snapshot: AnalysisSnapshot, underlying: UnderlyingAssessment) -> TimingAssessment:
        records = _mapping(snapshot.source_records)
        tactical = _mapping(records.get("argus_tactical"))
        lifecycle = _mapping(tactical.get("entry_lifecycle"))
        trigger_satisfied = any(item.status == "SATISFIED" for item in underlying.triggers)
        directive = _mapping(_mapping(tactical.get("contract_selection")).get("directive_contract"))
        stretch = str(directive.get("stretch_state") or "").upper()
        extended = stretch in {"STRETCHED", "EXTREME"} or str(lifecycle.get("state") or "").upper() in {"EXTENDED", "LATE"}
        expired = snapshot.market_state not in {"OPEN", "NON_LIVE_FIXTURE"} or snapshot.freshness_state is FreshnessState.STALE
        blockers = []
        if expired:
            state, blockers = "SETUP_INVALIDATED", ["OPPORTUNITY_EXPIRED_OR_MARKET_CLOSED"]
        elif extended:
            state, blockers = "ENTRY_EXTENDED", ["ENTRY_MATERIALLY_EXTENDED"]
        elif trigger_satisfied:
            state = "ENTRY_AVAILABLE"
        elif underlying.directional_posture != "NEUTRAL":
            state, blockers = "CONFIRMATION_PENDING", ["TRIGGER_INCOMPLETE"]
        else:
            state, blockers = "SETUP_FORMING", ["THESIS_NOT_YET_COHERENT"]
        components = {"completed_ltf_context": 100.0 if not expired else 0.0,
                      "trigger_completion": 100.0 if trigger_satisfied else 0.0,
                      "entry_extension": 0.0 if extended else 100.0,
                      "opportunity_window": 0.0 if expired else 100.0}
        score = round(sum(components.values()) / len(components))
        return seal(TimingAssessment(
            **self._common(snapshot, "timing"), assessment_id=f"timing_{snapshot.analysis_id}",
            timing_state=state, trigger_satisfied=trigger_satisfied, entry_extended=extended,
            opportunity_expired=expired, blockers=tuple(blockers), score=score,
            score_components=components, missing_evidence=tuple(blockers),
        ))

    def assess_option_capture(self, snapshot: AnalysisSnapshot, underlying: UnderlyingAssessment) -> OptionCaptureAssessment:
        side = "CE" if underlying.directional_posture == "BULLISH" else "PE" if underlying.directional_posture == "BEARISH" else None
        rejected: dict[str, tuple[str, ...]] = {}
        eligible: list[OptionContractQuote] = []
        for quote in snapshot.candidate_contracts:
            reasons = self._contract_blockers(snapshot, quote, side)
            if reasons:
                rejected[quote.contract_id] = tuple(reasons)
            else:
                eligible.append(quote)
        eligible.sort(key=lambda row: (row.authority_rank if row.authority_rank is not None else 10_000, -(row.authority_score or 0)))
        selected = eligible[0] if eligible else None
        blockers = [] if selected else ["NO_ELIGIBLE_OPTION_CONTRACT"]
        ose = _mapping(_mapping(snapshot.source_records).get("ose"))
        duel = str(_mapping(ose.get("duel")).get("state") or "").upper()
        aligned = (side == "CE" and "CALL ADVANTAGE" in duel) or (side == "PE" and "PUT ADVANTAGE" in duel)
        if side and duel and not aligned:
            blockers.append("OSE_NON_CONFIRMATION")
        estimate = self._execution_estimate(snapshot, selected, underlying) if selected else None
        if estimate and estimate.resulting_rr and max(estimate.resulting_rr) < self.policy.minimum_rr:
            blockers.append("INSUFFICIENT_NATURAL_RR")
        if estimate and not estimate.executable:
            blockers.extend(estimate.blockers)
        spread_quality = max(0.0, 100.0 - (selected.spread_pct or 100.0) / self.policy.max_spread_pct * 100.0) if selected else 0.0
        authority_quality = selected.authority_score or 0.0 if selected else 0.0
        greeks_quality = 100.0 if selected and selected.delta is not None and selected.iv is not None else 50.0 if selected else 0.0
        ose_quality = 100.0 if aligned else 30.0 if duel else 0.0
        components = {"authority_contract_quality": authority_quality, "spread_quality": spread_quality,
                      "greeks_completeness": greeks_quality, "ose_alignment": ose_quality}
        quality = round(sum(components.values()) / len(components))
        return seal(OptionCaptureAssessment(
            **self._common(snapshot, "option_capture"), assessment_id=f"option_{snapshot.analysis_id}",
            option_state="ELIGIBLE" if selected and not blockers else "BLOCKED",
            requested_side=side, selected_contract_id=selected.contract_id if selected else None,
            eligible_contract_ids=tuple(row.contract_id for row in eligible), rejected_contracts=rejected,
            execution_estimate=estimate, blockers=tuple(sorted(set(blockers))),
            execution_quality=quality, score_components=components,
            missing_evidence=tuple(blockers),
        ))

    def _contract_blockers(self, snapshot, quote, side):
        reasons = []
        if quote.option_type != side:
            return ["DIRECTIONAL_SIDE_MISMATCH"]
        if quote.availability is not Availability.AVAILABLE or quote.freshness_state is not FreshnessState.FRESH:
            reasons.append("STALE_OPTION_QUOTE")
        if quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask <= 0:
            reasons.append("EXECUTABLE_BID_ASK_UNAVAILABLE")
        if quote.spread_pct is None or quote.spread_pct > self.policy.max_spread_pct:
            reasons.append("SPREAD_UNACCEPTABLE")
        if quote.distance_atm is None or quote.distance_atm > self.policy.maximum_atm_distance:
            reasons.append("FAR_OTM_OR_DISTANCE_UNACCEPTABLE")
        if quote.delta is None or not self.policy.minimum_abs_delta <= abs(quote.delta) <= self.policy.maximum_abs_delta:
            reasons.append("DELTA_UNSUITABLE_OR_MISSING")
        if not quote.volume or not quote.oi:
            reasons.append("LIQUIDITY_FIELDS_UNAVAILABLE")
        if quote.authority_status != "CANDIDATE" or quote.rejection_reason:
            reasons.append(quote.rejection_reason or "UPSTREAM_CONTRACT_REJECTED")
        if (quote.authority_score or 0) < self.policy.minimum_contract_score:
            reasons.append("UPSTREAM_CONTRACT_QUALITY_LOW")
        if quote.iv is not None and quote.iv >= 40:
            reasons.append("IV_HOSTILITY")
        if quote.theta is not None and quote.ask and abs(quote.theta) / quote.ask > self.policy.maximum_daily_theta_fraction:
            reasons.append("THETA_DECAY_HOSTILITY")
        if snapshot.time_remaining_seconds is not None and snapshot.time_remaining_seconds <= 0:
            reasons.append("CONTRACT_EXPIRED")
        return reasons

    def _execution_estimate(self, snapshot, quote, underlying):
        spread = quote.spread_abs if quote and quote.spread_abs is not None else None
        if not quote or quote.ask is None or spread is None:
            return None
        slippage = round(spread * self.policy.slippage_fraction_of_spread, 4)
        entry = round(quote.ask + slippage, 4)
        entry_band = (round(quote.ask, 4), round(quote.ask + spread * .5, 4))
        spot = self._number(_mapping(_mapping(snapshot.source_records).get("argus_underlying")).get("ltp"))
        invalidation = underlying.invalidations[0] if underlying.invalidations else None
        targets = underlying.natural_targets
        stop = None
        target_premiums = []
        rr = []
        cost = round(slippage * 2 + self.policy.round_trip_cost_buffer, 4)
        blockers = []
        if spot is not None and invalidation and invalidation.level is not None and quote.delta is not None:
            distance = abs(spot - invalidation.level)
            stop = round(max(.05, entry - distance * abs(quote.delta)), 4)
        else:
            blockers.append("PREMIUM_STOP_MAPPING_UNAVAILABLE")
        for target in targets:
            if spot is None or quote.delta is None:
                continue
            premium = round(entry + abs(target.level - spot) * abs(quote.delta), 4)
            target_premiums.append(premium)
            if stop is not None:
                risk = entry - stop + cost
                reward = premium - entry - cost
                if risk > 0:
                    rr.append(round(max(0.0, reward / risk), 3))
        if not target_premiums:
            blockers.append("PREMIUM_TARGET_MAPPING_UNAVAILABLE")
        return seal(ExecutionEstimate(
            **self._common(snapshot, f"execution:{quote.contract_id}"), contract_id=quote.contract_id,
            expected_entry=entry, entry_band=entry_band, estimated_one_way_slippage=slippage,
            estimated_round_trip_cost=cost, premium_hard_stop_candidate=stop,
            stop_mapping_status="DELTA_APPROXIMATION_LOW_CONFIDENCE" if stop is not None else "UNAVAILABLE",
            target_premiums=tuple(target_premiums), resulting_rr=tuple(rr),
            executable=not blockers, blockers=tuple(blockers),
            components={"quote_hash": quote.content_hash, "ask": quote.ask, "spread_abs": spread,
                        "delta": quote.delta, "underlying_spot": spot,
                        "structural_invalidation": invalidation.level if invalidation else None,
                        "natural_targets": [target.level for target in targets],
                        "slippage_fraction": self.policy.slippage_fraction_of_spread,
                        "cost_buffer": self.policy.round_trip_cost_buffer},
        ))

    @staticmethod
    def _number(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
