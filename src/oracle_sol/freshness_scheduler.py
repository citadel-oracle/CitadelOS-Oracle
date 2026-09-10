"""Freshness Scheduler (Phase-1 Cognitive Architecture).

Dynamically schedules model updates based on:
- Time age (seconds elapsed)
- Revision distance (latest_canonical_revision - analyzed_revision)
- Unseen canonical event backlog
- Material model disagreements or reversal signals
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.oracle_sol.contracts import GeminiReview, PrimarySynthesisOutput, QwenObservation
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor

logger = logging.getLogger(__name__)


@dataclass
class ModelFreshnessRecord:
    model_name: str
    last_analysis_time: float = 0.0
    analyzed_revision: int = 0
    latest_known_revision: int = 0
    unseen_events_count: int = 0
    is_running: bool = False
    status_label: str = "INITIALIZING"

    def age_seconds(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        if self.last_analysis_time <= 0:
            return 999.0
        return max(0.0, now - self.last_analysis_time)

    def revision_lag(self) -> int:
        return max(0, self.latest_known_revision - self.analyzed_revision)


class FreshnessScheduler:
    """Coordinates event-aware model cadence without fixed rigid loops."""

    def __init__(self, quota_governor: Optional[CognitiveQuotaGovernor] = None) -> None:
        self.quota_governor = quota_governor or CognitiveQuotaGovernor()
        self.freshness: Dict[str, ModelFreshnessRecord] = {
            "qwen": ModelFreshnessRecord(model_name="qwen/qwen3.8-27b"),
            "gpt_oss": ModelFreshnessRecord(model_name="openai/gpt-oss-120b"),
            "gemini": ModelFreshnessRecord(model_name="gemini-3.8-flash"),
            "gemini_primary": ModelFreshnessRecord(model_name="gemini-3.8-flash"),
            "gemini_secondary": ModelFreshnessRecord(model_name="gemini-3.8-flash"),
            "gemini_tertiary": ModelFreshnessRecord(model_name="gemini-3.8-flash"),
        }

    def update_canonical_state(self, latest_revision: int, unseen_events_count: int) -> None:
        """Updates known canonical progression across all tracked models."""
        for rec in self.freshness.values():
            rec.latest_known_revision = latest_revision
            rec.unseen_events_count = unseen_events_count

    def record_model_completion(
        self,
        model_key: str,
        revision_analyzed: int,
        tokens_consumed: int = 1200,
        latency_ms: float = 50.0,
    ) -> None:
        """Records inference completion, updating freshness and quota metrics."""
        now = time.time()
        rec = self.freshness.get(model_key)
        if rec:
            rec.last_analysis_time = now
            rec.analyzed_revision = revision_analyzed
            rec.unseen_events_count = 0
            rec.is_running = False
            rec.status_label = "CURRENT"
        self.quota_governor.record_call_success(
            model_key=model_key,
            tokens_consumed=tokens_consumed,
            latency_ms=latency_ms,
        )

    def should_run_qwen(
        self,
        has_new_events: bool = False,
        relationship_changed: bool = False,
    ) -> bool:
        """Determines if Qwen Fast Sentinel should execute on this tick."""
        rec = self.freshness["qwen"]
        if rec.is_running or not self.quota_governor.can_invoke("qwen"):
            return False

        age = rec.age_seconds()
        min_interval = self.quota_governor.compute_recommended_interval("qwen")

        # Fast event trigger: if new events or relationships changed and minimum cadence met
        if (has_new_events or relationship_changed) and age >= min_interval:
            return True

        # Revision lag trigger: if lagging by >= 5 revisions
        if rec.revision_lag() >= 5 and age >= min_interval:
            return True

        # Periodic freshness deadline (default 20 seconds)
        if age >= 20.0:
            return True

        return False

    def should_run_gpt(
        self,
        qwen_obs: Optional[QwenObservation] = None,
        last_synthesis: Optional[PrimarySynthesisOutput] = None,
    ) -> bool:
        """Determines if GPT-OSS Primary Synthesizer should execute on this tick."""
        rec = self.freshness["gpt_oss"]
        if rec.is_running or not self.quota_governor.can_invoke("gpt_oss"):
            return False

        age = rec.age_seconds()
        min_interval = self.quota_governor.compute_recommended_interval("gpt_oss")
        if age < min_interval:
            return False

        # Material Qwen shift: if Qwen entered REVERSAL_WATCH or flipped continuation
        if qwen_obs and last_synthesis:
            if "REVERSAL" in qwen_obs.continuation_status and last_synthesis.current_state != "REVERSAL_WATCH":
                return True
            if qwen_obs.continuation_status == "CONTINUATION_LOSING_PROGRESS" and last_synthesis.entry_window == "READY":
                return True

        # Event backlog trigger: if accumulated 3+ unseen canonical events
        if rec.unseen_events_count >= 3:
            return True

        # Max acceptable staleness during active market (45 seconds)
        if age >= 45.0:
            return True

        return False

    def should_run_gemini(
        self,
        qwen_obs: Optional[QwenObservation] = None,
        last_synthesis: Optional[PrimarySynthesisOutput] = None,
    ) -> bool:
        """Determines if Gemini Independent Reviewer should execute."""
        rec = self.freshness["gemini"]
        if rec.is_running or not self.quota_governor.can_invoke("gemini"):
            return False

        age = rec.age_seconds()
        min_interval = self.quota_governor.compute_recommended_interval("gemini")
        if age < min_interval:
            return False

        # State transition or tension trigger:
        if qwen_obs and last_synthesis:
            # Tension between Qwen and GPT
            if ("PUT" in qwen_obs.current_side_pressure and "CALL" in last_synthesis.current_state) or \
               ("BUYER" in qwen_obs.current_side_pressure and "PUT" in last_synthesis.current_state):
                return True

        # Deep review periodic cadence (e.g. every 90-120 seconds)
        if age >= 90.0:
            return True

        return False

    def get_freshness_status_summary(self) -> Dict[str, Any]:
        """Produces exact freshness telemetry for the frontend primary decision strip."""
        now = time.time()
        res = {}
        for k, rec in self.freshness.items():
            age = rec.age_seconds(now)
            status = "RUNNING" if rec.is_running else (
                "QUOTA_BLOCKED" if not self.quota_governor.can_invoke(k, now) else (
                    "CURRENT" if age < 30.0 else ("STALE" if age < 90.0 else "OUTDATED")
                )
            )
            res[k] = {
                "model_name": rec.model_name,
                "status": status,
                "age_seconds": round(age, 1),
                "analyzed_revision": rec.analyzed_revision,
                "latest_revision": rec.latest_known_revision,
                "unseen_events_count": rec.unseen_events_count,
            }
        return res
