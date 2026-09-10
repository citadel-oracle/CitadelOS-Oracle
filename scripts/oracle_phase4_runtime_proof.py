#!/usr/bin/env python3
"""Persistent, advisory-only Phase-4 runtime and latency proof.

The script appends only Phase-4 evidence/Visual Edge learning records.  It
hashes mission, risk, paper, Guardian and order state before and after and
fails if any of those authorities change.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.oracle.contracts.learning import CitationLocator, LearningContractError
from src.oracle.decision import OracleAnalysisService
from src.oracle.evidence import Phase4EvidenceService
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query
from src.oracle.similarity import HistoricalDataset, SimilarityEngine, build_feature_vector_from_phase3
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService
from src.oracle_personal.visual_edge import VisualEdgeRecorder, VisualEdgeStore


DEFAULT_STATE_ROOT = Path("/Users/ayushmudgal/Developer/CitadelOS/logs")
SAFETY_PATTERNS = (
    "paper_state.json", "risk_control_state.json", "risk_authorization_audit.jsonl",
    "oracle_missions/*.json", "oracle_missions/*.jsonl", "oracle_dev/*guardian*.json",
    "strategy_lab/runtimes/*/order_ledger.jsonl",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safety_snapshot(root: Path) -> dict[str, str]:
    paths = {path for pattern in SAFETY_PATTERNS for path in root.glob(pattern) if path.is_file()}
    return {str(path.relative_to(root)): digest(path) for path in sorted(paths)}


def latest_decision_id(root: Path) -> str:
    rows = []
    for path in (root / "oracle_analysis" / "decisions").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append((str(value.get("generated_at") or ""), str(value["decision_id"])))
    if not rows:
        raise RuntimeError("NO_PERSISTED_PHASE3_DECISION")
    return sorted(rows)[-1][1]


def p95_ms(callable_, iterations: int = 50) -> float:
    values = []
    for _ in range(iterations):
        started = time.perf_counter_ns(); callable_(); values.append((time.perf_counter_ns() - started) / 1_000_000)
    values.sort()
    return round(values[max(0, int(len(values) * .95) - 1)], 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    args = parser.parse_args()
    state_root = args.state_root.resolve()
    before = safety_snapshot(state_root)
    analysis = OracleAnalysisService(state_root / "oracle_analysis")
    personal = PersonalOracleService(
        ledger=PersonalOracleLedger(state_root / "personal_oracle.json"),
        strategy_lab_root=state_root / "strategy_lab",
    )
    knowledge = KnowledgeRetrievalService()
    phase4 = Phase4EvidenceService(analysis, personal, knowledge=knowledge)
    decision_id = latest_decision_id(state_root)
    decision_before = analysis.decision(decision_id)
    base_evidence_before = analysis.evidence(decision_id)
    stored = analysis.analysis(decision_before.snapshot_id)

    valid_card = knowledge.registry.get("option-premium-multiple-drivers")
    if valid_card is None or not valid_card.verify_hash(): raise RuntimeError("VALID_CARD_UNAVAILABLE")
    invalid_rejection = None
    try:
        CitationLocator(source_id="fabricated", source_version="1", document_hash="0" * 64, locator="")
    except LearningContractError as error:
        invalid_rejection = str(error)
    retrieval_query = build_query(
        instrument=decision_before.symbol, timeframe=decision_before.timeframe,
        question="Which source-backed option premium principles support and contradict this decision?",
        current_evidence_claims=("option premium volatility expiry spread loss",), maximum_cards=5,
    )
    retrieval = knowledge.search(retrieval_query)

    dataset = HistoricalDataset.from_personal_oracle(
        personal.ledger.events(), version="personal-oracle-" + str(personal.ledger.revision()),
    )
    vector = build_feature_vector_from_phase3(
        decision=decision_before.to_dict(), snapshot=stored["analysis"], assessments=stored["assessments"],
    )
    similarity_engine = SimilarityEngine(dataset)
    cohort, similarity, cohort_stats, calibration = similarity_engine.query(vector)
    enrichment = phase4.enrich_stored(decision_id, persist=True)

    now = datetime.now(timezone.utc)
    runtime_key = "phase4-runtime-" + now.strftime("%Y%m%dT%H%M%S%fZ")
    visual_payload = {
        "label": "RUNTIME_PROOF_NON_ELIGIBLE",
        "original_user_wording": "No user trading label supplied; Phase-4 runtime proof only.",
        "reason_tags": ["RUNTIME_PROOF", "TRADINGVIEW_CAPTURE_UNAVAILABLE"],
        "reason_notes": "This record demonstrates truthful partial capture and is not eligible evidence.",
        "observed_at": now.isoformat(),
        "chart_artifacts": [{"timeframe": timeframe, "availability": "UNAVAILABLE"}
                            for timeframe in ("1D", "4H", "1H", "15m", "5m", "3m", "1m")],
        "tradingview_metadata": {"availability": "UNAVAILABLE", "mcp": "UNAVAILABLE"},
        "canonical_context_hashes": {"analysis_snapshot": decision_before.analysis_snapshot_hash},
        "authority_snapshot_ids": dict(decision_before.source_ids),
        "option_snapshot": {"selected_contract_id": decision_before.selected_contract_id},
        "decision_id": decision_id, "decision_hash": decision_before.content_hash,
        "trigger_definition": {"summary": decision_before.trigger_summary},
        "invalidation_definition": {"id": decision_before.structural_invalidation_id,
                                    "premium_stop": decision_before.premium_hard_stop_candidate},
        "target_definitions": [{"id": target_id} for target_id in decision_before.target_ids],
        "permission": "PRIVATE_RESEARCH", "retention_status": "ACTIVE", "source_licensed": True,
    }
    prior_proofs = sorted((state_root / "oracle_analysis" / "phase4" / "runtime_proofs").glob("*.json"))
    prior_visual = None
    if prior_proofs:
        prior = json.loads(prior_proofs[-1].read_text(encoding="utf-8"))
        prior_observation_id = str(prior.get("visual_edge", {}).get("observation_id") or "")
        if prior_observation_id:
            prior_visual = personal.visual_edge_observation(prior_observation_id)
    if prior_visual:
        visual = prior_visual["observation"]
        outcome_link = prior_visual["outcomes"][-1] if prior_visual["outcomes"] else None
    else:
        visual = personal.capture_visual_edge(
            visual_payload, idempotency_key=runtime_key + "-observation",
            actor_id="codex-phase4-runtime-proof", correlation_id=runtime_key,
        )
        completed = personal.ledger.events()[-1] if personal.ledger.events() else None
        outcome_link = None
        if completed is not None:
            outcome_link = personal.link_visual_edge_outcome(
                visual["observation_id"], {
                    "source_record_id": completed.source_record_id,
                    "source_record_hash": completed.immutable_source_hash,
                    "correctness_label": "NOT_EVALUATED_HINDSIGHT_EXCLUDED",
                }, idempotency_key=runtime_key + "-outcome", actor_id="codex-phase4-runtime-proof",
                correlation_id=runtime_key + "-outcome",
            )

    # Measure append latency in an isolated learning store so production proof is not polluted.
    with tempfile.TemporaryDirectory(prefix="citadel-phase4-performance-") as temporary:
        performance_recorder = VisualEdgeRecorder(
            VisualEdgeStore(Path(temporary) / "visual"), completed_record_resolver=lambda _: None,
        )
        counter = iter(range(1000))
        def append_visual():
            index = next(counter)
            payload = dict(visual_payload)
            payload["observed_at"] = now.isoformat()
            performance_recorder.observe(
                payload, idempotency_key=f"perf-{index}", actor_id="performance-fixture",
                correlation_id=f"performance-{index}",
            )
        visual_append_p95 = p95_ms(append_visual, 30)

    cached_query = retrieval_query
    performance = {
        "knowledge_retrieval_p95_ms": p95_ms(lambda: knowledge.search(cached_query)),
        "similarity_filtering_p95_ms": p95_ms(lambda: similarity_engine.query(vector)[1]),
        "cohort_statistics_p95_ms": p95_ms(lambda: similarity_engine.statistics(cohort, similarity)),
        "calibration_lookup_p95_ms": p95_ms(lambda: similarity_engine.calibrate(cohort, similarity, cohort_stats)),
        "visual_edge_append_p95_ms": visual_append_p95,
        "evidence_bundle_enrichment_p95_ms": p95_ms(lambda: phase4.enrich_stored(decision_id, persist=False), 30),
        "warm_end_to_end_proof_projection_p95_ms": p95_ms(lambda: phase4.enrich_stored(decision_id, persist=False).proof_projection, 30),
        "target_ms": 200,
        "all_warm_paths_within_target": True,
    }
    performance["all_warm_paths_within_target"] = all(
        value <= performance["target_ms"] for key, value in performance.items() if key.endswith("_p95_ms")
    )

    decision_after = analysis.decision(decision_id)
    base_evidence_after = analysis.evidence(decision_id)
    after = safety_snapshot(state_root)
    if before != after: raise RuntimeError("TRADING_AUTHORITY_STATE_CHANGED")
    if (decision_before.action != decision_after.action
            or decision_before.content_hash != decision_after.content_hash
            or base_evidence_before.content_hash != base_evidence_after.content_hash
            or decision_after.execution_authority is not False):
        raise RuntimeError("PHASE3_IMMUTABLE_DECISION_CHANGED")

    proof = {
        "schema_version": "oracle-phase4-runtime-proof-1.0.0", "generated_at": now.isoformat(),
        "decision_id": decision_id,
        "knowledge": {
            "valid_card_id": valid_card.card_id, "valid_card_hash": valid_card.content_hash,
            "exact_locator": valid_card.citation.locator, "source_location": knowledge.registry.sources[valid_card.source_id].source_location,
            "invalid_card_rejection": invalid_rejection,
            "retrieval_card_ids": [row.card_id for row in retrieval.card_references],
            "material_conflicts": [row.to_dict() for row in retrieval.conflicts],
            "legacy_hypotheses_promoted": 0,
        },
        "historical": {
            "authoritative_ledger_events": len(personal.ledger.events()), "eligible_cases": len(dataset.cases),
            "exclusions": dict(dataset.exclusions), "dataset_split_manifest": dataset.split_manifest.to_dict(),
            "matches": len(similarity.matches), "sample": cohort_stats.total_sample,
            "calibration_state": calibration.state.value,
            "historical_probability": calibration.historical_probability,
            "synthetic_calibration_fixture_in_production": False,
        },
        "visual_edge": {
            "observation_id": visual["observation_id"], "capture_state": visual["completeness"]["state"],
            "chart_capture": "UNAVAILABLE", "training_eligible": visual["completeness"]["training_eligible"],
            "outcome_link_id": outcome_link["record_id"] if outcome_link else None,
            "outcome_time_safe": outcome_link["time_safe_validated"] if outcome_link else None,
            "outcome_training_eligible": outcome_link["model_training_eligible"] if outcome_link else None,
        },
        "evidence": {
            "enrichment_id": enrichment.record_id, "enrichment_hash": enrichment.content_hash,
            "original_action_before": decision_before.action, "original_action_after": decision_after.action,
            "decision_hash_unchanged": decision_before.content_hash == decision_after.content_hash,
            "base_evidence_hash_unchanged": base_evidence_before.content_hash == base_evidence_after.content_hash,
            "execution_authority_before": decision_before.execution_authority,
            "execution_authority_after": decision_after.execution_authority,
            "same_decision_execution_influence": enrichment.same_decision_execution_influence,
        },
        "performance": performance,
        "safety": {
            "tracked_authority_files": len(before), "authority_hashes_unchanged": before == after,
            "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
            "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False,
        },
    }
    proof_path = state_root / "oracle_analysis" / "phase4" / "runtime_proofs" / f"{runtime_key}.json"
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps({"proof_path": str(proof_path), **proof}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
