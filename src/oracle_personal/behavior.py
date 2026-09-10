"""Explicit, source-gated behavioral observation classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .models import BehavioralEnrichment, BehavioralObservation, OracleEvent


@dataclass(frozen=True)
class BehaviorPolicy:
    cooldown_minutes: int = 10
    post_loss_window_minutes: int = 30
    maximum_trades_per_day: int = 3
    late_entry_seconds_by_timeframe: tuple[tuple[str, int], ...] = (
        ("1m", 60), ("3m", 120), ("5m", 180), ("15m", 300), ("default", 180)
    )
    weak_kronos_core_below: float = 50.0
    weak_kronos_alpha_below: float = 50.0
    high_uncertainty_at_or_above: float = 0.65
    high_reversal_risk_at_or_above: float = 0.65
    near_daily_limit_at_or_above: float = 80.0

    def late_entry_seconds(self, timeframe: str = "5m") -> int:
        values = dict(self.late_entry_seconds_by_timeframe)
        return values.get(timeframe, values["default"])


class BehaviorClassifier:
    def __init__(self, policy: BehaviorPolicy = BehaviorPolicy(), timeframe: str = "5m"):
        self.policy = policy
        self.timeframe = timeframe

    def classify(
        self,
        events: Iterable[OracleEvent],
        enrichments: Iterable[BehavioralEnrichment] = (),
    ) -> tuple[BehavioralObservation, ...]:
        rows = sorted(events, key=lambda event: (event.entry_at, event.oracle_event_id))
        latest: dict[str, BehavioralEnrichment] = {}
        for enrichment in sorted(enrichments, key=lambda item: (item.reviewed_at, item.enrichment_id)):
            latest[enrichment.oracle_event_id] = enrichment
        result = []
        consecutive_losses = 0
        previous: Optional[OracleEvent] = None
        previous_observation: Optional[BehavioralObservation] = None
        for event in rows:
            enrichment = latest.get(event.oracle_event_id)
            observation = self._classify_one(event, previous, previous_observation, consecutive_losses, enrichment)
            result.append(observation)
            consecutive_losses = consecutive_losses + 1 if event.outcome == "LOSS" else 0
            previous, previous_observation = event, observation
        return tuple(result)

    def _classify_one(self, event, previous, previous_observation, consecutive_losses, enrichment):
        reasons: list[str] = []
        mistakes = set(enrichment.mistake_tags if enrichment else event.mistake_tags)
        entry_at = datetime.fromisoformat(event.entry_at)
        delay = None
        entry_timing = "UNKNOWN"
        if event.signal_at:
            delay = (entry_at - datetime.fromisoformat(event.signal_at)).total_seconds()
            entry_timing = "EARLY" if delay < 0 else "LATE" if delay > self.policy.late_entry_seconds(self.timeframe) else "ON_TIME"
            if entry_timing == "LATE": mistakes.add("LATE_ENTRY")
        distance = event.entry_price - event.entry_reference_price if event.entry_reference_price is not None else None
        chase = "UNKNOWN" if distance is None else ("YES" if self._is_chase(event.side, distance) else "NO")
        if chase == "YES": mistakes.add("CHASE_ENTRY")

        minutes_since = None
        cooldown = enrichment.cooldown_respected if enrichment else "UNKNOWN"
        after_loss = "NO"
        same_direction = same_setup = None
        if previous:
            minutes_since = max(0.0, (entry_at - datetime.fromisoformat(previous.exit_at)).total_seconds() / 60)
            cooldown = "YES" if minutes_since >= self.policy.cooldown_minutes else "NO"
            after_loss = "YES" if previous.outcome == "LOSS" and minutes_since <= self.policy.post_loss_window_minutes else "NO"
            same_direction = event.side == previous.side
            same_setup = event.setup_tag is not None and event.setup_tag == previous.setup_tag
            if cooldown == "NO": mistakes.add("NO_COOLDOWN")
            if after_loss == "YES": mistakes.add("TRADE_AFTER_LOSS")

        exit_timing = "UNKNOWN"
        early_exit = enrichment.stop_respected if False else "UNKNOWN"
        if event.planned_target_price is not None and event.planned_stop_price is not None:
            target_hit = event.exit_price >= event.planned_target_price if event.side in {"BUY", "LONG"} else event.exit_price <= event.planned_target_price
            stop_hit = event.exit_price <= event.planned_stop_price if event.side in {"BUY", "LONG"} else event.exit_price >= event.planned_stop_price
            if target_hit or stop_hit:
                exit_timing, early_exit = "PLAN_BASED", "NO"
            elif event.exit_reason and "MANUAL" in event.exit_reason.upper():
                exit_timing, early_exit = "EARLY", "YES"
                mistakes.add("EARLY_EXIT")

        size_multiplier = event.quantity / event.recommended_quantity if event.recommended_quantity else None
        oversized = "UNKNOWN" if size_multiplier is None else ("YES" if size_multiplier > 1 else "NO")
        if oversized == "YES": mistakes.add("SIZE_TOO_HIGH")
        athena_pause = self._tri(event.athena_recommendation, {"PAUSE", "STOP", "AVOID"})
        near_limit = "UNKNOWN" if event.athena_utilization is None else ("YES" if event.athena_utilization >= self.policy.near_daily_limit_at_or_above else "NO")
        technical_against = self._against(event.side, event.technical_bias or event.technical_signal)
        argus_against = self._against(event.side, event.argus_bias)
        weak_core = "UNKNOWN" if event.kronos_core_quality is None else ("YES" if event.kronos_core_quality < self.policy.weak_kronos_core_below else "NO")
        weak_alpha = "UNKNOWN" if event.kronos_alpha_direction is None else self._against(event.side, event.kronos_alpha_direction)
        hermes_wait = self._tri(event.hermes_event_risk, {"WAIT", "AVOID_NEW_TRADES", "HIGH", "CRITICAL"})
        uncertainty = "UNKNOWN" if event.kronos_alpha_uncertainty is None else ("YES" if event.kronos_alpha_uncertainty >= self.policy.high_uncertainty_at_or_above else "NO")
        reversal = "UNKNOWN" if event.kronos_alpha_reversal_risk is None else ("YES" if event.kronos_alpha_reversal_risk >= self.policy.high_reversal_risk_at_or_above else "NO")
        for value, tag in ((hermes_wait, "TRADE_DURING_EVENT_RISK"), (technical_against, "TRADE_AGAINST_STRUCTURE"), (uncertainty, "TRADE_WITH_HIGH_UNCERTAINTY"), (reversal, "TRADE_WITH_HIGH_REVERSAL_RISK")):
            if value == "YES": mistakes.add(tag)
        if event.trade_number_of_day and event.trade_number_of_day > self.policy.maximum_trades_per_day:
            mistakes.add("OVERTRADING")

        tri_values = [
            enrichment.followed_plan if enrichment else "UNKNOWN",
            enrichment.stop_respected if enrichment else "UNKNOWN",
            enrichment.target_respected if enrichment else "UNKNOWN", cooldown,
            entry_timing, chase, exit_timing, early_exit, oversized, athena_pause,
            near_limit, technical_against, argus_against, weak_core, weak_alpha,
            hermes_wait, uncertainty, reversal,
        ]
        coverage = sum(value != "UNKNOWN" for value in tri_values)
        if not coverage: reasons.append("BEHAVIOR_SOURCE_FIELDS_UNAVAILABLE")
        return BehavioralObservation(
            oracle_event_id=event.oracle_event_id,
            followed_plan=enrichment.followed_plan if enrichment else "UNKNOWN",
            stop_respected=enrichment.stop_respected if enrichment else "UNKNOWN",
            target_respected=enrichment.target_respected if enrichment else "UNKNOWN",
            cooldown_respected=cooldown, entry_timing=entry_timing,
            entry_distance_from_reference=distance, signal_to_entry_delay_seconds=delay,
            chase_entry=chase, exit_timing=exit_timing, early_exit=early_exit,
            stop_moved="UNKNOWN", target_moved="UNKNOWN",
            trade_number_of_day=event.trade_number_of_day,
            previous_trade_result=previous.outcome if previous else None,
            minutes_since_previous_trade=minutes_since, after_loss=after_loss,
            after_consecutive_losses=consecutive_losses,
            same_direction_repeat=same_direction, same_setup_repeat=same_setup,
            size_multiplier_used=size_multiplier, exceeded_recommended_size=oversized,
            entered_during_athena_pause=athena_pause, entered_near_daily_limit=near_limit,
            entered_against_technical_bias=technical_against, entered_against_argus=argus_against,
            entered_with_weak_kronos_core=weak_core, entered_with_weak_kronos_alpha=weak_alpha,
            entered_during_hermes_wait=hermes_wait, entered_during_high_uncertainty=uncertainty,
            entered_during_high_reversal_risk=reversal,
            mistake_tags=tuple(sorted(mistakes)), setup_tags=enrichment.setup_tags if enrichment else (),
            reviewed_by_user=enrichment.reviewed_by_user if enrichment else False,
            coverage_count=coverage, observable_field_count=len(tri_values), reason_codes=tuple(reasons),
        )

    @staticmethod
    def _against(side: str, bias: Optional[str]) -> str:
        if not bias: return "UNKNOWN"
        normalized = bias.upper()
        bullish = any(token in normalized for token in ("BULL", "BUY", "CE"))
        bearish = any(token in normalized for token in ("BEAR", "SELL", "PE"))
        if not bullish and not bearish: return "UNKNOWN"
        long_side = side in {"BUY", "LONG"}
        return "YES" if (long_side and bearish) or (not long_side and bullish) else "NO"

    @staticmethod
    def _tri(value: Optional[str], positives: set[str]) -> str:
        if value is None: return "UNKNOWN"
        return "YES" if value.upper() in positives else "NO"

    @staticmethod
    def _is_chase(side: str, distance: float) -> bool:
        return distance > 0 if side in {"BUY", "LONG"} else distance < 0
