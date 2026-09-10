"""Deterministic filters, normalized distances and honest cohort statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from src.oracle.contracts.learning import (
    CalibrationReport, CalibrationState, CohortDefinition, CohortStatistics,
    DatasetSplitManifest, HistoricalCaseReference, HistoricalOutcomeRecord, OutcomeDefinition,
    SampleSufficiencyPolicy, SimilarityFeatureVector, SimilarityMatch,
    SimilarityResult, seal,
)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


_POLICY_TIME = "2026-08-01T00:00:00+00:00"

DEFAULT_OUTCOME_DEFINITION = seal(OutcomeDefinition(
    record_id="oracle-outcome-target-stop-1", outcome_definition_id="oracle-outcome-target-stop-1",
    version="1.0.0", created_at=_POLICY_TIME,
    provenance={"owner": "HistoricalSimilarityEngine", "immutable_decision_definitions_required": True},
    decision_policy_version="oracle-decision-3.0.0",
    target_definition="First immutable Decision Envelope natural target/premium target, without hindsight relabelling.",
    stop_definition="Immutable Decision Envelope structural invalidation/premium hard-stop mapping.",
    evaluation_window="Until first target, first stop, setup invalidation, or the original expiry/window.",
    tie_break_policy="Same-timestamp target and stop is NEITHER unless authoritative intrabar ordering exists.",
    include_costs=True,
    required_metrics=("TARGET_BEFORE_STOP", "STOP_BEFORE_TARGET", "NEITHER", "MFE", "MAE",
                      "TIME_TO_TARGET", "TIME_TO_STOP", "AFTER_COST_RETURN", "SLIPPAGE",
                      "INVALIDATION_TIMING", "PREMIUM_RESPONSE"),
))

DEFAULT_SAMPLE_POLICY = seal(SampleSufficiencyPolicy(
    record_id="oracle-sample-sufficiency-default-1", version="1.0.0", created_at=_POLICY_TIME,
    provenance={"owner": "HistoricalSimilarityEngine", "thresholds": "explicit configuration, not inferred"},
    minimum_total_sample=30, minimum_oos_sample=15, minimum_regime_coverage=1,
    minimum_expiry_bucket_coverage=1, minimum_time_bucket_coverage=1,
    maximum_missing_fraction=0.10, confidence_level=0.95, maximum_cohort_drift=0.20,
    recency_half_life_days=None, costs_required=True,
))

DEFAULT_DATASET_SPLIT = seal(DatasetSplitManifest(
    record_id="oracle-dataset-split-2026h1", version="1.0.0", created_at=_POLICY_TIME,
    provenance={"owner": "HistoricalSimilarityEngine", "boundary_timezone": "UTC"},
    dataset_version="personal-oracle-phase4-1", train_end="2026-06-30T23:59:59+00:00",
    oos_start="2026-07-01T00:00:00+00:00", source_record_hashes={},
    excluded_record_ids=(), exclusion_reasons={},
))


@dataclass(frozen=True)
class HistoricalDataset:
    version: str
    cases: tuple[HistoricalCaseReference, ...]
    outcomes: Mapping[str, HistoricalOutcomeRecord]
    exclusions: Mapping[str, int]
    source: str
    production: bool = True
    split_manifest: DatasetSplitManifest | None = None

    @classmethod
    def from_personal_oracle(cls, events: Iterable[Any], *, version: str) -> "HistoricalDataset":
        """Admit only completed, time-safe records with full pre-trade feature truth.

        Current legacy Personal Oracle trades ordinarily lack target-vs-stop ordering
        and the Phase-4 feature envelope.  They remain authoritative trade records,
        but are truthfully excluded from this narrower empirical cohort.
        """
        cases: list[HistoricalCaseReference] = []
        outcomes: dict[str, HistoricalOutcomeRecord] = {}
        excluded: dict[str, int] = {}
        excluded_records: dict[str, str] = {}
        def exclude(identity: str, reason: str) -> None:
            excluded[reason] = excluded.get(reason, 0) + 1
            excluded_records[identity or f"unknown-{len(excluded_records) + 1}"] = reason
        for event in events:
            source_type = str(getattr(event, "source_type", ""))
            identity = str(getattr(event, "oracle_event_id", ""))
            marker = " ".join((source_type, identity, str(getattr(event, "source_record_id", "")))).lower()
            if any(token in marker for token in ("fixture", "synthetic", "scaffold", "placeholder", "test")):
                exclude(identity, "RESEARCH_FIXTURE_OR_SCAFFOLD")
                continue
            context = dict(getattr(event, "entry_context", {}) or {})
            required = ("setup_version", "location_class", "vob_state", "ose_state", "argus_state",
                        "strike_relation", "expiry_bucket", "iv_regime", "delta_bucket",
                        "spread_liquidity_bucket", "trigger_definition_id",
                        "invalidation_definition_id", "target_definition_ids", "feature_versions")
            if not bool(getattr(event, "context_complete", False)) or any(context.get(key) in (None, "", [], {}) for key in required):
                exclude(identity, "INCOMPLETE_PRETRADE_FEATURES")
                continue
            # A WIN/LOSS label does not prove whether the immutable target or stop happened first.
            classification = str(context.get("phase4_outcome_classification") or "")
            if classification not in {"TARGET_BEFORE_STOP", "STOP_BEFORE_TARGET", "NEITHER"}:
                exclude(identity, "OUTCOME_DEFINITION_UNPROVEN")
                continue
            if not getattr(event, "planned_stop_price", None) or not getattr(event, "planned_target_price", None):
                exclude(identity, "IMMUTABLE_TARGET_STOP_UNAVAILABLE")
                continue
            # This branch is intentionally strict; new Phase-4-complete events can enter without backfilling legacy truth.
            vector = seal(SimilarityFeatureVector(
                record_id=f"feature-{identity}", version="oracle-similarity-features-1.0.0",
                created_at=str(getattr(event, "captured_at")), provenance={"source": source_type, "future_fields": False},
                symbol=str(getattr(event, "symbol")).upper(), setup_version=str(context["setup_version"]),
                timeframe_alignment=tuple(context.get("timeframe_alignment") or (getattr(event, "timeframe", "UNKNOWN"),)),
                regime=str(getattr(event, "market_regime") or context.get("market_regime") or "UNKNOWN"),
                location_class=str(context["location_class"]), structural_claims=tuple(context.get("structural_claims") or ()),
                vob_state=str(context["vob_state"]), ose_state=str(context["ose_state"]), argus_state=str(context["argus_state"]),
                option_type=str(getattr(event, "option_side")), strike_relation=str(context["strike_relation"]),
                expiry_bucket=str(context["expiry_bucket"]), iv_regime=str(context["iv_regime"]),
                delta_bucket=str(context["delta_bucket"]), time_of_day_bucket=str(getattr(event, "time_bucket")),
                spread_liquidity_bucket=str(context["spread_liquidity_bucket"]),
                trigger_definition_id=str(context["trigger_definition_id"]),
                invalidation_definition_id=str(context["invalidation_definition_id"]),
                target_definition_ids=tuple(context["target_definition_ids"]), feature_versions=dict(context["feature_versions"]),
                numerical_features=dict(context.get("similarity_numerical_features") or {}),
                observed_at=str(getattr(event, "entry_at")),
            ))
            source_hash = str(getattr(event, "immutable_source_hash"))
            decision_id = str(context.get("decision_id") or "legacy-unlinked")
            decision_hash = str(context.get("decision_hash") or "")
            if len(decision_hash) != 64:
                exclude(identity, "IMMUTABLE_DECISION_REFERENCE_UNAVAILABLE")
                continue
            outcome_id = f"outcome-{identity}"
            outcome = seal(HistoricalOutcomeRecord(
                record_id=outcome_id, outcome_id=outcome_id, version=DEFAULT_OUTCOME_DEFINITION.version,
                created_at=str(getattr(event, "captured_at")), provenance={"authoritative": True, "source_type": source_type},
                source_record_id=str(getattr(event, "source_record_id")), source_record_hash=source_hash,
                decision_id=decision_id, decision_hash=decision_hash,
                outcome_definition_id=DEFAULT_OUTCOME_DEFINITION.outcome_definition_id,
                target_definition_from_decision=str(getattr(event, "planned_target_price")),
                stop_definition_from_decision=str(getattr(event, "planned_stop_price")), classification=classification,
                mfe=getattr(event, "mfe", None), mae=getattr(event, "mae", None),
                time_to_target_seconds=context.get("time_to_target_seconds"), time_to_stop_seconds=context.get("time_to_stop_seconds"),
                after_cost_return=context.get("after_cost_return"), slippage=getattr(event, "slippage", None),
                invalidation_timing_seconds=context.get("invalidation_timing_seconds"), premium_response=context.get("premium_response"),
                costs_included=getattr(event, "brokerage", None) is not None and getattr(event, "slippage", None) is not None,
                completed_at=str(getattr(event, "exit_at")),
            ))
            split = "OOS" if str(getattr(event, "entry_at")) >= DEFAULT_DATASET_SPLIT.oos_start else "TRAIN"
            case = seal(HistoricalCaseReference(
                record_id=f"case-{identity}", case_id=f"case-{identity}", version="oracle-historical-case-1.0.0",
                created_at=str(getattr(event, "captured_at")), provenance={"authoritative": True, "production": True},
                source_record_id=str(getattr(event, "source_record_id")), source_record_hash=source_hash,
                feature_vector=vector, split=split, data_completeness=float(getattr(event, "context_completeness_percentage", 100)) / 100,
                outcome_record_id=outcome.outcome_id, outcome_record_hash=outcome.content_hash, production_eligible=True,
            ))
            cases.append(case); outcomes[outcome_id] = outcome
        split_manifest = seal(DatasetSplitManifest(
            record_id="dataset-split-" + _hash({"version": version, "cases": [row.case_id for row in cases]})[:24],
            version=DEFAULT_DATASET_SPLIT.version, created_at=_POLICY_TIME,
            provenance={"policy_id": DEFAULT_DATASET_SPLIT.record_id, "legacy_relabelling": False},
            dataset_version=version, train_end=DEFAULT_DATASET_SPLIT.train_end,
            oos_start=DEFAULT_DATASET_SPLIT.oos_start,
            source_record_hashes={row.source_record_id: row.source_record_hash for row in cases},
            excluded_record_ids=tuple(sorted(excluded_records)), exclusion_reasons=excluded_records,
        ))
        return cls(version=version, cases=tuple(cases), outcomes=outcomes, exclusions=excluded,
                   source="PersonalOracleLedger.authoritative_completed_trade", production=True,
                   split_manifest=split_manifest)


class SimilarityEngine:
    METHOD_VERSION = "oracle-transparent-similarity-1.0.0"
    EXACT_FIELDS = ("symbol", "setup_version", "regime", "location_class", "option_type",
                    "strike_relation", "expiry_bucket", "iv_regime", "delta_bucket",
                    "time_of_day_bucket", "spread_liquidity_bucket")
    REQUIRED_EXACT = ("symbol", "setup_version", "option_type", "expiry_bucket",
                      "iv_regime", "time_of_day_bucket", "spread_liquidity_bucket")
    DEFAULT_WEIGHTS = {"spot_distance_atr": 0.30, "delta_abs": 0.25, "iv_percentile": 0.20,
                       "spread_pct": 0.15, "minutes_to_close_norm": 0.10}

    def __init__(self, dataset: HistoricalDataset, *, policy: SampleSufficiencyPolicy = DEFAULT_SAMPLE_POLICY,
                 outcome_definition: OutcomeDefinition = DEFAULT_OUTCOME_DEFINITION):
        if dataset.production and any(
            not row.production_eligible
            or bool(row.provenance.get("fixture"))
            or any(token in " ".join((row.case_id, row.source_record_id)).lower()
                   for token in ("fixture", "synthetic", "scaffold", "placeholder", "test"))
            for row in dataset.cases
        ):
            raise ValueError("NON_PRODUCTION_CASE_IN_PRODUCTION_DATASET")
        if dataset.production and (dataset.split_manifest is None or not dataset.split_manifest.verify_hash()):
            raise ValueError("PRODUCTION_DATASET_SPLIT_MANIFEST_REQUIRED")
        self.dataset = dataset
        self.policy = policy
        self.outcome_definition = outcome_definition

    def query(self, vector: SimilarityFeatureVector, *, maximum_distance: float = 0.45) -> tuple[CohortDefinition, SimilarityResult, CohortStatistics, CalibrationReport]:
        cohort_id = "cohort-" + _hash({
            "query": vector.content_hash, "dataset": self.dataset.version,
            "outcome": self.outcome_definition.content_hash,
            "split": self.dataset.split_manifest.content_hash if self.dataset.split_manifest else "TEST_FIXTURE",
        })[:24]
        cohort = seal(CohortDefinition(
            record_id=cohort_id, cohort_id=cohort_id,
            version="oracle-cohort-1.0.0", created_at=vector.created_at,
            provenance={"method": self.METHOD_VERSION, "feature_weights_published": True,
                        "dataset_split_manifest_hash": self.dataset.split_manifest.content_hash if self.dataset.split_manifest else None},
            query_feature_hash=vector.content_hash, outcome_definition_id=self.outcome_definition.outcome_definition_id,
            dataset_version=self.dataset.version,
            exact_filters={name: str(getattr(vector, name)) for name in self.REQUIRED_EXACT},
            relaxed_filters={name: (str(getattr(vector, name)),) for name in self.EXACT_FIELDS if name not in self.REQUIRED_EXACT},
            numerical_weights=self.DEFAULT_WEIGHTS, maximum_distance=maximum_distance,
        ))
        matches: list[SimilarityMatch] = []
        excluded = dict(self.dataset.exclusions)
        for case in self.dataset.cases:
            candidate = case.feature_vector
            if any(getattr(candidate, name) != getattr(vector, name) for name in self.REQUIRED_EXACT):
                excluded["REQUIRED_EXACT_FILTER"] = excluded.get("REQUIRED_EXACT_FILTER", 0) + 1
                continue
            exact, differing = [], {}
            categorical_penalty = 0.0
            for name in self.EXACT_FIELDS:
                left, right = getattr(vector, name), getattr(candidate, name)
                if left == right:
                    exact.append(name)
                else:
                    differing[name] = {"query": left, "case": right}
                    categorical_penalty += 0.05
            numerical_penalty = 0.0
            missing_weight = 0.0
            for name, weight in self.DEFAULT_WEIGHTS.items():
                left, right = vector.numerical_features.get(name), candidate.numerical_features.get(name)
                if left is None or right is None:
                    missing_weight += weight
                    differing[name] = {"query": left, "case": right, "missing": True}
                else:
                    delta = abs(float(left) - float(right))
                    numerical_penalty += min(1.0, delta) * weight
                    if delta == 0:
                        exact.append(name)
                    else:
                        differing[name] = {"query": left, "case": right, "normalized_difference": delta}
            distance = round(categorical_penalty + numerical_penalty + missing_weight, 6)
            if distance > maximum_distance:
                excluded["DISTANCE_EXCEEDED"] = excluded.get("DISTANCE_EXCEEDED", 0) + 1
                continue
            tier = "EXACT" if not differing else "RELAXED"
            matches.append(SimilarityMatch(
                case_id=case.case_id, tier=tier, distance=distance, exact_features=tuple(sorted(exact)),
                differing_features=differing,
                reasons=(f"Required exact fields matched: {', '.join(self.REQUIRED_EXACT)}.",
                         f"Published weighted distance {distance:.6f} <= {maximum_distance:.6f}."),
                split=case.split, data_completeness=case.data_completeness,
                source_record_id=case.source_record_id, source_record_hash=case.source_record_hash,
            ))
        matches.sort(key=lambda row: (row.distance, row.case_id))
        result = seal(SimilarityResult(
            record_id="similarity-" + vector.content_hash[:24], version="oracle-similarity-result-1.0.0",
            created_at=vector.created_at, provenance={"dataset_source": self.dataset.source, "llm_used": False},
            query_feature_hash=vector.content_hash, cohort_id=cohort.cohort_id, dataset_version=self.dataset.version,
            outcome_definition_id=self.outcome_definition.outcome_definition_id, matches=tuple(matches),
            excluded_counts=excluded, method_version=self.METHOD_VERSION,
        ))
        statistics = self.statistics(cohort, result)
        calibration = self.calibrate(cohort, result, statistics)
        return cohort, result, statistics, calibration

    def statistics(self, cohort: CohortDefinition, result: SimilarityResult) -> CohortStatistics:
        outcomes = [self.dataset.outcomes[self._case(match.case_id).outcome_record_id] for match in result.matches]
        count = lambda state: sum(row.classification == state for row in outcomes)
        target, stop, neither = count("TARGET_BEFORE_STOP"), count("STOP_BEFORE_TARGET"), count("NEITHER")
        decisive = target + stop
        rate = target / decisive if decisive else None
        interval = self._wilson(target, decisive, self.policy.confidence_level) if decisive else None
        caveats = []
        if not outcomes: caveats.append("No authoritative Phase-4-complete historical cases matched.")
        if self.dataset.exclusions: caveats.append("Legacy, fixture/scaffold, incomplete or outcome-unproven records were excluded.")
        values = lambda name: [float(getattr(row, name)) for row in outcomes if getattr(row, name) is not None]
        average = lambda rows: round(sum(rows) / len(rows), 8) if rows else None
        missing_slots = sum(sum(getattr(row, name) is None for name in ("mfe", "mae", "after_cost_return", "slippage")) for row in outcomes)
        missing_fraction = missing_slots / (len(outcomes) * 4) if outcomes else 1.0
        return seal(CohortStatistics(
            record_id="statistics-" + cohort.cohort_id, version="oracle-cohort-statistics-1.0.0",
            created_at=result.created_at, provenance={"outcome_definition_hash": self.outcome_definition.content_hash},
            cohort_id=cohort.cohort_id, total_sample=len(outcomes), oos_sample=sum(match.split == "OOS" for match in result.matches),
            target_before_stop=target, stop_before_target=stop, neither=neither, target_rate=rate,
            confidence_interval=interval, mean_mfe=average(values("mfe")), mean_mae=average(values("mae")),
            mean_time_to_target_seconds=average(values("time_to_target_seconds")),
            mean_time_to_stop_seconds=average(values("time_to_stop_seconds")),
            mean_after_cost_return=average(values("after_cost_return")), mean_slippage=average(values("slippage")),
            costs_included=bool(outcomes) and all(row.costs_included for row in outcomes),
            missing_fraction=missing_fraction, caveats=tuple(caveats),
        ))

    def calibrate(self, cohort: CohortDefinition, result: SimilarityResult, stats: CohortStatistics) -> CalibrationReport:
        state = CalibrationState.NOT_AVAILABLE
        probability = None; brier = None; error = None; drift = None
        caveats = list(stats.caveats)
        matches_by_split = {split: [match for match in result.matches if match.split == split] for split in ("TRAIN", "OOS")}
        matched_cases = [self._case(match.case_id) for match in result.matches]
        coverage = {
            "regime": len({row.feature_vector.regime for row in matched_cases}),
            "expiry": len({row.feature_vector.expiry_bucket for row in matched_cases}),
            "time": len({row.feature_vector.time_of_day_bucket for row in matched_cases}),
        }
        coverage_failed = (coverage["regime"] < self.policy.minimum_regime_coverage
                           or coverage["expiry"] < self.policy.minimum_expiry_bucket_coverage
                           or coverage["time"] < self.policy.minimum_time_bucket_coverage)
        if (stats.total_sample < self.policy.minimum_total_sample
                or stats.missing_fraction > self.policy.maximum_missing_fraction or coverage_failed):
            state = CalibrationState.INSUFFICIENT_SAMPLE
            caveats.append(f"Policy requires total>={self.policy.minimum_total_sample}, OOS>={self.policy.minimum_oos_sample}, missing<={self.policy.maximum_missing_fraction:.2f}.")
            if coverage_failed: caveats.append(f"Coverage failed: {coverage}.")
        elif stats.oos_sample == 0:
            state = CalibrationState.IN_SAMPLE_ONLY
        elif stats.oos_sample < self.policy.minimum_oos_sample:
            state = CalibrationState.OOS_UNCALIBRATED
        elif self.policy.costs_required and not stats.costs_included:
            state = CalibrationState.DEGRADED; caveats.append("Cost/slippage inclusion required by policy.")
        elif not matches_by_split["TRAIN"]:
            state = CalibrationState.OOS_UNCALIBRATED; caveats.append("No training baseline exists for OOS calibration.")
        else:
            outcomes = lambda rows: [self.dataset.outcomes[self._case(match.case_id).outcome_record_id] for match in rows]
            train = outcomes(matches_by_split["TRAIN"]); oos = outcomes(matches_by_split["OOS"])
            train_decisive = [row for row in train if row.classification != "NEITHER"]
            oos_decisive = [row for row in oos if row.classification != "NEITHER"]
            if not train_decisive or not oos_decisive:
                state = CalibrationState.OOS_UNCALIBRATED
            else:
                train_rate = sum(row.classification == "TARGET_BEFORE_STOP" for row in train_decisive) / len(train_decisive)
                oos_rate = sum(row.classification == "TARGET_BEFORE_STOP" for row in oos_decisive) / len(oos_decisive)
                brier = sum((train_rate - (row.classification == "TARGET_BEFORE_STOP")) ** 2 for row in oos_decisive) / len(oos_decisive)
                error = abs(train_rate - oos_rate); drift = error
                if drift > self.policy.maximum_cohort_drift:
                    state = CalibrationState.DEGRADED
                elif error <= 0.10:
                    state = CalibrationState.OOS_CALIBRATED; probability = oos_rate
                elif error <= 0.20:
                    state = CalibrationState.OOS_CALIBRATED_WEAK; probability = oos_rate
                else:
                    state = CalibrationState.OOS_UNCALIBRATED
        return seal(CalibrationReport(
            record_id="calibration-" + cohort.cohort_id, version="oracle-calibration-1.0.0",
            created_at=result.created_at, provenance={"policy_hash": self.policy.content_hash, "llm_used": False},
            cohort_id=cohort.cohort_id, cohort_statistics_hash=stats.content_hash,
            policy_id=self.policy.record_id, state=state, historical_probability=probability,
            numerator=stats.target_before_stop, denominator=stats.target_before_stop + stats.stop_before_target,
            confidence_interval=stats.confidence_interval,
            oos_status=f"{stats.oos_sample}/{stats.total_sample} OOS", costs_included=stats.costs_included,
            cohort_version=cohort.version, brier_score=brier, calibration_error=error, cohort_drift=drift,
            caveats=tuple(caveats),
        ))

    def _case(self, case_id: str) -> HistoricalCaseReference:
        return next(row for row in self.dataset.cases if row.case_id == case_id)

    @staticmethod
    def _wilson(successes: int, total: int, confidence: float) -> tuple[float, float]:
        # Explicit normal quantiles for the supported policy levels; default is 95%.
        z = 1.6448536269514722 if confidence <= .90 else 1.959963984540054 if confidence <= .95 else 2.5758293035489004
        p = successes / total; denominator = 1 + z * z / total
        centre = (p + z * z / (2 * total)) / denominator
        margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
        return round(max(0.0, centre - margin), 8), round(min(1.0, centre + margin), 8)


def build_feature_vector_from_phase3(*, decision: Mapping[str, Any], snapshot: Mapping[str, Any],
                                     assessments: Mapping[str, Any]) -> SimilarityFeatureVector:
    """Freeze only information present at the Phase-3 decision timestamp."""
    option = dict((assessments.get("option_capture") or {}))
    underlying = dict((assessments.get("underlying") or {}))
    records = dict(snapshot.get("source_records") or {})
    candidate_id = decision.get("selected_contract_id")
    candidate = next((dict(row) for row in snapshot.get("candidate_contracts") or () if row.get("contract_id") == candidate_id), {})
    ose = dict(records.get("ose") or {}); argus = dict(records.get("argus_tactical") or {}); vob = dict(records.get("vob") or {})
    delta = candidate.get("delta"); iv = candidate.get("iv"); spread = candidate.get("spread_pct")
    def bucket(value, cuts, labels, missing="UNKNOWN"):
        if value is None: return missing
        for cut, label in zip(cuts, labels):
            if float(value) < cut: return label
        return labels[-1]
    observed = str(decision.get("source_timestamp") or snapshot.get("source_timestamp"))
    time_value = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    return seal(SimilarityFeatureVector(
        record_id="feature-" + str(decision["decision_id"]), version="oracle-similarity-features-1.0.0",
        created_at=str(decision.get("generated_at")), provenance={"decision_hash": decision["content_hash"], "future_fields": False},
        symbol=str(decision["symbol"]).upper(), setup_version=str(decision.get("policy_version") or "UNKNOWN"),
        timeframe_alignment=tuple(sorted((snapshot.get("source_records") or {}).get("context_lanes", {}).keys())),
        regime=str(dict(records.get("canonical_market_assessment") or {}).get("regime") or "UNKNOWN"),
        location_class=str(underlying.get("location_quality") or "UNKNOWN"),
        structural_claims=tuple(item.get("trigger_type") for item in underlying.get("triggers") or ()),
        vob_state=str(vob.get("status") or vob.get("availability") or "UNKNOWN"),
        ose_state=str(dict(ose.get("duel") or {}).get("state") or "UNKNOWN"),
        argus_state=str(argus.get("direction") or argus.get("bias") or "UNKNOWN"),
        option_type=str(candidate.get("option_type") or option.get("requested_side") or "NONE"),
        strike_relation=bucket(abs(float(candidate.get("distance_atm") or 0)), (1, 51, float("inf")), ("ATM", "NEAR", "FAR")),
        expiry_bucket=(lambda days: "DTE_0" if days <= 0 else "DTE_1_7" if days <= 7 else "DTE_8_PLUS")(
            (datetime.fromisoformat(str(snapshot["expiry"]) + "T00:00:00+00:00").date() - time_value.date()).days
        ) if snapshot.get("expiry") else "UNKNOWN",
        iv_regime=bucket(iv, (15, 30, float("inf")), ("LOW", "NORMAL", "HIGH")),
        delta_bucket=bucket(abs(float(delta)) if delta is not None else None, (.35, .65, float("inf")), ("LOW", "MID", "HIGH")),
        time_of_day_bucket=f"HOUR_{time_value.hour:02d}",
        spread_liquidity_bucket=bucket(spread, (2, 8, float("inf")), ("TIGHT", "NORMAL", "WIDE")),
        trigger_definition_id=str((underlying.get("triggers") or [{}])[0].get("trigger_id") if underlying.get("triggers") else "UNAVAILABLE"),
        invalidation_definition_id=str(decision.get("structural_invalidation_id") or "UNAVAILABLE"),
        target_definition_ids=tuple(decision.get("target_ids") or ()),
        feature_versions={"similarity": "1.0.0", "decision": str(decision.get("policy_version"))},
        numerical_features={
            "spot_distance_atr": 0.0, "delta_abs": abs(float(delta)) if delta is not None else None,
            "iv_percentile": min(1.0, float(iv) / 100) if iv is not None else None,
            "spread_pct": min(1.0, float(spread) / 100) if spread is not None else None,
            "minutes_to_close_norm": min(1.0, float(snapshot.get("time_remaining_seconds") or 0) / 22500),
        }, observed_at=observed,
    ))
