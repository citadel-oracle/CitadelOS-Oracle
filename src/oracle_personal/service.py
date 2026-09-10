"""Read-oriented orchestration for Personal Oracle and its compact Lite feed."""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Optional

from src.execution.paper_state import PaperStateService

from .analytics import PersonalOracleAnalytics
from .behavior import BehaviorClassifier
from .capture import PersonalOracleCapture
from .coaching import BehavioralCoaching
from .ledger import DEFAULT_PATH, OracleLedgerError, PersonalOracleLedger
from .lite import PersonalOracleLite, StrategyLabOracleSource
from .second_brain import LocalObsidianVault, OracleSecondBrainService, SecondBrainStore
from .shadow import PersonalOracleShadow
from .visual_edge import VisualEdgeRecorder, VisualEdgeStore


PERFORMANCE_LEAK_TITLES = {
    "Rapid Reentry",
    "Loss Sequence Reentry",
    "Same Direction Repeat",
    "Same Setup Repeat",
    "Profit Surrender",
    "Early Exit",
    "Late Entry",
    "Chase Entry",
    "Oversized",
    "Session Violation",
    "Cooldown Violation",
}
LOGGER = logging.getLogger(__name__)


class PersonalOracleService:
    def __init__(self, paper_state=None, ledger=None, strategy_lab_root: Path | str = "logs/strategy_lab"):
        self.paper_state = paper_state or PaperStateService()
        self.ledger = ledger or PersonalOracleLedger()
        self.capture = PersonalOracleCapture(self.ledger)
        self.analytics = PersonalOracleAnalytics()
        self.classifier = BehaviorClassifier()
        self.coach = BehavioralCoaching()
        self.lite = PersonalOracleLite(self.ledger, StrategyLabOracleSource(strategy_lab_root))
        self.shadow = PersonalOracleShadow(self.ledger)
        second_brain_path = Path(os.environ.get(
            "CITADEL_ORACLE_SECOND_BRAIN_PATH",
            str(self.ledger.path.parent / "personal_oracle_second_brain.json"),
        ))
        vault_path = os.environ.get("CITADEL_OBSIDIAN_VAULT_PATH")
        production_ledger = (self.ledger.path.resolve() == DEFAULT_PATH.resolve()
                             or self.ledger.path.parent.name == "logs")
        if vault_path is None and production_ledger:
            try:
                config = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "knowledge_sync" / "config.json").read_text(encoding="utf-8"))
                vault_path = str(config.get("vault") or "") or None
            except (OSError, ValueError, json.JSONDecodeError):
                vault_path = None
        if vault_path is None and not production_ledger:
            vault_path = str(self.ledger.path.parent / "obsidian_vault")
        self.second_brain = OracleSecondBrainService(
            SecondBrainStore(second_brain_path),
            vault=LocalObsidianVault(vault_path) if vault_path else None,
            event_provider=self.ledger.events,
        )
        visual_root = self.ledger.path.parent / "personal_oracle_visual_edge"
        self.visual_edge = VisualEdgeRecorder(
            VisualEdgeStore(visual_root), completed_record_resolver=self._completed_record,
        )
        self.last_backfill: Optional[dict[str, int]] = None
        self.last_outcome_reconciliation: Optional[dict[str, int]] = None
        self.last_shadow_error: Optional[str] = None
        self._unlinked_outcome_ids: set[str] = set()
        self._summary_cache: Optional[dict[str, Any]] = None
        self._summary_revision = None
        self._cache_lock = RLock()

    def _completed_record(self, source_record_id: str):
        return next((row for row in self.ledger.events()
                     if row.source_record_id == source_record_id or row.oracle_event_id == source_record_id), None)

    def capture_visual_edge(self, raw: Mapping[str, Any], *, idempotency_key: str,
                            actor_id: str, correlation_id: str) -> dict[str, Any]:
        return self.visual_edge.observe(raw, idempotency_key=idempotency_key,
                                        actor_id=actor_id, correlation_id=correlation_id)

    def revise_visual_edge(self, observation_id: str, raw: Mapping[str, Any], *,
                           idempotency_key: str, actor_id: str, correlation_id: str,
                           expected_prior_version: int) -> dict[str, Any]:
        return self.visual_edge.revise(
            observation_id, raw, idempotency_key=idempotency_key, actor_id=actor_id,
            correlation_id=correlation_id, expected_prior_version=expected_prior_version,
        )

    def link_visual_edge_outcome(self, observation_id: str, raw: Mapping[str, Any], *,
                                 idempotency_key: str, actor_id: str,
                                 correlation_id: str) -> dict[str, Any]:
        return self.visual_edge.link_outcome(
            observation_id, raw, idempotency_key=idempotency_key,
            actor_id=actor_id, correlation_id=correlation_id,
        )

    def visual_edge_observation(self, observation_id: str) -> dict[str, Any] | None:
        return self.visual_edge.store.observation(observation_id)

    def backfill_authoritative(self, *, dry_run: bool = False) -> dict[str, int]:
        try:
            self.last_backfill = self.lite.backfill(dry_run=dry_run)
            if not dry_run:
                self.last_outcome_reconciliation = self.shadow.reconcile_outcomes(self.lite.source.records())
                if self.last_outcome_reconciliation.get("unlinked"):
                    self.last_shadow_error = "UNLINKED_OUTCOME"
                self._invalidate()
        except (OracleLedgerError, OSError, RuntimeError):
            self.last_backfill = {
                "discovered": 0, "valid": 0, "inserted": 0,
                "duplicate": 0, "skipped": 0, "invalid": 0,
            }
        return dict(self.last_backfill)

    def capture_shadow_advisory(self, candidate: Mapping[str, Any], *, source_event_id: str) -> bool:
        try:
            added = self.shadow.advise(candidate, source_event_id=source_event_id)
            self.last_shadow_error = None
        except (KeyError, TypeError, ValueError, OracleLedgerError, OSError) as error:
            self.last_shadow_error = type(error).__name__
            LOGGER.warning("Personal ORACLE shadow evaluation unavailable: %s", self.last_shadow_error)
            self._invalidate()
            return False
        if added:
            self._invalidate()
        return added

    def capture_closed_trade(self, raw: Mapping[str, Any], *, entry_context=None) -> bool:
        added = self.capture.capture_closed_trade(raw, entry_context=entry_context)
        if added:
            self._capture_second_brain_learning(
                source_record_id=str(raw.get("close_event_id") or ""),
            )
            self._invalidate()
        return added

    def ingest_strategy_lab_trade(self, trade: Mapping[str, Any], *, source_event_id: Optional[str] = None) -> bool:
        """Append one completed Strategy Lab trade without influencing execution."""

        try:
            added = self.lite.ingest_completed_trade(trade, source_event_id=source_event_id)
        except (KeyError, TypeError, ValueError, OracleLedgerError, OSError):
            return False
        if added:
            self._capture_second_brain_learning(
                source_record_id=str(trade.get("trade_id") or trade.get("position_id") or ""),
                source_event_id=source_event_id,
            )
            self._invalidate()
        try:
            linked = self.shadow.link_outcome(trade)
        except (KeyError, TypeError, ValueError, OracleLedgerError, OSError):
            linked = False
        if linked:
            self._invalidate()
        elif dict(trade.get("oracle_entry_context") or {}).get("candidate_signal_id"):
            trade_id = str(trade.get("trade_id") or trade.get("position_id") or "")
            if trade_id and not any(row.source_trade_id == trade_id for row in self.ledger.outcomes()):
                self._unlinked_outcome_ids.add(trade_id)
                self.last_shadow_error = "UNLINKED_OUTCOME"
                self._invalidate()
        return added

    def _capture_second_brain_learning(self, *, source_record_id: str,
                                       source_event_id: Optional[str] = None) -> None:
        try:
            event = next(
                row for row in reversed(self.ledger.events())
                if row.source_record_id == source_record_id
                or (source_event_id and row.source_event_id == source_event_id)
            )
            self.second_brain.record_completed_trade(event)
        except (StopIteration, OSError, RuntimeError, TypeError, ValueError) as error:
            LOGGER.warning("Phase-6B post-trade learning unavailable: %s", type(error).__name__)

    def second_brain_projection(self, decision: Mapping[str, Any], *,
                                knowledge: Optional[Mapping[str, Any]] = None,
                                context: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        return self.second_brain.project(decision, knowledge=knowledge, context=context)

    def second_brain_status(self) -> dict[str, Any]:
        return self.second_brain.status()

    def discover_strategies(self) -> tuple[dict[str, Any], ...]:
        return self.lite.discover_strategies()

    def import_legacy_history(self, source_path: Path | str, *, dry_run: bool = False) -> dict[str, int]:
        result = self.lite.import_legacy(source_path, dry_run=dry_run)
        if not dry_run:
            self._invalidate()
        return result

    def status(self) -> dict[str, Any]:
        result = self.summary()
        return {
            key: result.get(key)
            for key in (
                "status", "health", "readiness", "generated_at", "snapshot_version",
                "freshness", "execution_influence", "event_count", "maturity",
                "last_backfill", "warnings", "mode", "dataset", "schema_version",
                "complete_context_count", "last_event_at",
                "ingestion", "shadow",
            )
        }

    def summary(self) -> dict[str, Any]:
        try:
            revision = self.ledger.revision()
            with self._cache_lock:
                if self._summary_cache is not None and revision == self._summary_revision:
                    return deepcopy(self._summary_cache)
                result = self._build_compact_summary()
                self._summary_cache = deepcopy(result)
                self._summary_revision = self.ledger.revision()
                return result
        except (OracleLedgerError, OSError, RuntimeError) as error:
            return {
                "status": "UNAVAILABLE",
                "health": "UNAVAILABLE",
                "readiness": "UNAVAILABLE",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_version": 0,
                "freshness": {"state": "UNAVAILABLE", "age_seconds": None},
                "execution_influence": "ZERO",
                "error": str(error),
            }

    def findings(self):
        return self.analytics.findings(self.ledger.events())

    def segments(self):
        return self.analytics.segments(self.ledger.events())

    def recommendations(self):
        return self.analytics.recommendations(self.ledger.events())

    def behavior(self):
        events = self.ledger.events()
        observations = self.classifier.classify(events, self.ledger.enrichments())
        return self.coach.behavior(events, observations)

    def coaching(self):
        events = self.ledger.events()
        observations = self.classifier.classify(events, self.ledger.enrichments())
        return self.coach.coaching(events, observations)

    def scorecard(self):
        events = self.ledger.events()
        return self.coach.scorecard(self.classifier.classify(events, self.ledger.enrichments()))

    def trends(self):
        events = self.ledger.events()
        observations = self.classifier.classify(events, self.ledger.enrichments())
        return self.coach.trends(events, observations)

    def mistakes(self):
        observations = self.classifier.classify(self.ledger.events(), self.ledger.enrichments())
        counts: dict[str, int] = {}
        for observation in observations:
            for tag in observation.mistake_tags:
                counts[tag] = counts.get(tag, 0) + 1
        return {
            "status": "available",
            "mistakes": [
                {"tag": tag, "count": count}
                for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
            ],
        }

    def events(self, limit: int = 25) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 100))
        rows = sorted(self.ledger.events(), key=lambda event: event.exit_at, reverse=True)[:bounded]
        return {"status": "available", "limit": bounded, "events": [event.to_dict() for event in rows]}

    def _build_compact_summary(self) -> dict[str, Any]:
        events = self.ledger.events()
        document = self.ledger.load_document()
        classifications = self.ledger.classifications()
        observations = self.ledger.observations()
        classified_event_ids = {row.source_event_id for row in classifications}
        current_event_ids = {row.oracle_event_id for row in events}
        if events and classified_event_ids != current_event_ids:
            classifications, observations = self.lite.refresh_analysis()
            document = self.ledger.load_document()
        strategies = self.discover_strategies()
        strategy_ids = {row.strategy_id for row in events if row.strategy_id}
        active = [row for row in observations if row.status != "RESOLVED"]
        active.sort(key=lambda row: (
            {"CRITICAL": 0, "IMPORTANT": 1, "POSITIVE": 2, "INSIGHT": 3, "INFORMATIONAL": 4}.get(row.severity, 5),
            -row.confidence,
            row.observation_id,
        ))
        top = [row.to_dict() for row in active[:3]]
        statuses = self._strategy_statuses(strategies, events, active)
        manual_count = sum(bool(row.manual_action_source) for row in events)
        manual_status = "NOT_RECORDED" if manual_count == 0 else "RECORDED" if manual_count == len(events) else "PARTIAL"
        focus = self._today_focus(events, active)
        latest = max((row.exit_at for row in events), default=None)
        latest_event = max(events, key=lambda row: (row.exit_at, row.oracle_event_id), default=None)
        latest_ingest = max((row.captured_at for row in events), default=None)
        age = self._age_seconds(latest)
        ingest_age = self._age_seconds(latest_ingest)
        freshness_state = "NO_DATA" if latest is None else "FRESH" if age is not None and age <= 86_400 else "HISTORICAL"
        maturity = "MATURE" if len(events) >= 100 else "LEARNING" if events else "COLLECTING"
        strengths = [
            {"title": row.title, "sample_size": row.sample_size, "realized_impact": row.actual_realized_impact}
            for row in active if row.severity == "POSITIVE"
        ][:3]
        leaks = [
            {"title": row.title, "sample_size": row.sample_size, "realized_impact": row.actual_realized_impact}
            for row in active if row.severity in {"CRITICAL", "IMPORTANT"}
        ][:3]
        behavioral_observations = self.classifier.classify(events, self.ledger.enrichments())
        behavior = self.coach.behavior(events, behavioral_observations)
        behavior.pop("observations", None)
        legacy_summary = self.analytics.summary(events)
        scorecard = self.coach.scorecard(behavioral_observations)
        trends = self.coach.trends(events, behavioral_observations)
        hero = self._hero_summary(strategies, statuses, active, focus, scorecard, trends)
        strategy_scope = self._strategy_scope(strategies, events, active)
        classifications_by_event: dict[str, list[str]] = {}
        for row in classifications:
            classifications_by_event.setdefault(row.source_event_id, []).append(row.classification_type)
        trade_evidence = [
            {
                "strategy_id": row.strategy_id or "NOT_RECORDED",
                "strategy_family": row.strategy_family or "NOT_RECORDED",
                "symbol": row.symbol,
                "timeframe": row.timeframe or "NOT_RECORDED",
                "option_side": row.option_side,
                "source_record_id": row.source_record_id,
                "source_event_id": row.oracle_event_id,
                "outcome": row.outcome,
                "realized_pnl": row.realized_pnl,
                "classifications": classifications_by_event.get(row.oracle_event_id, [])[:8],
                "execution_integrity": (
                    "EXECUTION_DEFECT"
                    if "EXECUTION_DEFECT" in classifications_by_event.get(row.oracle_event_id, [])
                    else "VALID_STRATEGY_OUTCOME"
                ),
                "exit_at": row.exit_at,
            }
            for row in sorted(events, key=lambda event: event.exit_at, reverse=True)[:25]
        ]
        shadow = self.shadow.projection()
        shadow["prospective_scorecard"]["unlinked_outcomes"] = max(
            len(self._unlinked_outcome_ids),
            int((self.last_outcome_reconciliation or {}).get("unlinked") or 0),
        )
        shadow["status"] = "DEGRADED" if self.last_shadow_error else "READY" if shadow["latest_advisory"] else "COLLECTING"
        shadow["error_reason"] = self.last_shadow_error
        return {
            "status": "READY" if events else "LEARNING",
            "sample_size": len(events),
            "health": "HEALTHY",
            "readiness": "READY" if events else "INSUFFICIENT_DATA",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_version": int(document.get("snapshot_version") or 0),
            "freshness": {"state": freshness_state, "age_seconds": age, "latest_event_at": latest},
            "execution_influence": "ZERO",
            "advisory_only": True,
            "mode": "READ_ONLY_INTELLIGENCE",
            "dataset": "PERSONAL_ORACLE",
            "schema_version": 3,
            "ingestion": {
                "mode": latest_event.ingestion_mode if latest_event else "LEGACY",
                "label": "LIVE INGESTION" if latest_event and latest_event.ingestion_mode == "EVENT_DRIVEN" else "STARTUP-ONLY",
                "context_captured": bool(latest_event and latest_event.context_captured),
                "context_completeness_percentage": latest_event.context_completeness_percentage if latest_event else 0.0,
                "overall_context_completeness_percentage": round(
                    sum(row.context_completeness_percentage for row in events) / len(events), 2
                ) if events else 0.0,
                "missing_context_fields": list(latest_event.missing_context_fields) if latest_event else ["ENTRY_CONTEXT_ENVELOPE"],
                "source_event_id": latest_event.source_event_id if latest_event else None,
                "latest_oracle_ingest_timestamp": latest_ingest,
                "latest_trade_timestamp": latest,
                "freshness_status": "NO_DATA" if latest_ingest is None else "FRESH" if ingest_age is not None and ingest_age <= 86_400 else "HISTORICAL",
                "freshness_age_seconds": ingest_age,
            },
            "shadow": shadow,
            "scope": {
                "discovered_strategy_count": len(strategies),
                "analysed_strategy_count": len(strategy_ids),
                "learning_strategy_count": statuses["learning"] + statuses["insufficient_data"],
                "observed_trade_count": len(events),
                "classified_event_count": len({row.source_event_id for row in classifications}),
            },
            "insights": {
                "new_observation_count": sum(row.status == "NEW" for row in active),
                "top_observations": top,
                "today_focus": focus,
                "top_strengths": strengths,
                "top_performance_leaks": leaks,
            },
            "hero": hero,
            "strategy_status_counts": statuses,
            "behavior": {
                "manual_behaviour_status": manual_status,
                "latest_update": latest,
            },
            "evidence": {
                "observed_trades": legacy_summary.get("sample_size", len(events)),
                "coverage": legacy_summary.get("coverage") or {},
                "performance": legacy_summary.get("performance") or {},
                "behavior": behavior,
                "behavioral_findings": self.coach.findings(events, behavioral_observations).get("findings", [])[:10],
                "coaching": self.coach.coaching(events, behavioral_observations),
                "scorecard": scorecard,
                "trends": trends,
                "limitations": legacy_summary.get("limitations") or [],
                "maturity": legacy_summary.get("maturity", "COLLECTING"),
                "observations": [row.to_dict() for row in observations[:200]],
                "observation_count": len(observations),
                "strategy_scope": strategy_scope,
                "trade_evidence": trade_evidence,
                "trade_evidence_limit": 25,
            },
            "score": {
                "overall_system_discipline_score": "INSUFFICIENT_DATA",
                "components": [],
                "reason": "A fully traceable manual and configured-policy dataset is required.",
            },
            "event_count": len(events),
            "complete_context_count": sum(row.context_complete for row in events),
            "last_event_at": latest,
            "classification_count": len(classifications),
            "observation_count": len(observations),
            "maturity": maturity,
            "last_backfill": self.last_backfill,
            "warnings": [] if events else ["INSUFFICIENT_COMPLETED_TRADE_EVIDENCE"],
        }

    @staticmethod
    def _hero_summary(strategies, statuses, observations, focus, scorecard, trends) -> dict[str, Any]:
        execution_issue = next(
            (
                row.title
                for row in observations
                if row.category == "EXECUTION_HEALTH" and row.severity == "CRITICAL"
            ),
            None,
        )
        performance_leaks = [
            row
            for row in observations
            if row.category != "EXECUTION_HEALTH"
            and row.severity in {"CRITICAL", "IMPORTANT"}
            and row.title in PERFORMANCE_LEAK_TITLES
        ]
        performance_leaks.sort(key=lambda row: (
            row.actual_realized_impact is None,
            row.actual_realized_impact if row.actual_realized_impact is not None else 0,
            -row.confidence,
            row.title,
            row.observation_id,
        ))
        current_window = dict((trends or {}).get("current_window") or {})
        cooldown = current_window.get("cooldown_compliance")
        discipline = {
            "label": "Cooldown compliance",
            "percentage": cooldown,
        } if isinstance(cooldown, (int, float)) else None
        if discipline is None:
            priority = {
                "Plan Adherence": 0,
                "Entry Discipline": 1,
                "Exit Discipline": 2,
                "Risk Discipline": 3,
                "Context Alignment": 4,
            }
            candidates = [
                row
                for row in (scorecard or {}).get("categories", ())
                if isinstance(row.get("score"), (int, float))
            ]
            candidates.sort(key=lambda row: (
                priority.get(str(row.get("category")), 99),
                str(row.get("category")),
            ))
            if candidates:
                discipline = {
                    "label": str(candidates[0]["category"]),
                    "percentage": candidates[0]["score"],
                }
        return {
            "discovered_strategy_count": len(strategies),
            "needs_attention_count": int(statuses.get("needs_attention") or 0),
            "active_observation_count": len(observations),
            "new_observation_count": sum(row.status == "NEW" for row in observations),
            "highest_priority_execution_issue": execution_issue,
            "highest_impact_performance_leak": performance_leaks[0].title if performance_leaks else None,
            "cooldown_compliance_percentage": cooldown if isinstance(cooldown, (int, float)) else None,
            "discipline_metric": discipline,
            "today_focus": dict(focus),
        }

    @staticmethod
    def _strategy_statuses(strategies, events, observations) -> dict[str, int]:
        by_strategy: dict[str, list[Any]] = {}
        for event in events:
            if event.strategy_id:
                by_strategy.setdefault(event.strategy_id, []).append(event)
        attention = {
            strategy_id
            for observation in observations
            if observation.severity in {"CRITICAL", "IMPORTANT"}
            for strategy_id in observation.affected_strategy_ids
        }
        result = {"stable": 0, "improving": 0, "needs_attention": 0, "learning": 0, "insufficient_data": 0}
        for metadata in strategies:
            strategy_id = str(metadata.get("strategy_id") or "")
            rows = by_strategy.get(strategy_id, [])
            if not rows:
                result["insufficient_data"] += 1
            elif strategy_id in attention:
                result["needs_attention"] += 1
            elif len(rows) < 5:
                result["learning"] += 1
            elif len(rows) >= 6 and sum(row.realized_pnl for row in rows[-3:]) > sum(row.realized_pnl for row in rows[-6:-3]):
                result["improving"] += 1
            else:
                result["stable"] += 1
        return result

    @staticmethod
    def _strategy_scope(strategies, events, observations) -> list[dict[str, Any]]:
        event_counts: dict[str, int] = {}
        for event in events:
            if event.strategy_id:
                event_counts[event.strategy_id] = event_counts.get(event.strategy_id, 0) + 1
        attention = {
            strategy_id
            for observation in observations
            if observation.severity in {"CRITICAL", "IMPORTANT"}
            for strategy_id in observation.affected_strategy_ids
        }
        rows = []
        for metadata in strategies:
            strategy_id = str(metadata.get("strategy_id") or "")
            parameters = dict(metadata.get("parameters") or {})
            count = event_counts.get(strategy_id, 0)
            rows.append({
                "strategy_id": strategy_id,
                "strategy_family": str(
                    parameters.get("strategy_family")
                    or metadata.get("family")
                    or str(metadata.get("name") or strategy_id).split()[0]
                    or "NOT_RECORDED"
                ).upper(),
                "symbol": str(
                    parameters.get("chart_symbol")
                    or (metadata.get("supported_markets") or ["NOT_RECORDED"])[0]
                ),
                "timeframe": str((metadata.get("supported_timeframes") or ["NOT_RECORDED"])[0]),
                "option_side": str(parameters.get("option_type") or "NOT_RECORDED"),
                "observed_trade_count": count,
                "status": (
                    "NEEDS_ATTENTION" if strategy_id in attention
                    else "LEARNING" if 0 < count < 5
                    else "STABLE" if count >= 5
                    else "INSUFFICIENT_DATA"
                ),
            })
        return rows

    @staticmethod
    def _today_focus(events, observations) -> dict[str, Any]:
        if not events:
            return {
                "text": "Insufficient evidence—continue collecting completed trades.",
                "confidence": 1.0,
                "sample_size": 0,
            }
        critical = next((row for row in observations if row.severity == "CRITICAL"), None)
        if critical:
            return {"text": f"Review {critical.title.lower()} evidence.", "confidence": critical.confidence, "sample_size": critical.sample_size}
        rapid = next((row for row in observations if row.title == "Rapid Reentry"), None)
        if rapid:
            return {"text": "Monitor rapid re-entry after completed trades.", "confidence": rapid.confidence, "sample_size": rapid.sample_size}
        if all(row.category != "EXECUTION_HEALTH" for row in observations):
            return {
                "text": "No execution defect detected; recent outcomes appear strategy-driven.",
                "confidence": 0.9,
                "sample_size": len(events),
            }
        return {"text": "Continue collecting completed-trade evidence.", "confidence": 0.7, "sample_size": len(events)}

    @staticmethod
    def _age_seconds(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return round(max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()), 3)
        except (TypeError, ValueError):
            return None

    def _invalidate(self) -> None:
        with self._cache_lock:
            self._summary_cache = None
            self._summary_revision = None
