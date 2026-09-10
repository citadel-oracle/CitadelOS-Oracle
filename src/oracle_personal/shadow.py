"""Deterministic, advisory-only Personal ORACLE pre-trade intelligence."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterable, Mapping, Optional

from .ledger import PersonalOracleLedger
from .models import OracleAdvisory, OracleEvent, OracleOutcomeEvaluation


POLICY_VERSION = "PERSONAL_ORACLE_SHADOW_V1"
POLICY_DEFAULTS = {
    "rapid_reentry_seconds": 900,
    "consecutive_loss_threshold": 3,
    "overtrading_daily_threshold": 5,
    "recent_trade_window": 10,
    "minimum_cohort_size": 5,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _identifier(prefix: str, *parts: Any) -> str:
    canonical = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


class PersonalOracleShadow:
    """Produces prospective descriptions; it has no execution surface."""

    def __init__(self, ledger: PersonalOracleLedger):
        self.ledger = ledger

    def advise(self, candidate: Mapping[str, Any], *, source_event_id: str) -> bool:
        candidate_id = str(candidate.get("candidate_signal_id") or "").strip()
        proposed_at = str(candidate.get("entry_timestamp") or "").strip()
        if not candidate_id or not proposed_at:
            raise ValueError("candidate identity and proposed entry time are required")
        history = tuple(sorted((
            event for event in self.ledger.events()
            if datetime.fromisoformat(event.exit_at) < datetime.fromisoformat(proposed_at)
        ), key=lambda event: (event.exit_at, event.oracle_event_id)))
        metrics, sample_sizes, cohort, cohort_rows = self._metrics(history, candidate)
        classification, confidence, reasons = self._classify(metrics, cohort_rows)
        if len(self.ledger.outcomes()) < 10:
            confidence = "UNCALIBRATED"
        advisory = OracleAdvisory(
            advisory_id=_identifier("advisory", candidate_id),
            candidate_signal_id=candidate_id,
            source_event_id=source_event_id,
            generated_at=_now(),
            proposed_entry_at=proposed_at,
            symbol=self._text(candidate.get("instrument")),
            underlying=self._text(candidate.get("underlying")),
            option_side=self._text(candidate.get("option_side")),
            strike=_number(candidate.get("strike")),
            expiry=self._text(candidate.get("expiry")),
            strategy=self._text(candidate.get("strategy")),
            setup=self._text(candidate.get("setup")),
            timeframe=self._text(candidate.get("timeframe")),
            proposed_quantity=int(candidate["quantity"]) if isinstance(candidate.get("quantity"), int) else None,
            signal_price=_number(candidate.get("signal_price")),
            reference_price=_number(candidate.get("reference_price")),
            proposed_stop=_number(candidate.get("stop_loss")),
            proposed_target=_number(candidate.get("target")),
            market_regime=self._text(candidate.get("market_regime")),
            context_completeness_percentage=_number(candidate.get("context_completeness_percentage")) or 0.0,
            missing_context_fields=tuple(str(value) for value in candidate.get("missing_context_fields") or ()),
            personal_metrics=metrics,
            sample_sizes=sample_sizes,
            classification=classification,
            confidence_band=confidence,
            reason_codes=reasons,
            applicable_cohort=cohort,
            cohort_sample_size=len(cohort_rows),
            policy_version=POLICY_VERSION,
            policy_source="POLICY_DEFAULT",
            policy_parameters=POLICY_DEFAULTS,
            data_provenance=dict(candidate.get("provenance") or {}),
        )
        return self.ledger.append_advisory(advisory)

    def link_outcome(self, trade: Mapping[str, Any]) -> bool:
        context = dict(trade.get("oracle_entry_context") or {})
        candidate_id = str(context.get("candidate_signal_id") or "").strip()
        if not candidate_id:
            return False
        advisory = next((row for row in self.ledger.advisories() if row.candidate_signal_id == candidate_id), None)
        if advisory is None:
            return False
        trade_id = str(trade.get("trade_id") or trade.get("position_id") or "").strip()
        pnl = _number(trade.get("realized_pnl"))
        if not trade_id or pnl is None:
            return False
        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        reason_evaluations = {
            reason: self._reason_outcome(reason, outcome)
            for reason in advisory.reason_codes
        }
        return self.ledger.append_outcome(OracleOutcomeEvaluation(
            outcome_evaluation_id=_identifier("outcome", advisory.advisory_id, trade_id),
            advisory_id=advisory.advisory_id,
            candidate_signal_id=candidate_id,
            source_trade_id=trade_id,
            linked_at=_now(),
            realized_pnl=pnl,
            outcome=outcome,
            holding_seconds=_number(trade.get("duration_seconds")),
            mae=_number(trade.get("mae")),
            mfe=_number(trade.get("mfe")),
            reason_evaluations=reason_evaluations,
        ))

    def reconcile_outcomes(self, records: Iterable[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, int]:
        result = {"linked": 0, "duplicate": 0, "unlinked": 0}
        for _, _, trade in records:
            context = dict(trade.get("oracle_entry_context") or {})
            candidate_id = str(context.get("candidate_signal_id") or "")
            if not candidate_id:
                continue
            if self.link_outcome(trade):
                result["linked"] += 1
            else:
                advisory = next((row for row in self.ledger.advisories() if row.candidate_signal_id == candidate_id), None)
                trade_id = str(trade.get("trade_id") or trade.get("position_id") or "")
                already_linked = advisory and any(
                    row.advisory_id == advisory.advisory_id and row.source_trade_id == trade_id
                    for row in self.ledger.outcomes()
                )
                result["duplicate" if already_linked else "unlinked"] += 1
        return result

    def projection(self) -> dict[str, Any]:
        advisories = self.ledger.advisories()
        outcomes = self.ledger.outcomes()
        latest = max(advisories, key=lambda row: (row.generated_at, row.advisory_id), default=None)
        linked = {row.advisory_id for row in outcomes}
        return {
            "latest_advisory": latest.to_dict() if latest else None,
            "latest_successful_shadow_evaluation": latest.generated_at if latest else None,
            "latest_outcome_status": "COMPLETED" if latest and latest.advisory_id in linked else "PENDING" if latest else "NO_DATA",
            "freshness": self._freshness(latest.generated_at if latest else None),
            "prospective_scorecard": self._scorecard(advisories, outcomes),
            "advisory_only": True,
            "execution_influence": "ZERO",
        }

    @classmethod
    def _metrics(cls, history: tuple[OracleEvent, ...], candidate: Mapping[str, Any]):
        strategy = candidate.get("strategy")
        setup = candidate.get("setup")
        timeframe = candidate.get("timeframe")
        option_side = candidate.get("option_side")
        proposed_at = datetime.fromisoformat(str(candidate["entry_timestamp"]))
        period = cls._entry_period(proposed_at)
        strategy_rows = tuple(row for row in history if row.strategy_id == strategy and (not setup or row.setup_tag == setup))
        cohorts = {
            "overall": history,
            "strategy_setup": strategy_rows,
            "timeframe": tuple(row for row in history if timeframe and row.timeframe == timeframe),
            "option_side": tuple(row for row in history if option_side and row.option_side == option_side),
            "weekday": tuple(row for row in history if row.weekday == proposed_at.strftime("%A")),
            "entry_period": tuple(row for row in history if row.time_bucket == period),
        }
        applicable = "STRATEGY_SETUP" if strategy_rows else "OVERALL"
        cohort_rows = strategy_rows or history
        metrics = {name: cls._aggregate(rows) for name, rows in cohorts.items()}
        recent = history[-POLICY_DEFAULTS["recent_trade_window"] :]
        consecutive_losses = 0
        for row in reversed(history):
            if row.realized_pnl >= 0:
                break
            consecutive_losses += 1
        today_rows = tuple(row for row in history if row.trading_date == proposed_at.date().isoformat())
        last_exit = datetime.fromisoformat(history[-1].exit_at) if history else None
        cooldown_seconds = max(0.0, (proposed_at - last_exit).total_seconds()) if last_exit else None
        metrics.update({
            "recent_rolling": cls._aggregate(recent),
            "consecutive_loss_state": {"value": consecutive_losses, "sample_size": len(history), "threshold": POLICY_DEFAULTS["consecutive_loss_threshold"]},
            "trade_frequency_state": {"value": len(today_rows), "sample_size": len(today_rows), "state": "POLICY_THRESHOLD_REACHED" if len(today_rows) >= POLICY_DEFAULTS["overtrading_daily_threshold"] else "NORMAL"},
            "cooldown_state": {"value_seconds": cooldown_seconds, "sample_size": 1 if history else 0, "state": "POLICY_WINDOW_ACTIVE" if cooldown_seconds is not None and cooldown_seconds < POLICY_DEFAULTS["rapid_reentry_seconds"] else "CLEAR"},
            "record_composition": {
                "sample_size": len(history),
                "legacy": sum(row.ingestion_mode == "LEGACY" for row in history),
                "context_v3": sum(row.context_captured for row in history),
                "partial_context": sum(row.context_captured and not row.context_complete for row in history),
            },
        })
        return metrics, {name: len(rows) for name, rows in cohorts.items()}, applicable, cohort_rows

    @staticmethod
    def _aggregate(rows: tuple[OracleEvent, ...]) -> dict[str, Any]:
        values = [row.realized_pnl for row in rows]
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "sample_size": len(values),
            "win_rate": round(100 * len(wins) / len(values), 2) if values else None,
            "expectancy": round(sum(values) / len(values), 2) if values else None,
            "average_win": round(sum(wins) / len(wins), 2) if wins else None,
            "average_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
            "median_pnl": round(statistics.median(values), 2) if values else None,
        }

    @staticmethod
    def _classify(metrics: Mapping[str, Any], cohort_rows: tuple[OracleEvent, ...]):
        cohort = PersonalOracleShadow._aggregate(cohort_rows)
        overall = dict(metrics["overall"])
        size = len(cohort_rows)
        if size < POLICY_DEFAULTS["minimum_cohort_size"]:
            return "INSUFFICIENT_DATA", "UNCALIBRATED", ("MINIMUM_COHORT_NOT_MET",)
        confidence = "LOW" if size < 10 else "MEDIUM"
        cohort_expectancy = cohort.get("expectancy")
        overall_expectancy = overall.get("expectancy")
        if size >= 5 and overall.get("sample_size", 0) >= 5 and cohort_expectancy and overall_expectancy and cohort_expectancy * overall_expectancy < 0:
            return "CONFLICTING_PERSONAL_EVIDENCE", confidence, ("COHORT_CONFLICTS_WITH_OVERALL",)
        if size >= 20 and (
            dict(metrics.get("consecutive_loss_state") or {}).get("value", 0) >= POLICY_DEFAULTS["consecutive_loss_threshold"]
            or dict(metrics.get("trade_frequency_state") or {}).get("state") == "POLICY_THRESHOLD_REACHED"
        ):
            return "HIGH_PERSONAL_RISK", confidence, ("POLICY_RISK_THRESHOLD_REACHED",)
        if cohort_expectancy is not None and cohort_expectancy < 0 and (cohort.get("win_rate") or 0) < 45:
            return "PERSONAL_CAUTION", confidence, ("NEGATIVE_COHORT_EXPECTANCY", "LOW_COHORT_WIN_RATE")
        if cohort_expectancy is not None and cohort_expectancy > 0 and (cohort.get("win_rate") or 0) >= 55:
            return "POSITIVE_PERSONAL_FIT", confidence, ("POSITIVE_COHORT_EXPECTANCY", "COHORT_WIN_RATE_SUPPORTIVE")
        return "NORMAL_HISTORICAL_PROFILE", confidence, ("NO_MATERIAL_PERSONAL_DEVIATION",)

    @staticmethod
    def _scorecard(advisories: tuple[OracleAdvisory, ...], outcomes: tuple[OracleOutcomeEvaluation, ...]) -> dict[str, Any]:
        by_advisory = {row.advisory_id: row for row in advisories}
        distribution: dict[str, int] = {}
        outcome_groups: dict[str, list[OracleOutcomeEvaluation]] = {}
        for advisory in advisories:
            distribution[advisory.classification] = distribution.get(advisory.classification, 0) + 1
        for outcome in outcomes:
            advisory = by_advisory.get(outcome.advisory_id)
            if advisory:
                outcome_groups.setdefault(advisory.classification, []).append(outcome)
        summaries = {}
        confidence_groups: dict[str, list[OracleOutcomeEvaluation]] = {}
        for classification, rows in outcome_groups.items():
            wins = sum(row.outcome == "WIN" for row in rows)
            summaries[classification] = {
                "sample_size": len(rows),
                "average_pnl": round(sum(row.realized_pnl for row in rows) / len(rows), 2),
                "win_rate": {"state": "AVAILABLE" if len(rows) >= 5 else "INSUFFICIENT_SAMPLE", "numerator": wins, "denominator": len(rows), "value": round(100 * wins / len(rows), 2) if len(rows) >= 5 else None},
            }
        for outcome in outcomes:
            advisory = by_advisory.get(outcome.advisory_id)
            if advisory:
                confidence_groups.setdefault(advisory.confidence_band, []).append(outcome)
        calibration = {
            band: {
                "state": "AVAILABLE" if len(rows) >= 5 else "INSUFFICIENT_SAMPLE",
                "numerator": sum(row.outcome == "WIN" for row in rows),
                "denominator": len(rows),
                "win_rate": round(100 * sum(row.outcome == "WIN" for row in rows) / len(rows), 2) if len(rows) >= 5 else None,
            }
            for band, rows in confidence_groups.items()
        }
        return {
            "total_prospective_advisories": len(advisories),
            "completed_outcomes": len(outcomes),
            "pending_advisories": max(0, len(advisories) - len(outcomes)),
            "classification_distribution": distribution,
            "outcome_by_classification": summaries,
            "caution_precision": PersonalOracleShadow._precision(advisories, outcomes, {"PERSONAL_CAUTION", "HIGH_PERSONAL_RISK"}, "LOSS"),
            "high_risk_precision": PersonalOracleShadow._precision(advisories, outcomes, {"HIGH_PERSONAL_RISK"}, "LOSS"),
            "positive_fit_precision": PersonalOracleShadow._precision(advisories, outcomes, {"POSITIVE_PERSONAL_FIT"}, "WIN"),
            "calibration_by_confidence_band": calibration,
            "unlinked_outcomes": 0,
            "duplicate_prevention_status": "ENFORCED",
        }

    @staticmethod
    def _precision(advisories, outcomes, classifications, expected):
        eligible = {row.advisory_id for row in advisories if row.classification in classifications}
        rows = [row for row in outcomes if row.advisory_id in eligible]
        numerator = sum(row.outcome == expected for row in rows)
        return {"state": "AVAILABLE" if len(rows) >= 5 else "INSUFFICIENT_SAMPLE", "numerator": numerator, "denominator": len(rows), "value": round(100 * numerator / len(rows), 2) if len(rows) >= 5 else None}

    @staticmethod
    def _reason_outcome(reason: str, outcome: str) -> str:
        if reason in {"NEGATIVE_COHORT_EXPECTANCY", "LOW_COHORT_WIN_RATE", "POLICY_RISK_THRESHOLD_REACHED"}:
            return "SUPPORTED" if outcome == "LOSS" else "UNSUPPORTED"
        if reason in {"POSITIVE_COHORT_EXPECTANCY", "COHORT_WIN_RATE_SUPPORTIVE"}:
            return "SUPPORTED" if outcome == "WIN" else "UNSUPPORTED"
        return "UNVERIFIABLE"

    @staticmethod
    def _freshness(timestamp: Optional[str]) -> dict[str, Any]:
        if timestamp is None:
            return {"state": "NO_DATA", "age_seconds": None}
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds())
        return {"state": "FRESH" if age <= 86_400 else "HISTORICAL", "age_seconds": round(age, 3)}

    @staticmethod
    def _entry_period(value: datetime) -> str:
        minute = value.hour * 60 + value.minute
        if minute < 615:
            return "OPENING"
        if minute < 720:
            return "MORNING"
        if minute < 840:
            return "MIDDAY"
        return "CLOSING"

    @staticmethod
    def _text(value: Any) -> Optional[str]:
        return str(value) if value is not None and value != "" else None
