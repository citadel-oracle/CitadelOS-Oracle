"""Linked Phase-4 proof over immutable Phase-3 decisions and evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
import re
from threading import RLock
import tempfile
from typing import Any, Mapping

from src.oracle.contracts.learning import DecisionEvidenceEnrichment, seal
from src.oracle.knowledge_engine import KnowledgeRetrievalService, build_query
from src.oracle.similarity import HistoricalDataset, SimilarityEngine, build_feature_vector_from_phase3


class Phase4EvidenceUnavailable(LookupError):
    pass


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,200}$")


def _safe_id(value: str) -> str:
    value = str(value)
    if not _SAFE_ID.fullmatch(value): raise Phase4EvidenceUnavailable("PHASE4_EVIDENCE_ID_INVALID")
    return value


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class Phase4EvidenceStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = RLock()

    def save(self, enrichment: DecisionEvidenceEnrichment, *, similarity: Mapping[str, Any],
             statistics: Mapping[str, Any], calibration: Mapping[str, Any]) -> None:
        payloads = {
            self.root / "enrichments" / enrichment.decision_id / f"{enrichment.record_id}.json": enrichment.to_dict(),
            self.root / "similarity" / enrichment.decision_id / f"{enrichment.similarity_result_hash}.json": dict(similarity),
            self.root / "cohorts" / f"{calibration['cohort_id']}.json": {
                "statistics": dict(statistics), "calibration": dict(calibration),
            },
        }
        with self._lock:
            for path, payload in payloads.items():
                if path.exists() and json.loads(path.read_text(encoding="utf-8")) != payload:
                    raise RuntimeError("IMMUTABLE_PHASE4_EVIDENCE_CONFLICT")
            for path, payload in payloads.items():
                if not path.exists(): _atomic(path, payload)

    def enrichment(self, decision_id: str) -> dict[str, Any] | None:
        return self._latest(self.root / "enrichments" / _safe_id(decision_id))

    def similarity(self, decision_id: str) -> dict[str, Any] | None:
        decision_id = _safe_id(decision_id)
        enrichment = self.enrichment(decision_id)
        if enrichment is None: return None
        return self._read_optional(
            self.root / "similarity" / decision_id / f"{enrichment['similarity_result_hash']}.json"
        )

    def cohort(self, cohort_id: str) -> dict[str, Any] | None:
        return self._read_optional(self.root / "cohorts" / f"{_safe_id(cohort_id)}.json")

    @classmethod
    def _latest(cls, root: Path) -> dict[str, Any] | None:
        if not root.exists(): return None
        paths = tuple(root.glob("*.json"))
        if not paths: return None
        return cls._read_optional(max(paths, key=lambda path: (path.stat().st_mtime_ns, path.name)))

    @staticmethod
    def _read_optional(path: Path) -> dict[str, Any] | None:
        if not path.exists(): return None
        try: value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise Phase4EvidenceUnavailable("PHASE4_EVIDENCE_UNAVAILABLE") from error
        return value if isinstance(value, dict) else None


class Phase4EvidenceService:
    """Advisory enrichment; Phase-3 action is an asserted immutable input."""

    def __init__(self, analysis_service, personal_oracle, *, knowledge=None, store=None):
        self.analysis_service = analysis_service
        self.personal_oracle = personal_oracle
        self.knowledge = knowledge or KnowledgeRetrievalService()
        self.store = store or Phase4EvidenceStore(analysis_service.store.root / "phase4")

    def enrich_result(self, result, *, persist: bool = True, telemetry=None) -> DecisionEvidenceEnrichment:
        payload = result.to_dict()
        return self._enrich(
            decision=payload["decision"], evidence=payload["evidence"], snapshot=payload["analysis"],
            assessments=payload["assessments"], persist=persist, telemetry=telemetry,
        )

    def enrich_stored(self, decision_id: str, *, persist: bool = True) -> DecisionEvidenceEnrichment:
        decision = self.analysis_service.decision(decision_id).to_dict()
        evidence = self.analysis_service.evidence(decision_id).to_dict()
        stored = self.analysis_service.analysis(decision["snapshot_id"])
        return self._enrich(decision=decision, evidence=evidence, snapshot=stored["analysis"],
                            assessments=stored["assessments"], persist=persist)

    def _enrich(self, *, decision, evidence, snapshot, assessments, persist, telemetry=None):
        query = build_query(
            # A decision policy version is not a market setup classification.
            # Until Phase-3 emits a canonical setup_type, leave this filter open.
            instrument=decision["symbol"], setup_type=None,
            market_regime=dict(snapshot.get("source_records", {}).get("canonical_market_assessment") or {}).get("regime"),
            # MULTI is an envelope scope, not a literal card timeframe.  Keep
            # the filter open so cards for its constituent lanes can compete.
            timeframe=None if decision.get("timeframe") == "MULTI" else decision.get("timeframe"),
            option_buying_relevance="HIGH",
            current_evidence_claims=tuple(item.get("claim", "") for item in evidence.get("items") or ()),
            question="Which verified option-premium principles support or challenge the current evidence?",
            maximum_cards=5,
        )
        knowledge_started = perf_counter()
        knowledge = self.knowledge.search(query)
        if telemetry is not None:
            telemetry("knowledge_retrieval", (perf_counter() - knowledge_started) * 1000, error=False)
        ledger = self.personal_oracle.ledger
        similarity_started = perf_counter()
        dataset = HistoricalDataset.from_personal_oracle(
            ledger.events(), version="personal-oracle-" + str(ledger.revision()),
        )
        vector = build_feature_vector_from_phase3(decision=decision, snapshot=snapshot, assessments=assessments)
        cohort, similarity, statistics, calibration = SimilarityEngine(dataset).query(vector)
        if telemetry is not None:
            telemetry("similarity_calibration", (perf_counter() - similarity_started) * 1000, error=False)
        eligible_visual = self.personal_oracle.visual_edge.store.eligible_observation_ids()
        cards = [self.knowledge.registry.cards[ref.card_id] for ref in knowledge.card_references]
        projection = {
            "principle": [{
                "card_id": card.card_id, "source": self.knowledge.registry.sources[card.source_id].title,
                "source_location": self.knowledge.registry.sources[card.source_id].source_location,
                "exact_locator": card.citation.locator, "permitted_excerpt": card.permitted_excerpt,
                "paraphrase": card.paraphrased_interpretation,
                "relevance": next(ref.relevance for ref in knowledge.card_references if ref.card_id == card.card_id),
                "failure_conditions": list(card.failure_conditions), "probability_source": False,
            } for card in cards],
            "principle_conflicts": [row.to_dict() for row in knowledge.conflicts],
            "current_evidence": {
                "supporting_facts": [row["explanation"] for row in evidence.get("items") or () if row.get("classification") == "SUPPORT"],
                "conflicts": [row["explanation"] for row in evidence.get("items") or () if row.get("classification") == "CONTRADICT"],
                "missing_inputs": list(evidence.get("missing_evidence") or ()),
                "freshness": decision.get("freshness_state"),
            },
            "historical_evidence": {
                "cohort": cohort.to_dict(), "matches": [row.to_dict() for row in similarity.matches],
                "statistics": statistics.to_dict(), "calibration": calibration.to_dict(),
                "historical_probability": calibration.historical_probability,
                "sample_insufficiency": calibration.state.value == "INSUFFICIENT_SAMPLE",
                "exclusions": dict(similarity.excluded_counts),
            },
            "personal_edge": {
                "eligible_observation_ids": list(eligible_visual),
                "hindsight_contaminated_examples_included": False,
            },
            "policy": {"same_decision_execution_influence": "ZERO", "execution_authority": False,
                       "decision_action_changed": False, "evidence_policy_version": "oracle-phase4-advisory-1.0.0"},
        }
        enrichment_identity = knowledge.content_hash[:12] + similarity.content_hash[:12] + calibration.content_hash[:12]
        enrichment = seal(DecisionEvidenceEnrichment(
            record_id="enrichment-" + decision["decision_id"] + "-" + enrichment_identity,
            version="oracle-evidence-enrichment-4.0.0",
            created_at=decision["generated_at"],
            provenance={"orchestrator": "Phase4EvidenceService", "phase3_contract_mutated": False,
                        "knowledge_probability_forbidden": True},
            decision_id=decision["decision_id"], decision_hash=decision["content_hash"],
            base_evidence_bundle_id=evidence["bundle_id"], base_evidence_bundle_hash=evidence["content_hash"],
            original_action=decision["action"], knowledge_result_hash=knowledge.content_hash,
            similarity_result_hash=similarity.content_hash, cohort_statistics_hash=statistics.content_hash,
            calibration_report_hash=calibration.content_hash, knowledge_references=knowledge.card_references,
            knowledge_conflicts=knowledge.conflicts, historical_probability=calibration.historical_probability,
            calibration_state=calibration.state, visual_edge_reference_ids=eligible_visual, proof_projection=projection,
        ))
        if decision["action"] != enrichment.original_action or decision.get("execution_authority") is not False:
            raise RuntimeError("PHASE4_DECISION_BOUNDARY_VIOLATION")
        if persist:
            persistence_started = perf_counter()
            self.store.save(enrichment, similarity={"cohort": cohort.to_dict(), "similarity": similarity.to_dict()},
                            statistics=statistics.to_dict(), calibration=calibration.to_dict())
            if telemetry is not None:
                telemetry("phase4_persistence", (perf_counter() - persistence_started) * 1000, error=False)
        return enrichment

    def evidence_projection(self, decision_id: str) -> dict[str, Any] | None:
        return self.store.enrichment(decision_id)

    def similarity_for_decision(self, decision_id: str) -> dict[str, Any]:
        stored = self.store.similarity(decision_id)
        if stored is not None: return stored
        enrichment = self.enrich_stored(decision_id, persist=False)
        return {"proof": enrichment.proof_projection["historical_evidence"], "persisted": False}
