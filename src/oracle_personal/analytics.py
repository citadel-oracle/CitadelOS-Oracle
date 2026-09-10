"""Deterministic, threshold-gated Personal ORACLE analytics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any, Callable, Iterable

from .models import OracleEvent


@dataclass(frozen=True)
class MaturityThresholds:
    segment: int = 10
    preliminary: int = 20
    stable: int = 50
    mature: int = 100


class PersonalOracleAnalytics:
    def __init__(self, thresholds: MaturityThresholds = MaturityThresholds()):
        self.thresholds = thresholds

    def summary(self, events: Iterable[OracleEvent]) -> dict[str, Any]:
        rows = sorted(events, key=lambda event: (event.exit_at, event.oracle_event_id))
        pnls = [event.realized_pnl for event in rows]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        r_values = [event.r_multiple for event in rows if event.r_multiple is not None]
        complete = sum(event.context_complete for event in rows)
        max_win, max_loss = self._streaks(rows)
        return {
            "status": "available",
            "sample_size": len(rows),
            "maturity": self.maturity(len(rows)),
            "thresholds": self.thresholds.__dict__,
            "coverage": {
                "complete_context_count": complete,
                "complete_context_percentage": round(complete / len(rows) * 100, 2) if rows else 0.0,
                "historical_backfill_count": sum(event.historical_backfill for event in rows),
            },
            "performance": {
                "wins": len(wins), "losses": len(losses), "flat": sum(pnl == 0 for pnl in pnls),
                "win_rate_percentage": round(len(wins) / len(rows) * 100, 2) if rows else None,
                "net_pnl": round(sum(pnls), 2),
                "expectancy": round(mean(pnls), 2) if pnls else None,
                "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
                "average_r": round(mean(r_values), 4) if r_values else None,
                "max_win_streak": max_win, "max_loss_streak": max_loss,
            },
            "limitations": self.limitations(rows),
        }

    def segments(self, events: Iterable[OracleEvent]) -> dict[str, Any]:
        rows = list(events)
        dimensions: dict[str, Callable[[OracleEvent], Any]] = {
            "instrument": lambda e: e.symbol,
            "option_side": lambda e: e.option_side,
            "strategy": lambda e: e.strategy_name,
            "weekday": lambda e: e.weekday,
            "time_bucket": lambda e: e.time_bucket,
            "trade_number_of_day": lambda e: e.trade_number_of_day,
            "regime": lambda e: e.market_regime,
            "technical_signal": lambda e: e.technical_signal,
            "argus_bias": lambda e: e.argus_bias,
            "kronos_direction": lambda e: e.kronos_direction,
            "athena_risk_state": lambda e: e.athena_risk_state,
            "hermes_event_risk": lambda e: e.hermes_event_risk,
            "previous_outcome": lambda e: e.previous_trade_outcome,
            "cooldown_respected": lambda e: e.cooldown_respected,
            "early_exit": lambda e: e.early_exit,
            "late_entry": lambda e: e.late_entry,
        }
        result = {}
        for name, getter in dimensions.items():
            buckets: dict[str, list[OracleEvent]] = defaultdict(list)
            for event in rows:
                raw = getter(event)
                key = "UNAVAILABLE" if raw is None else str(raw)
                buckets[key].append(event)
            result[name] = [self._segment_row(key, values) for key, values in sorted(buckets.items())]
        mistake_buckets: dict[str, list[OracleEvent]] = defaultdict(list)
        for event in rows:
            for tag in event.mistake_tags:
                mistake_buckets[tag].append(event)
        result["mistake_tags"] = [self._segment_row(k, v) for k, v in sorted(mistake_buckets.items())]
        return {"status": "available", "minimum_segment_size": self.thresholds.segment, "segments": result}

    def findings(self, events: Iterable[OracleEvent]) -> dict[str, Any]:
        rows = list(events)
        segment_payload = self.segments(rows)["segments"]
        findings = []
        for dimension, segments in segment_payload.items():
            eligible = [row for row in segments if row["meaningful"]]
            if len(eligible) < 2:
                continue
            best = max(eligible, key=lambda row: row["expectancy"])
            worst = min(eligible, key=lambda row: row["expectancy"])
            if best["value"] == worst["value"] or best["expectancy"] == worst["expectancy"]:
                continue
            findings.append({
                "finding_id": f"segment-{dimension}", "type": "OBSERVED_SEGMENT_DIFFERENCE",
                "dimension": dimension, "sample_size": best["sample_size"] + worst["sample_size"],
                "statement": f"Observed {dimension} segments have different historical expectancy.",
                "evidence": {"higher": best, "lower": worst},
                "limitations": ["Association only; no causal claim.", "Paper-history results may not generalize."],
            })
        return {"status": "available", "sample_size": len(rows), "findings": findings[:12], "limitations": self.limitations(rows)}

    def recommendations(self, events: Iterable[OracleEvent]) -> dict[str, Any]:
        rows = list(events)
        findings = self.findings(rows)["findings"]
        if not findings:
            items = [{
                "state": "INSUFFICIENT_EVIDENCE", "recommendation": "Continue collecting completed paper trades with entry-time context.",
                "sample_size": len(rows), "evidence": [],
                "limitations": ["No threshold-qualified comparative finding is available."],
            }]
        else:
            items = [{
                "state": "REVIEW_OBSERVED_PATTERN", "recommendation": finding["statement"],
                "sample_size": finding["sample_size"], "evidence": [finding["finding_id"]],
                "limitations": finding["limitations"],
            } for finding in findings]
        return {"status": "available", "maturity": self.maturity(len(rows)), "recommendations": items}

    def maturity(self, count: int) -> str:
        if count >= self.thresholds.mature: return "MATURE"
        if count >= self.thresholds.stable: return "STABLE"
        if count >= self.thresholds.preliminary: return "PRELIMINARY"
        return "COLLECTING"

    @staticmethod
    def limitations(rows: list[OracleEvent]) -> list[str]:
        result = ["Deterministic descriptive analytics; no causal inference."]
        if any(event.historical_backfill for event in rows):
            result.append("Historical backfill lacks timestamp-aligned intelligence context.")
        if rows and all(event.brokerage is None for event in rows):
            result.append("Brokerage and slippage are unavailable.")
        return result

    def _segment_row(self, value: str, rows: list[OracleEvent]) -> dict[str, Any]:
        pnls = [event.realized_pnl for event in rows]
        return {"value": value, "sample_size": len(rows), "meaningful": len(rows) >= self.thresholds.segment,
                "win_rate_percentage": round(sum(p > 0 for p in pnls) / len(pnls) * 100, 2),
                "expectancy": round(mean(pnls), 2), "net_pnl": round(sum(pnls), 2)}

    @staticmethod
    def _streaks(rows: list[OracleEvent]) -> tuple[int, int]:
        win = loss = max_win = max_loss = 0
        for event in rows:
            if event.outcome == "WIN": win += 1; loss = 0
            elif event.outcome == "LOSS": loss += 1; win = 0
            else: win = loss = 0
            max_win, max_loss = max(max_win, win), max(max_loss, loss)
        return max_win, max_loss
