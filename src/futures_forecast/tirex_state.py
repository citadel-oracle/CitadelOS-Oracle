"""Transparent, advisory-only TiRex quantile interpretation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Sequence

from .math import ForecastValidationError, finite_number, validate_quantile_matrix


@dataclass(frozen=True)
class TiRexStateConfig:
    quantile_levels: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    horizon_indices: tuple[int, ...] = (0, 2, 5)
    enter_threshold: float = 0.35
    exit_threshold: float = 0.15
    immediate_reversal_threshold: float = 0.85
    confirmations_required: int = 2
    formula_version: str = "TIREX_DIRECTIONAL_STATE_V1"


class TiRexStateClassifier:
    """Classify three horizon quantile distributions with two-snapshot hysteresis."""

    def __init__(self, config: TiRexStateConfig | None = None):
        self.config = config or TiRexStateConfig()
        self._confirmed = "NEUTRAL"
        self._candidate = "NEUTRAL"
        self._streak = 0

    def classify(self, quantiles: Any, current_close: float, recent_closes: Sequence[float]) -> dict[str, Any]:
        horizon = max(self.config.horizon_indices) + 1
        matrix = validate_quantile_matrix(quantiles, quantile_count=len(self.config.quantile_levels), horizon=horizon)
        close = finite_number(current_close, "TIREX_CURRENT_CLOSE")
        history = [finite_number(value, "TIREX_HISTORY_CLOSE") for value in recent_closes]
        if len(history) < 20:
            raise ForecastValidationError("TIREX_NOISE_CONTEXT_INSUFFICIENT")
        changes = [abs(history[index] - history[index - 1]) for index in range(1, len(history))]
        noise = max(0.05, median(changes))
        q10, q50, q90 = 0, self.config.quantile_levels.index(0.5), len(self.config.quantile_levels) - 1
        evidence = []
        horizon_states = []
        widths = []
        for index in self.config.horizon_indices:
            displacement = (matrix[q50][index] - close) / noise
            width = max(noise, matrix[q90][index] - matrix[q10][index])
            distribution_position = (matrix[q50][index] - close) / width
            score = max(-1.5, min(1.5, displacement / 3.0 + distribution_position))
            evidence.append(score)
            widths.append(width)
            horizon_states.append("BULLISH" if score >= self.config.enter_threshold else "BEARISH" if score <= -self.config.enter_threshold else "NEUTRAL")
        composite = sum(evidence) / len(evidence)
        positive = sum(state == "BULLISH" for state in horizon_states)
        negative = sum(state == "BEARISH" for state in horizon_states)
        raw = "BULLISH" if composite >= self.config.enter_threshold and positive >= 2 else "BEARISH" if composite <= -self.config.enter_threshold and negative >= 2 else "NEUTRAL"
        self._transition(raw, composite)
        return {
            "status": "READY",
            "state": self._confirmed,
            "raw_state": raw,
            "evidence_score": round(composite, 6),
            "horizon_states": horizon_states,
            "horizon_scores": [round(value, 6) for value in evidence],
            "uncertainty_widths": [round(value, 6) for value in widths],
            "noise_scale": round(noise, 6),
            "candidate": self._candidate,
            "candidate_streak": self._streak,
            "formula_version": self.config.formula_version,
            "execution_influence": "ZERO",
            "not_probability": True,
        }

    def unavailable(self, reason: str) -> dict[str, Any]:
        self._candidate = "NEUTRAL"
        self._streak = 0
        self._confirmed = "NEUTRAL"
        return {
            "status": "UNAVAILABLE",
            "state": "NEUTRAL",
            "raw_state": "NEUTRAL",
            "reason": reason,
            "formula_version": self.config.formula_version,
            "execution_influence": "ZERO",
            "not_probability": True,
        }

    def _transition(self, raw: str, composite: float) -> None:
        if raw == self._confirmed:
            self._candidate, self._streak = raw, 0
            return
        if self._confirmed != "NEUTRAL" and raw == "NEUTRAL" and abs(composite) > self.config.exit_threshold:
            return
        if raw != "NEUTRAL" and self._confirmed not in {"NEUTRAL", raw} and abs(composite) >= self.config.immediate_reversal_threshold:
            self._confirmed, self._candidate, self._streak = raw, raw, 0
            return
        if raw != self._candidate:
            self._candidate, self._streak = raw, 1
        else:
            self._streak += 1
        if self._streak >= self.config.confirmations_required:
            self._confirmed, self._streak = raw, 0
