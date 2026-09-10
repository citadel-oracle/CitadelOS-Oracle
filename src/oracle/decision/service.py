"""Persisted, advisory-only Analysis -> Evidence -> Decision orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
import tempfile
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from src.oracle.analysis import AnalysisSnapshotAssembler
from src.oracle.analyst import MarketAnalystCore
from src.oracle.contracts.analysis import (
    AnalysisSnapshot, EvidenceBundle, OptionCaptureAssessment,
    OracleDecisionEnvelope, TimingAssessment, UnderlyingAssessment,
    record_from_dict, seal,
)
from src.oracle.evidence import EvidenceEngine


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")


class AnalysisNotFoundError(LookupError):
    pass


class ImmutableAnalysisConflictError(RuntimeError):
    pass


def _atomic_write_exact(path: Path, value: Mapping[str, Any]) -> None:
    """Preserve the content-addressed payload byte-for-value on atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class DecisionPolicy:
    version: str = "oracle-decision-3.0.0"
    minimum_rr: float = 1.5
    minimum_setup_quality: int = 60
    minimum_execution_quality: int = 50
    minimum_data_completeness: int = 75
    minimum_evidence_agreement: int = 70


@dataclass(frozen=True)
class AnalysisResult:
    snapshot: AnalysisSnapshot
    underlying: UnderlyingAssessment
    timing: TimingAssessment
    option_capture: OptionCaptureAssessment
    evidence: EvidenceBundle
    decision: OracleDecisionEnvelope

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.snapshot.to_dict(),
            "assessments": {
                "underlying": self.underlying.to_dict(), "timing": self.timing.to_dict(),
                "option_capture": self.option_capture.to_dict(),
            },
            "evidence": self.evidence.to_dict(), "decision": self.decision.to_dict(),
            "safety": {
                "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                "advisory_only": True, "execution_influence": "ZERO",
                "execution_authority": False,
            },
        }


class OracleAnalysisStore:
    """Atomic immutable records; reads perform no writes or refreshes."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = RLock()

    def save(self, result: AnalysisResult) -> None:
        payloads = {
            self.root / "snapshots" / f"{result.snapshot.analysis_id}.json": result.snapshot.to_dict(),
            self.root / "assessments" / f"{result.snapshot.analysis_id}.json": {
                "underlying": result.underlying.to_dict(), "timing": result.timing.to_dict(),
                "option_capture": result.option_capture.to_dict(),
            },
            self.root / "evidence" / f"{result.evidence.bundle_id}.json": result.evidence.to_dict(),
            self.root / "decisions" / f"{result.decision.decision_id}.json": result.decision.to_dict(),
            self.root / "manifests" / f"{result.snapshot.analysis_id}.json": {
                "analysis_id": result.snapshot.analysis_id, "snapshot_hash": result.snapshot.content_hash,
                "decision_id": result.decision.decision_id, "decision_hash": result.decision.content_hash,
                "evidence_bundle_id": result.evidence.bundle_id, "evidence_hash": result.evidence.content_hash,
                "assessment_hashes": {
                    "underlying": result.underlying.content_hash, "timing": result.timing.content_hash,
                    "option_capture": result.option_capture.content_hash,
                },
                "advisory_only": True, "execution_authority": False,
            },
        }
        with self._lock:
            for path, payload in payloads.items():
                if path.exists():
                    try:
                        current = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, TypeError) as error:
                        raise ImmutableAnalysisConflictError("IMMUTABLE_RECORD_UNREADABLE") from error
                    if current != payload:
                        raise ImmutableAnalysisConflictError("IMMUTABLE_RECORD_CONFLICT")
            for path, payload in payloads.items():
                if not path.exists():
                    _atomic_write_exact(path, payload)

    def analysis(self, analysis_id: str) -> dict[str, Any]:
        self._validate_id(analysis_id)
        snapshot = self._read(self.root / "snapshots" / f"{analysis_id}.json")
        assessments = self._read(self.root / "assessments" / f"{analysis_id}.json")
        manifest = self._read(self.root / "manifests" / f"{analysis_id}.json")
        return {"analysis": snapshot, "assessments": assessments, "manifest": manifest}

    def decision(self, decision_id: str) -> OracleDecisionEnvelope:
        self._validate_id(decision_id)
        return record_from_dict(OracleDecisionEnvelope, self._read(self.root / "decisions" / f"{decision_id}.json"))

    def evidence_for_decision(self, decision_id: str) -> EvidenceBundle:
        decision = self.decision(decision_id)
        return record_from_dict(EvidenceBundle, self._read(self.root / "evidence" / f"{decision.evidence_bundle_id}.json"))

    @staticmethod
    def _validate_id(value: str) -> None:
        if not _SAFE_ID.fullmatch(str(value)):
            raise AnalysisNotFoundError("ANALYSIS_RECORD_UNAVAILABLE")

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise AnalysisNotFoundError("ANALYSIS_RECORD_UNAVAILABLE") from error
        if not isinstance(value, dict):
            raise AnalysisNotFoundError("ANALYSIS_RECORD_UNAVAILABLE")
        return value


class OracleAnalysisService:
    """The sole Phase-3 orchestrator; no risk, mission, execution or broker dependency."""

    def __init__(
        self, root: str | Path, *, context_provider: Callable[[], Any] | None = None,
        dashboard_provider: Callable[[], Mapping[str, Any]] | None = None,
        feature_provider: Callable[[], Any] | None = None,
        visual_claim_provider: Callable[[str], Any] | None = None,
        clock=None, snapshot_assembler: AnalysisSnapshotAssembler | None = None,
        analyst: MarketAnalystCore | None = None, evidence_engine: EvidenceEngine | None = None,
        decision_policy: DecisionPolicy | None = None,
    ):
        self.store = OracleAnalysisStore(root)
        self.context_provider = context_provider
        self.dashboard_provider = dashboard_provider
        self.feature_provider = feature_provider
        self.visual_claim_provider = visual_claim_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.snapshot_assembler = snapshot_assembler or AnalysisSnapshotAssembler(clock=self.clock)
        self.analyst = analyst or MarketAnalystCore()
        self.evidence_engine = evidence_engine or EvidenceEngine()
        self.policy = decision_policy or DecisionPolicy()

    def create(self, *, symbol: str = "NIFTY", correlation_id: str | None = None,
               visual_claim_ids: Sequence[str] = (), telemetry=None) -> AnalysisResult:
        if symbol.upper() != "NIFTY":
            raise ValueError("PHASE3_SYMBOL_UNSUPPORTED")
        if any(not _SAFE_ID.fullmatch(str(claim_id)) for claim_id in visual_claim_ids):
            raise ValueError("VERIFIED_VISUAL_CLAIM_ID_INVALID")
        if self.context_provider is None or self.dashboard_provider is None:
            raise RuntimeError("ANALYSIS_SOURCE_PROVIDER_UNAVAILABLE")
        started = perf_counter()
        context = self.context_provider()
        self._telemetry(telemetry, "htf_cache_binding", started, context is None)
        if context is None:
            raise RuntimeError("CONTEXT_UNAVAILABLE")
        started = perf_counter()
        dashboard = self.dashboard_provider()
        self._telemetry(telemetry, "dashboard_snapshot_retrieval", started)
        execution = (((dashboard.get("feeds") or {}).get("strategy_lab") or {}).get("data") or {}).get("execution") or {}
        started = perf_counter()
        bool(execution.get("options_structure"))
        self._telemetry(telemetry, "ose_retrieval", started)
        started = perf_counter()
        bool(execution.get("nifty_vob"))
        self._telemetry(telemetry, "vob_retrieval", started)
        features = self.feature_provider() if self.feature_provider else None
        claims = []
        for claim_id in visual_claim_ids:
            claim = self.visual_claim_provider(claim_id) if self.visual_claim_provider else None
            if claim is None:
                raise ValueError(f"VERIFIED_VISUAL_CLAIM_UNAVAILABLE:{claim_id}")
            claims.append(claim)
        now = self.clock()
        correlation_id = correlation_id or f"oracle-analysis-{int(now.timestamp() * 1_000_000)}"
        started = perf_counter()
        snapshot = self.snapshot_assembler.assemble(
            context=context, dashboard=dashboard, canonical_features=features,
            visual_claims=claims, correlation_id=correlation_id,
        )
        self._telemetry(telemetry, "analysis_snapshot", started)
        return self.analyze_snapshot(snapshot, persist=True, telemetry=telemetry)

    def analyze_snapshot(self, snapshot: AnalysisSnapshot, *, persist: bool = True, telemetry=None) -> AnalysisResult:
        started = perf_counter()
        underlying = self.analyst.assess_underlying(snapshot)
        timing = self.analyst.assess_timing(snapshot, underlying)
        self._telemetry(telemetry, "market_analyst", started)
        started = perf_counter()
        options = self.analyst.assess_option_capture(snapshot, underlying)
        self._telemetry(telemetry, "option_candidate_comparison", started)
        started = perf_counter()
        evidence = self.evidence_engine.build(snapshot, underlying, timing, options)
        self._telemetry(telemetry, "evidence_bundle", started)
        started = perf_counter()
        decision = self._decide(snapshot, underlying, timing, options, evidence)
        self._telemetry(telemetry, "decision_envelope", started)
        result = AnalysisResult(snapshot, underlying, timing, options, evidence, decision)
        if persist:
            started = perf_counter()
            self.store.save(result)
            self._telemetry(telemetry, "phase3_persistence", started)
        return result

    @staticmethod
    def _telemetry(recorder, stage: str, started: float, error: bool = False) -> None:
        if recorder is not None:
            recorder(stage, (perf_counter() - started) * 1000, error=error)

    def analysis(self, analysis_id: str) -> dict[str, Any]:
        return self.store.analysis(analysis_id)

    def decision(self, decision_id: str) -> OracleDecisionEnvelope:
        return self.store.decision(decision_id)

    def evidence(self, decision_id: str) -> EvidenceBundle:
        return self.store.evidence_for_decision(decision_id)

    def _decide(self, snapshot, underlying, timing, options, evidence):
        estimate = options.execution_estimate
        reasons: list[str] = []
        terminal: list[str] = []
        wait: list[str] = []
        disclosed = {"4H_UNAVAILABLE_PARITY_UNPROVEN"}
        critical_underlying = [item for item in underlying.blockers if item not in disclosed]
        if not snapshot.compatible:
            terminal.extend(snapshot.compatibility_reasons or ("SOURCE_IDENTITY_OR_BOUNDARY_CONFLICT",))
        if timing.opportunity_expired:
            terminal.append("OPPORTUNITY_EXPIRED_OR_MARKET_CLOSED")
        if underlying.directional_posture == "NEUTRAL":
            terminal.append("DIRECTIONAL_EVIDENCE_CONFLICT")
        terminal.extend(item for item in critical_underlying if item in {
            "MANDATORY_HTF_CONTEXT_UNAVAILABLE", "DIRECTIONAL_EVIDENCE_CONFLICT",
            "STRUCTURAL_INVALIDATION_UNAVAILABLE", "NATURAL_TARGET_UNAVAILABLE", "NO_LOCATION_EDGE",
        })
        if not options.selected_contract_id:
            terminal.append("NO_ELIGIBLE_OPTION_CONTRACT")
        terminal.extend(item for item in options.blockers if item in {
            "NO_ELIGIBLE_OPTION_CONTRACT", "OSE_NON_CONFIRMATION", "INSUFFICIENT_NATURAL_RR",
            "PREMIUM_STOP_MAPPING_UNAVAILABLE", "PREMIUM_TARGET_MAPPING_UNAVAILABLE",
        })
        if estimate and (not estimate.resulting_rr or max(estimate.resulting_rr) < self.policy.minimum_rr):
            terminal.append("INSUFFICIENT_NATURAL_RR")
        if evidence.data_completeness < self.policy.minimum_data_completeness:
            terminal.append("DATA_COMPLETENESS_BELOW_POLICY")
        if evidence.evidence_agreement < self.policy.minimum_evidence_agreement:
            terminal.append("EVIDENCE_AGREEMENT_BELOW_POLICY")
        if timing.entry_extended:
            wait.append("ENTRY_MATERIALLY_EXTENDED")
        if not timing.trigger_satisfied and not timing.opportunity_expired and underlying.directional_posture != "NEUTRAL":
            wait.append("TRIGGER_INCOMPLETE")
        if options.execution_quality < self.policy.minimum_execution_quality and options.selected_contract_id:
            terminal.append("EXECUTION_QUALITY_BELOW_POLICY")
        stale_critical = [name for name in ("context", "argus", "vob", "ose", "canonical_features") if snapshot.source_states.get(name) != "FRESH"]
        if stale_critical:
            terminal.append("STALE_CRITICAL_SOURCE")
        if terminal:
            action = "NO_TRADE"
            reasons = terminal
        elif wait:
            action = "WAIT"
            reasons = wait
        elif underlying.setup_quality < self.policy.minimum_setup_quality:
            action, reasons = "NO_TRADE", ["SETUP_QUALITY_BELOW_POLICY"]
        elif timing.timing_state == "ENTRY_AVAILABLE" and options.option_state == "ELIGIBLE":
            action, reasons = "BUY", ["ALL_MANDATORY_PHASE3_GATES_SATISFIED"]
        else:
            action, reasons = "WAIT", ["FRESH_CONFIRMATION_PENDING"]
        selected = next((row for row in snapshot.candidate_contracts if row.contract_id == options.selected_contract_id), None)
        trigger = next((item for item in underlying.triggers if item.status == "SATISFIED"), None)
        invalidation = underlying.invalidations[0] if underlying.invalidations else None
        target_ids = tuple(item.target_id for item in underlying.natural_targets)
        contract_label = f"{selected.trading_symbol} ({selected.contract_id})" if selected else None
        why = f"{underlying.directional_posture} structure; timing {timing.timing_state}; option capture {options.option_state}."
        risk = "; ".join(sorted(set(reasons + list(options.blockers)))) or "Advisory candidate only; separate risk authorization is required outside Phase 3."
        return seal(OracleDecisionEnvelope(
            correlation_id=snapshot.correlation_id, snapshot_id=snapshot.snapshot_id,
            decision_id=str(snapshot.decision_id), instrument_id=snapshot.instrument_id,
            security_id=selected.contract_id if selected else snapshot.security_id,
            symbol=snapshot.symbol, timeframe="MULTI", source_timestamp=snapshot.source_timestamp,
            generated_at=snapshot.generated_at, as_of=snapshot.as_of,
            availability=snapshot.availability, freshness_state=snapshot.freshness_state,
            source_ids={"analysis_snapshot": snapshot.analysis_id, "evidence_bundle": evidence.bundle_id},
            source_hashes={"analysis_snapshot": snapshot.content_hash, "evidence_bundle": evidence.content_hash},
            dependency_versions={"decision_policy": self.policy.version,
                                 "analyst_policy": self.analyst.policy.version,
                                 "evidence_policy": self.evidence_engine.policy.version},
            provenance={"service": "OracleAnalysisService", "deterministic": True,
                        "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                        "advisory_only": True, "execution_influence": "ZERO"},
            missing_evidence=tuple(sorted(set(snapshot.missing_evidence + evidence.missing_evidence))),
            contradictory_evidence=tuple(sorted(set(snapshot.contradictory_evidence + evidence.contradictory_evidence))),
            action=action, policy_version=self.policy.version, analysis_snapshot_hash=snapshot.content_hash,
            assessment_hashes={"underlying": underlying.content_hash, "timing": timing.content_hash,
                               "option_capture": options.content_hash},
            evidence_bundle_id=evidence.bundle_id, evidence_bundle_hash=evidence.content_hash,
            selected_contract_id=selected.contract_id if selected else None, contract_label=contract_label,
            setup_quality=underlying.setup_quality,
            score_components={"setup_quality": dict(underlying.score_components),
                              "timing": dict(timing.score_components),
                              "option_capture": dict(options.score_components),
                              "data_completeness": {"snapshot": snapshot.data_completeness,
                                                    "evidence_bundle": evidence.data_completeness},
                              "evidence_agreement": {"supporting": evidence.supporting_count,
                                                     "contradicting": evidence.contradicting_count,
                                                     "missing": evidence.missing_count}},
            visual_certainty=evidence.visual_certainty, data_completeness=evidence.data_completeness,
            execution_quality=options.execution_quality, evidence_agreement=evidence.evidence_agreement,
            calibration_status="NOT_AVAILABLE", historical_probability=None,
            trigger_summary=f"{trigger.trigger_type} {trigger.direction} {trigger.level}" if trigger else "Confirmation pending",
            entry_band=estimate.entry_band if estimate else None,
            structural_invalidation_id=invalidation.invalidation_id if invalidation else None,
            premium_hard_stop_candidate=estimate.premium_hard_stop_candidate if estimate else None,
            stop_mapping_status=estimate.stop_mapping_status if estimate else "UNAVAILABLE",
            target_ids=target_ids, target_premiums=estimate.target_premiums if estimate else (),
            resulting_rr=estimate.resulting_rr if estimate else (),
            estimated_cost=estimate.estimated_round_trip_cost if estimate else None,
            why=why, risk=risk, reason_codes=tuple(sorted(set(reasons))),
            blockers=tuple(sorted(set(terminal + wait + list(options.blockers) + critical_underlying))),
            execution_authority=False,
        ))
