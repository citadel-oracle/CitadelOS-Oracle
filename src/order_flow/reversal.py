"""Time-based reversal warning state machine with no independent vote."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import DataQuality, ReversalState


@dataclass(frozen=True, slots=True)
class ReversalObservation:
    state: ReversalState
    stable_direction: int
    candidate_direction: int
    first_warning_ns: int | None
    forming_ns: int | None
    confirmed_ns: int | None
    score: float
    warning_futures_price: float | None
    warning_atm_premium: float | None
    confirmed_futures_price: float | None
    confirmed_atm_premium: float | None
    lead_time_ms: float | None
    futures_points_warning_to_confirmation: float | None
    atm_points_warning_to_confirmation: float | None
    false_reversal_count: int
    recovered_original_direction: bool
    last_false_reversal_ns: int | None


class ReversalEngine:
    """A noisy packet can warn, but elapsed persistence is required to flip."""

    def __init__(
        self,
        *,
        flip_threshold: float = 0.35,
        stable_threshold: float = 0.20,
        forming_seconds: float = 0.75,
        confirmation_seconds: float = 1.50,
    ):
        self.flip_threshold = flip_threshold
        self.stable_threshold = stable_threshold
        self.forming_ns_required = int(forming_seconds * 1_000_000_000)
        self.confirmation_ns_required = int(confirmation_seconds * 1_000_000_000)
        self.state = ReversalState.STABLE_DIRECTION
        self.stable_direction = 0
        self.candidate_direction = 0
        self.first_warning_ns: int | None = None
        self.forming_ns: int | None = None
        self.confirmed_ns: int | None = None
        self.warning_futures_price: float | None = None
        self.warning_atm_premium: float | None = None
        self.confirmed_futures_price: float | None = None
        self.confirmed_atm_premium: float | None = None
        self.lead_time_ms: float | None = None
        self.futures_points_warning_to_confirmation: float | None = None
        self.atm_points_warning_to_confirmation: float | None = None
        self.false_reversal_count = 0
        self.recovered_original_direction = False
        self.last_false_reversal_ns: int | None = None

    def update(
        self,
        score: float,
        *,
        now_ns: int,
        data_quality: DataQuality = DataQuality.GOOD,
        futures_price: float | None = None,
        atm_premium: float | None = None,
    ) -> ReversalObservation:
        self.recovered_original_direction = False
        if data_quality is not DataQuality.GOOD:
            return self._observation(score)
        direction = 1 if score >= self.stable_threshold else -1 if score <= -self.stable_threshold else 0
        if self.stable_direction == 0 and direction:
            self.stable_direction = direction
            self._reset_candidate()
            return self._observation(score)
        opposite = (
            self.stable_direction != 0
            and direction == -self.stable_direction
            and abs(score) >= self.flip_threshold
        )
        if not opposite:
            if self.candidate_direction and direction == self.stable_direction:
                self.false_reversal_count += 1
                self.recovered_original_direction = True
                self.last_false_reversal_ns = now_ns
            if direction == self.stable_direction or abs(score) < self.stable_threshold:
                self._reset_candidate()
            return self._observation(score)
        if self.candidate_direction != direction:
            self.candidate_direction = direction
            self.first_warning_ns = now_ns
            self.forming_ns = None
            self.confirmed_ns = None
            self.warning_futures_price = futures_price
            self.warning_atm_premium = atm_premium
            self.confirmed_futures_price = None
            self.confirmed_atm_premium = None
            self.lead_time_ms = None
            self.futures_points_warning_to_confirmation = None
            self.atm_points_warning_to_confirmation = None
            self.state = ReversalState.PRESSURE_FLIP
            return self._observation(score)
        held = now_ns - (self.first_warning_ns or now_ns)
        if held >= self.confirmation_ns_required:
            self.state = ReversalState.REVERSAL_CONFIRMED
            self.confirmed_ns = self.confirmed_ns or now_ns
            self.confirmed_futures_price = futures_price
            self.confirmed_atm_premium = atm_premium
            self.lead_time_ms = held / 1_000_000.0
            if futures_price is not None and self.warning_futures_price is not None:
                self.futures_points_warning_to_confirmation = (
                    futures_price - self.warning_futures_price
                )
            if atm_premium is not None and self.warning_atm_premium is not None:
                self.atm_points_warning_to_confirmation = (
                    atm_premium - self.warning_atm_premium
                )
            self.stable_direction = direction
            self.candidate_direction = 0
        elif held >= self.forming_ns_required:
            self.state = ReversalState.REVERSAL_FORMING
            self.forming_ns = self.forming_ns or now_ns
        return self._observation(score)

    def _reset_candidate(self) -> None:
        self.state = ReversalState.STABLE_DIRECTION
        self.candidate_direction = 0
        self.first_warning_ns = None
        self.forming_ns = None
        self.confirmed_ns = None
        self.warning_futures_price = None
        self.warning_atm_premium = None
        self.confirmed_futures_price = None
        self.confirmed_atm_premium = None
        self.lead_time_ms = None
        self.futures_points_warning_to_confirmation = None
        self.atm_points_warning_to_confirmation = None

    def _observation(self, score: float) -> ReversalObservation:
        return ReversalObservation(
            self.state,
            self.stable_direction,
            self.candidate_direction,
            self.first_warning_ns,
            self.forming_ns,
            self.confirmed_ns,
            score,
            self.warning_futures_price,
            self.warning_atm_premium,
            self.confirmed_futures_price,
            self.confirmed_atm_premium,
            self.lead_time_ms,
            self.futures_points_warning_to_confirmation,
            self.atm_points_warning_to_confirmation,
            self.false_reversal_count,
            self.recovered_original_direction,
            self.last_false_reversal_ns,
        )
