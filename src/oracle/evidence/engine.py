"""Explainable claim-level evidence over already-authoritative records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.oracle.contracts.analysis import (
    AnalysisSnapshot, EvidenceBundle, EvidenceConflict, EvidenceItem,
    OptionCaptureAssessment, TimingAssessment, UnderlyingAssessment, seal,
)
from src.oracle.contracts.perception import Availability, FreshnessState


@dataclass(frozen=True)
class EvidencePolicy:
    version: str = "oracle-evidence-3.0.0"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class EvidenceEngine:
    def __init__(self, policy: EvidencePolicy | None = None):
        self.policy = policy or EvidencePolicy()

    def build(
        self, snapshot: AnalysisSnapshot, underlying: UnderlyingAssessment,
        timing: TimingAssessment, options: OptionCaptureAssessment,
    ) -> EvidenceBundle:
        records = _dict(snapshot.source_records)
        vob = _dict(records.get("vob"))
        tactical = _dict(records.get("argus_tactical"))
        ose = _dict(records.get("ose"))
        items: list[EvidenceItem] = []
        conflicts: list[EvidenceConflict] = []

        lanes = _dict(records.get("context_lanes"))
        mandatory_lanes = ("1D", "1H", "15m", "5m", "3m")
        lane_missing = [tf for tf in mandatory_lanes if str(_dict(lanes.get(tf)).get("availability")) not in {"AVAILABLE", "HISTORICAL"}]
        items.append(self._item(
            snapshot, "context", "completed multi-timeframe numerical context is present",
            "MISSING" if lane_missing else "SUPPORT", "MANDATORY",
            f"Missing lanes: {', '.join(lane_missing)}" if lane_missing else "Phase-2 completed context lanes are referenced by hash.",
            {"available_lanes": len(mandatory_lanes) - len(lane_missing), "required_lanes": len(mandatory_lanes)},
        ))
        four_h = _dict(lanes.get("4H"))
        four_h_available = str(four_h.get("availability")) == "AVAILABLE" and bool(four_h.get("evidence_eligible"))
        items.append(self._item(
            snapshot, "context", "4H context parity is proven", "SUPPORT" if four_h_available else "MISSING", "DISCLOSURE",
            "4H parity-proven context is available." if four_h_available else "4H remains unavailable because TradingView parity is unproven; it is not a mandatory Phase-3 numerical gate.",
            {"availability": four_h.get("availability"), "evidence_eligible": four_h.get("evidence_eligible")}, suffix="4h",
        ))

        posture = underlying.directional_posture
        strongest = _dict(vob.get("strongest_confluence"))
        vob_direction = "BULLISH" if strongest.get("bullish") and not strongest.get("bearish") else "BEARISH" if strongest.get("bearish") and not strongest.get("bullish") else "NEUTRAL"
        items.append(self._item(
            snapshot, "vob", f"VOB structure supports {posture}",
            "SUPPORT" if posture != "NEUTRAL" and vob_direction == posture else "CONTRADICT" if vob_direction not in {"NEUTRAL", posture} else "MISSING",
            "MANDATORY", f"Reused VOB strongest-confluence direction is {vob_direction}.",
            {"vob_direction": vob_direction, "spot": vob.get("current_nifty_spot")},
        ))
        oracle = _dict(records.get("canonical_market_assessment"))
        oracle_direction = str(oracle.get("directional_bias") or "NEUTRAL").upper()
        items.append(self._item(
            snapshot, "canonical_market_assessment", f"canonical numerical assessment supports {posture}",
            "SUPPORT" if posture != "NEUTRAL" and oracle_direction == posture else "CONTRADICT" if oracle_direction not in {"NEUTRAL", posture} else "MISSING",
            "MANDATORY", f"Existing canonical market assessment reports {oracle_direction}; its indicator values are not recalculated here.",
            {"directional_bias": oracle_direction, "signal": oracle.get("signal"), "regime": oracle.get("regime")},
        ))

        trigger_classification = "SUPPORT" if timing.trigger_satisfied else "MISSING"
        items.append(self._derived_item(
            snapshot, timing, "timing", "completed structural trigger is satisfied now", trigger_classification,
            "MANDATORY", f"Timing state is {timing.timing_state}.",
            {"trigger_satisfied": timing.trigger_satisfied, "entry_extended": timing.entry_extended,
             "opportunity_expired": timing.opportunity_expired},
        ))

        selected = next((row for row in snapshot.candidate_contracts if row.contract_id == options.selected_contract_id), None)
        items.append(self._derived_item(
            snapshot, options, "option_capture", "an eligible executable option contract exists",
            "SUPPORT" if selected and options.option_state == "ELIGIBLE" else "MISSING", "MANDATORY",
            f"Selected exact ARGUS-ranked contract {selected.contract_id}." if selected else "No contract passed identity, freshness, spread, liquidity, Delta and authority gates.",
            {"candidate_count": len(snapshot.candidate_contracts), "eligible_count": len(options.eligible_contract_ids),
             "selected_contract_id": options.selected_contract_id, "execution_quality": options.execution_quality,
             "missing_contract_fields": list(selected.missing_evidence) if selected else [],
             "iv": selected.iv if selected else None, "theta": selected.theta if selected else None,
             "vega": selected.vega if selected else None, "gamma": selected.gamma if selected else None},
        ))

        duel = _dict(ose.get("duel"))
        side = options.requested_side
        duel_state = str(duel.get("state") or "UNAVAILABLE").upper()
        aligned = bool(side) and ((side == "CE" and "CALL ADVANTAGE" in duel_state) or (side == "PE" and "PUT ADVANTAGE" in duel_state))
        items.append(self._item(
            snapshot, "ose", f"OSE pair context confirms {side or 'directional'} option capture",
            "SUPPORT" if aligned else "CONTRADICT" if duel_state != "UNAVAILABLE" and side else "MISSING",
            "MANDATORY", f"Reused OSE duel state is {duel_state}; no OSE logic is reproduced.",
            {"state": duel_state, "ce_score": duel.get("ce_score"), "pe_score": duel.get("pe_score"), "delta": duel.get("delta")},
        ))

        market_open = snapshot.market_state in {"OPEN", "NON_LIVE_FIXTURE"}
        items.append(self._item(
            snapshot, "session", "the opportunity window is open", "SUPPORT" if market_open else "CONTRADICT",
            "MANDATORY", f"Authoritative ARGUS market state is {snapshot.market_state}.",
            {"market_state": snapshot.market_state, "time_remaining_seconds": snapshot.time_remaining_seconds},
        ))
        visual_certainty = "UNAVAILABLE"
        if snapshot.visual_claims:
            visual_certainty = "VERIFIED" if any(row.freshness_state is FreshnessState.FRESH for row in snapshot.visual_claims) else "VERIFIED_HISTORICAL"
            items.append(self._item(
                snapshot, "visual", "verified TradingView visual evidence is available",
                "SUPPORT", "OPTIONAL", "Only Phase-2 numerically verified claims are referenced.",
                {"verified_claim_count": len(snapshot.visual_claims)},
            ))
        else:
            items.append(self._item(
                snapshot, "visual", "verified TradingView visual evidence is available",
                "MISSING", "OPTIONAL", "VISUAL_UNAVAILABLE; purely numerical analysis remains permitted.",
                {"verified_claim_count": 0},
            ))

        contradictory = [item for item in items if item.classification == "CONTRADICT"]
        if posture == "NEUTRAL":
            conflicts.append(self._conflict(snapshot, "direction", "directional evidence is coherent",
                                            (underlying.assessment_id,), "MATERIAL",
                                            "VOB/canonical votes do not resolve to one posture.", "BUY_FORBIDDEN"))
        if not aligned and side and duel_state != "UNAVAILABLE":
            conflicts.append(self._conflict(snapshot, "ose", "option-side structure confirms the underlying thesis",
                                            (str(snapshot.source_ids.get("ose")), options.assessment_id), "MATERIAL",
                                            f"OSE {duel_state} does not confirm {side}.", "BUY_FORBIDDEN"))
        stale = [name for name in ("context", "argus", "vob", "ose", "canonical_features") if str(snapshot.source_states.get(name)) != "FRESH"]
        if stale:
            conflicts.append(self._conflict(snapshot, "freshness", "critical sources are fresh",
                                            tuple(stale), "MATERIAL", f"Stale or unavailable critical sources: {', '.join(stale)}.", "BUY_FORBIDDEN"))
        if snapshot.compatibility_reasons:
            conflicts.append(self._conflict(snapshot, "identity", "all source identities and boundaries are compatible",
                                            tuple(snapshot.source_ids.values()), "CRITICAL", "; ".join(snapshot.compatibility_reasons), "NO_TRADE"))
        support_count = sum(item.classification == "SUPPORT" for item in items)
        contradict_count = len(contradictory)
        missing_count = sum(item.classification == "MISSING" for item in items)
        agreement = round(support_count / max(1, support_count + contradict_count) * 100)
        completeness = round((snapshot.data_completeness + (len(items) - missing_count) / len(items) * 100) / 2)
        common = self._common(snapshot, "evidence_bundle", source="analysis_snapshot")
        return seal(EvidenceBundle(
            **common, bundle_id=f"evidence_{snapshot.analysis_id}", items=tuple(items), conflicts=tuple(conflicts),
            supporting_count=support_count, contradicting_count=contradict_count, missing_count=missing_count,
            data_completeness=max(0, min(100, completeness)), evidence_agreement=agreement,
            visual_certainty=visual_certainty,
            missing_evidence=tuple(item.evidence_id for item in items if item.classification == "MISSING"),
            contradictory_evidence=tuple(item.evidence_id for item in contradictory),
        ))

    def _common(self, snapshot, suffix, *, source):
        source_timestamp = str(snapshot.source_timestamps.get(source) or snapshot.source_timestamp)
        return dict(
            correlation_id=snapshot.correlation_id, snapshot_id=snapshot.snapshot_id,
            decision_id=snapshot.decision_id, instrument_id=snapshot.instrument_id,
            security_id=snapshot.security_id, symbol=snapshot.symbol, timeframe="MULTI",
            source_timestamp=source_timestamp, generated_at=snapshot.generated_at, as_of=source_timestamp,
            availability=snapshot.availability, freshness_state=snapshot.freshness_state,
            source_ids={source: str(snapshot.source_ids.get(source) or snapshot.analysis_id), "record": suffix},
            source_hashes={source: str(snapshot.source_hashes.get(source) or snapshot.content_hash)},
            dependency_versions={"evidence_policy": self.policy.version},
            provenance={"service": "EvidenceEngine", "claim_level": True, "advisory_only": True,
                        "execution_influence": "ZERO"},
        )

    def _item(self, snapshot, source, claim, classification, materiality, explanation, numerical_values, suffix=None):
        suffix = suffix or source
        source_id = str(snapshot.source_ids.get(source) or f"{source}_{snapshot.analysis_id}")
        source_hash = str(snapshot.source_hashes.get(source) or snapshot.content_hash)
        return seal(EvidenceItem(
            **self._common(snapshot, f"evidence:{suffix}", source=source),
            evidence_id=f"evidence_{suffix}_{snapshot.analysis_id}", claim=claim, source=source.upper(),
            source_record_id=source_id, source_record_hash=source_hash, classification=classification,
            materiality=materiality, explanation=explanation, numerical_values=numerical_values,
        ))

    def _derived_item(self, snapshot, assessment, suffix, claim, classification, materiality, explanation, numerical_values):
        return seal(EvidenceItem(
            **self._common(snapshot, f"evidence:{suffix}", source="analysis_snapshot"),
            evidence_id=f"evidence_{suffix}_{snapshot.analysis_id}", claim=claim, source=type(assessment).__name__,
            source_record_id=assessment.assessment_id, source_record_hash=assessment.content_hash,
            classification=classification, materiality=materiality, explanation=explanation,
            numerical_values=numerical_values,
        ))

    def _conflict(self, snapshot, suffix, claim, source_ids, severity, explanation, resolution):
        return seal(EvidenceConflict(
            **self._common(snapshot, f"conflict:{suffix}", source="analysis_snapshot"),
            conflict_id=f"conflict_{suffix}_{snapshot.analysis_id}", claim=claim,
            source_record_ids=tuple(source_ids), severity=severity, explanation=explanation, resolution=resolution,
            contradictory_evidence=(explanation,),
        ))
