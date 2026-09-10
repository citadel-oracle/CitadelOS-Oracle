"""Evidence-gated behavioral analytics and conservative coaching contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import mean
from typing import Any, Callable, Iterable

from .analytics import MaturityThresholds
from .models import BehavioralObservation, OracleEvent


@dataclass(frozen=True)
class CoachingThresholds:
    segment: int = 10
    preliminary: int = 20
    stable: int = 50
    mature: int = 100
    trend_window: int = 10
    scorecard_category: int = 10


class BehavioralCoaching:
    def __init__(self, thresholds: CoachingThresholds = CoachingThresholds()):
        self.thresholds = thresholds

    def behavior(self, events: Iterable[OracleEvent], observations: Iterable[BehavioralObservation]) -> dict[str, Any]:
        rows = list(observations)
        observed = sum(item.coverage_count > 0 for item in rows)
        fields = sum(item.observable_field_count for item in rows)
        covered = sum(item.coverage_count for item in rows)
        return {
            "status": "available", "observed_trades": len(rows), "behaviorally_observed_trades": observed,
            "behavioral_coverage_percentage": round(covered / fields * 100, 2) if fields else 0.0,
            "maturity": self.maturity(observed),
            "latest_update": max((event.exit_at for event in events), default=None),
            "observations": [item.to_dict() for item in rows[-100:]],
            "limitations": self._limitations(observed),
        }

    def comparisons(self, events: Iterable[OracleEvent], observations: Iterable[BehavioralObservation]) -> list[dict[str, Any]]:
        event_rows = list(events); observation_map = {item.oracle_event_id: item for item in observations}
        pairs = [(event, observation_map[event.oracle_event_id]) for event in event_rows if event.oracle_event_id in observation_map]
        specs: list[tuple[str, str, Callable, str, str]] = [
            ("POST_LOSS_DEGRADATION", "After loss vs after win", lambda o: "AFTER_LOSS" if o.previous_trade_result == "LOSS" else "AFTER_WIN" if o.previous_trade_result == "WIN" else None, "AFTER_LOSS", "AFTER_WIN"),
            ("SECOND_TRADE_WEAKNESS", "First trade vs later trades", lambda o: "FIRST" if o.trade_number_of_day == 1 else "LATER" if o.trade_number_of_day and o.trade_number_of_day > 1 else None, "LATER", "FIRST"),
            ("NO_COOLDOWN_COST", "Cooldown ignored vs respected", lambda o: o.cooldown_respected, "NO", "YES"),
            ("EARLY_EXIT_COST", "Early vs plan-based exit", lambda o: o.exit_timing, "EARLY", "PLAN_BASED"),
            ("LATE_ENTRY_COST", "Late vs on-time entry", lambda o: o.entry_timing, "LATE", "ON_TIME"),
            ("STOP_DISCIPLINE_ISSUE", "Stop not respected vs respected", lambda o: o.stop_respected, "NO", "YES"),
            ("TARGET_DISCIPLINE_ISSUE", "Target not respected vs respected", lambda o: o.target_respected, "NO", "YES"),
            ("HIGH_UNCERTAINTY_ENTRY_COST", "High vs lower uncertainty", lambda o: o.entered_during_high_uncertainty, "YES", "NO"),
            ("HIGH_REVERSAL_RISK_ENTRY_COST", "High vs lower reversal risk", lambda o: o.entered_during_high_reversal_risk, "YES", "NO"),
            ("KRONOS_ALPHA_ALIGNMENT_EDGE", "KRONOS ALPHA opposed vs aligned", lambda o: o.entered_with_weak_kronos_alpha, "YES", "NO"),
            ("CONTEXT_ALIGNMENT_EDGE", "Technical opposed vs aligned", lambda o: o.entered_against_technical_bias, "YES", "NO"),
            ("CONTEXT_ALIGNMENT_EDGE", "ARGUS opposed vs aligned", lambda o: o.entered_against_argus, "YES", "NO"),
            ("EVENT_RISK_VIOLATION", "Event risk vs normal", lambda o: o.entered_during_hermes_wait, "YES", "NO"),
            ("EVENT_RISK_VIOLATION", "Athena pause vs safe", lambda o: o.entered_during_athena_pause, "YES", "NO"),
            ("SIZE_DISCIPLINE_ISSUE", "Oversized vs normal size", lambda o: o.exceeded_recommended_size, "YES", "NO"),
            ("CE_BEHAVIOR_EDGE", "CE vs PE behavior", lambda o: next((e.option_side for e, candidate in pairs if candidate.oracle_event_id == o.oracle_event_id), None), "CE", "PE"),
            ("REPEATED_MISTAKE", "Manual override vs normal flow", lambda o: "YES" if "MANUAL_OVERRIDE" in o.mistake_tags else "NO", "YES", "NO"),
        ]
        result = []
        for finding_type, title, getter, support_key, comparison_key in specs:
            support = [event for event, obs in pairs if getter(obs) == support_key]
            comparison = [event for event, obs in pairs if getter(obs) == comparison_key]
            result.append(self._comparison(finding_type, title, support_key, support, comparison_key, comparison))
        return result

    def findings(self, events, observations) -> dict[str, Any]:
        qualified = [row for row in self.comparisons(events, observations) if row["qualified"]]
        findings = []
        for row in qualified:
            findings.append({
                "finding_id": row["finding_id"], "type": row["type"], "title": row["title"],
                "summary": f"Observed expectancy differs between {row['supporting_label']} and {row['comparison_label']} samples.",
                "supporting_sample": row["supporting"], "comparison_sample": row["comparison"],
                "metrics": {"expectancy_delta": row["expectancy_delta"], "win_rate_delta": row["win_rate_delta"]},
                "effect_size": row["effect_size"], "maturity": row["maturity"], "confidence_band": row["confidence_band"],
                "reason_codes": ["THRESHOLD_MET", "ASSOCIATION_ONLY"],
                "limitations": ["Observed association only; no causal claim.", "Paper-history outcomes may not generalize."],
                "date_range": row["date_range"], "last_updated": row["last_updated"],
            })
        repeated = self._repeated_mistake(events, observations)
        if repeated: findings.append(repeated)
        return {"status": "available", "findings": sorted(findings, key=lambda item: (-abs(item["effect_size"] or 0), item["finding_id"]))[:12],
                "limitations": self._limitations(sum(item.coverage_count > 0 for item in observations))}

    def coaching(self, events, observations) -> dict[str, Any]:
        findings = self.findings(events, observations)["findings"]
        recommendations = []
        for finding in findings:
            sample = finding["supporting_sample"]["sample_size"] + finding["comparison_sample"]["sample_size"]
            if sample < self.thresholds.preliminary: continue
            state = self._recommendation_state(finding)
            recommendations.append({
                "recommendation_id": f"coach-{finding['finding_id']}", "state": state, "title": finding["title"],
                "evidence_summary": finding["summary"], "sample_size": sample, "maturity": finding["maturity"],
                "expected_benefit": abs(finding["metrics"]["expectancy_delta"]) if finding["metrics"].get("expectancy_delta") is not None else None,
                "limitation": finding["limitations"][0], "execution_authority": False,
                "risk_override": False, "strategy_mutation": False,
            })
        if not recommendations:
            recommendations = [{"recommendation_id": "coach-collect", "state": "INSUFFICIENT_DATA",
                "title": "Collecting behavioral evidence", "evidence_summary": "No comparison currently meets coaching thresholds.",
                "sample_size": sum(item.coverage_count > 0 for item in observations), "maturity": "COLLECTING",
                "expected_benefit": None, "limitation": "Structured behavioral observations are insufficient.",
                "execution_authority": False, "risk_override": False, "strategy_mutation": False}]
        return {"status": "available", "recommendations": recommendations[:3], "maximum_recommendations": 3}

    def scorecard(self, observations: Iterable[BehavioralObservation]) -> dict[str, Any]:
        rows = list(observations)
        categories = {
            "Plan Adherence": [(o.followed_plan, "YES") for o in rows],
            "Entry Discipline": [(o.entry_timing, "ON_TIME") for o in rows] + [(o.chase_entry, "NO") for o in rows],
            "Exit Discipline": [(o.stop_respected, "YES") for o in rows] + [(o.target_respected, "YES") for o in rows] + [(o.early_exit, "NO") for o in rows],
            "Cooldown Compliance": [(o.cooldown_respected, "YES") for o in rows],
            "Risk Discipline": [(o.exceeded_recommended_size, "NO") for o in rows] + [(o.entered_during_athena_pause, "NO") for o in rows],
            "Context Alignment": [(o.entered_against_technical_bias, "NO") for o in rows] + [(o.entered_against_argus, "NO") for o in rows] + [(o.entered_during_hermes_wait, "NO") for o in rows],
            "Review Coverage": [("YES" if o.reviewed_by_user else "NO", "YES") for o in rows],
        }
        scores = []
        for category, values in categories.items():
            observed = [(value, positive) for value, positive in values if value != "UNKNOWN"]
            score = round(sum(value == positive for value, positive in observed) / len(observed) * 100, 2) if len(observed) >= self.thresholds.scorecard_category else None
            scores.append({"category": category, "score": score, "sample_size": len(observed), "maturity": self.maturity(len(observed)),
                           "available": score is not None})
        return {"status": "available", "categories": scores, "overall_score": None,
                "limitations": ["No personality or combined trader score is produced."]}

    def trends(self, events: Iterable[OracleEvent], observations: Iterable[BehavioralObservation]) -> dict[str, Any]:
        event_map = {event.oracle_event_id: event for event in events}
        rows = [(event_map[item.oracle_event_id], item) for item in observations if item.oracle_event_id in event_map]
        rows.sort(key=lambda pair: pair[0].exit_at)
        current = rows[-10:]; previous = rows[-20:-10]
        current_metrics = self._trend_metrics(current); previous_metrics = self._trend_metrics(previous)
        label = "INSUFFICIENT_DATA"
        if len(current) >= 10 and len(previous) >= 10:
            delta = current_metrics["expectancy"] - previous_metrics["expectancy"]
            mistake_delta = current_metrics["mistake_rate"] - previous_metrics["mistake_rate"]
            label = "IMPROVING" if delta > 0 and mistake_delta < 0 else "DETERIORATING" if delta < 0 and mistake_delta > 0 else "STABLE"
        return {"status": "available", "label": label, "current_window": current_metrics,
                "previous_window": previous_metrics, "minimum_window": 10,
                "current_month": self._month_metrics(rows, 0), "prior_month": self._month_metrics(rows, 1),
                "limitations": ["Trend labels require two comparable 10-trade windows."]}

    def maturity(self, count: int) -> str:
        if count >= self.thresholds.mature: return "MATURE"
        if count >= self.thresholds.stable: return "STABLE"
        if count >= self.thresholds.preliminary: return "PRELIMINARY"
        return "COLLECTING"

    @staticmethod
    def _recommendation_state(finding: dict[str, Any]) -> str:
        """Describe the supported action without upgrading association into approval."""
        if finding["type"] == "REPEATED_MISTAKE":
            return "IMPROVE"
        if finding["type"] == "BEST_BEHAVIORAL_PATTERN" and (finding["metrics"].get("expectancy_delta") or 0) > 0:
            return "MAINTAIN"
        return "OBSERVE"

    def _comparison(self, finding_type, title, support_label, support, comparison_label, comparison):
        a, b = self._metrics(support), self._metrics(comparison)
        qualified = len(support) >= self.thresholds.segment and len(comparison) >= self.thresholds.segment
        delta = round(a["expectancy"] - b["expectancy"], 4) if a["expectancy"] is not None and b["expectancy"] is not None else None
        pooled = self._pooled_std([event.realized_pnl for event in support], [event.realized_pnl for event in comparison])
        effect = round(delta / pooled, 4) if delta is not None and pooled else None
        all_rows = sorted([*support, *comparison], key=lambda e: e.exit_at)
        return {"finding_id": f"behavior-{finding_type.lower()}-{title.lower().replace(' ', '-')[:24]}", "type": finding_type,
                "title": title, "supporting_label": support_label, "comparison_label": comparison_label,
                "supporting": a, "comparison": b, "qualified": qualified, "expectancy_delta": delta,
                "win_rate_delta": round((a["win_rate"] or 0) - (b["win_rate"] or 0), 2) if support and comparison else None,
                "effect_size": effect, "maturity": self.maturity(min(len(support), len(comparison))),
                "confidence_band": "STABLE" if min(len(support), len(comparison)) >= 50 else "PRELIMINARY" if qualified else "INSUFFICIENT",
                "date_range": {"from": all_rows[0].trading_date, "to": all_rows[-1].trading_date} if all_rows else None,
                "last_updated": all_rows[-1].exit_at if all_rows else None}

    @staticmethod
    def _metrics(rows):
        pnls = [event.realized_pnl for event in rows]; points = [event.realized_points for event in rows]
        losses = [value for value in pnls if value < 0]; wins = [value for value in pnls if value > 0]
        r = [event.r_multiple for event in rows if event.r_multiple is not None]
        holding = [event.holding_seconds for event in rows if event.holding_seconds is not None]
        return {"sample_size": len(rows), "win_rate": round(len(wins) / len(rows) * 100, 2) if rows else None,
                "expectancy": round(mean(pnls), 4) if pnls else None, "average_r": round(mean(r), 4) if r else None,
                "average_points": round(mean(points), 4) if points else None,
                "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
                "average_holding_seconds": round(mean(holding), 2) if holding else None,
                "loss_severity": round(mean(losses), 4) if losses else None}

    @staticmethod
    def _pooled_std(a, b):
        values = [*a, *b]
        if len(values) < 2: return None
        avg = mean(values); variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
        return sqrt(variance) or None

    def _repeated_mistake(self, events, observations):
        event_map = {event.oracle_event_id: event for event in events}; buckets = {}
        for observation in observations:
            for tag in observation.mistake_tags: buckets.setdefault(tag, []).append(event_map.get(observation.oracle_event_id))
        eligible = [(tag, [event for event in rows if event]) for tag, rows in buckets.items() if len(rows) >= self.thresholds.segment]
        if not eligible: return None
        tag, rows = sorted(eligible, key=lambda pair: (-len(pair[1]), pair[0]))[0]; metrics = self._metrics(rows)
        return {"finding_id": f"behavior-repeated-{tag.lower()}", "type": "REPEATED_MISTAKE", "title": f"Repeated observable tag: {tag.replace('_', ' ').title()}",
                "summary": "A structured mistake tag repeats above the reporting threshold.", "supporting_sample": metrics,
                "comparison_sample": {"sample_size": 0}, "metrics": {"expectancy_delta": None}, "effect_size": None,
                "maturity": self.maturity(len(rows)), "confidence_band": "PRELIMINARY", "reason_codes": ["STRUCTURED_TAG_THRESHOLD_MET"],
                "limitations": ["Tag frequency is observational and does not diagnose intent or emotion."],
                "date_range": {"from": min(e.trading_date for e in rows), "to": max(e.trading_date for e in rows)},
                "last_updated": max(e.exit_at for e in rows)}

    @staticmethod
    def _trend_metrics(rows):
        if not rows: return {"sample_size": 0, "mistake_rate": None, "plan_adherence": None, "late_entry_rate": None, "early_exit_rate": None, "cooldown_compliance": None, "post_loss_expectancy": None, "average_r": None, "expectancy": None}
        def rate(values, positive):
            observed = [value for value in values if value != "UNKNOWN"]
            return round(sum(value == positive for value in observed) / len(observed) * 100, 2) if observed else None
        events = [event for event, _ in rows]; obs = [item for _, item in rows]
        post_loss = [event.realized_pnl for event, item in rows if item.previous_trade_result == "LOSS"]
        r = [event.r_multiple for event in events if event.r_multiple is not None]
        return {"sample_size": len(rows), "mistake_rate": round(sum(bool(item.mistake_tags) for item in obs) / len(obs) * 100, 2),
                "plan_adherence": rate([item.followed_plan for item in obs], "YES"), "late_entry_rate": rate([item.entry_timing for item in obs], "LATE"),
                "early_exit_rate": rate([item.early_exit for item in obs], "YES"), "cooldown_compliance": rate([item.cooldown_respected for item in obs], "YES"),
                "post_loss_expectancy": round(mean(post_loss), 4) if post_loss else None, "average_r": round(mean(r), 4) if r else None,
                "expectancy": round(mean(event.realized_pnl for event in events), 4)}

    def _month_metrics(self, rows, offset):
        if not rows: return self._trend_metrics([])
        latest = datetime.fromisoformat(rows[-1][0].exit_at); year, month = latest.year, latest.month - offset
        while month <= 0: year -= 1; month += 12
        return self._trend_metrics([pair for pair in rows if (datetime.fromisoformat(pair[0].exit_at).year, datetime.fromisoformat(pair[0].exit_at).month) == (year, month)])

    @staticmethod
    def _limitations(observed):
        return ["Observable structured fields only; no emotional or psychological inference.",
                "No coaching claim is published below configured evidence thresholds."] if observed else ["Collecting behavioral evidence; structured fields are unavailable."]
