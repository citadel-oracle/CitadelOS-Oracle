"""Idempotent contiguous directional episodes for later research."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts import DirectionalState, FlowProjection


@dataclass(slots=True)
class Episode:
    episode_id: str
    session_id: str
    direction: str
    contract: str | None
    started_at: str
    start_snapshot_id: str
    trigger_option_price: float | None
    futures_price: float | None
    executable_bid: float | None
    executable_ask: float | None
    feature_family_states: Mapping[str, Any]
    data_quality: str
    current_option_price: float | None = None
    current_futures_price: float | None = None
    current_score: float | None = None
    peak_score: float | None = None
    score_path: list[dict[str, Any]] = field(default_factory=list)
    band_crossings: dict[int, str] = field(default_factory=dict)
    mfe: float | None = None
    mae: float | None = None
    time_to_mfe_ms: float | None = None
    time_to_mae_ms: float | None = None
    horizons: dict[str, float | None] = field(default_factory=dict)
    reversal_states: list[dict[str, Any]] = field(default_factory=list)
    final_result: str | None = None
    complete: bool = False


class EpisodeEngine:
    BANDS = (60, 70, 80, 90)

    def __init__(self, *, entry_strength: float = 60.0, rearm_score: float = 0.12):
        self.entry_strength = entry_strength
        self.rearm_score = rearm_score
        self.active: Episode | None = None
        self.completed: list[Episode] = []
        self._seen_snapshots: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._rearmed = True
        self._closed_pending: deque[Episode] = deque()

    def update(
        self,
        projection: FlowProjection,
        *,
        futures_price: float | None = None,
        contract: str | None = None,
        option_price: float | None = None,
        executable_bid: float | None = None,
        executable_ask: float | None = None,
        elapsed_ms: float | None = None,
    ) -> Episode | None:
        if projection.snapshot_id in self._seen_snapshots:
            return self.active
        self._seen_snapshots.add(projection.snapshot_id)
        self._seen_order.append(projection.snapshot_id)
        if len(self._seen_order) > 50_000:
            self._seen_snapshots.discard(self._seen_order.popleft())
        if self.active is not None and self.active.session_id != projection.session_id:
            self._close("SESSION_ROLLOVER", futures_price)
            self._rearmed = True
        directional = projection.directional_state in {DirectionalState.CALL, DirectionalState.PUT}
        strength = projection.call_strength if projection.directional_state is DirectionalState.CALL else projection.put_strength
        if not directional or abs(projection.directional_score) < self.rearm_score:
            if self.active is not None:
                self._close("NEUTRAL_OR_DATA_LOCK", futures_price)
            self._rearmed = True
            return None
        if self.active and self.active.direction != projection.directional_state.value:
            self._close("DIRECTION_FLIP", futures_price)
            self._rearmed = True
        if self.active is None and self._rearmed and strength >= self.entry_strength:
            seed = f"{projection.session_id}|{projection.directional_state.value}|{projection.snapshot_id}"
            episode_id = "flow_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
            self.active = Episode(
                episode_id=episode_id,
                session_id=projection.session_id,
                direction=projection.directional_state.value,
                contract=contract,
                started_at=projection.generated_at,
                start_snapshot_id=projection.snapshot_id,
                trigger_option_price=option_price,
                futures_price=futures_price,
                executable_bid=executable_bid,
                executable_ask=executable_ask,
                feature_family_states=projection.family_values,
                data_quality=projection.data_quality.value,
                horizons={key: None for key in ("100ms", "250ms", "500ms", "1s", "3s", "5s", "10s", "30s")},
            )
            self._rearmed = False
        if self.active is None:
            return None
        self.active.current_option_price = option_price
        self.active.current_futures_price = futures_price
        self.active.current_score = strength
        self.active.peak_score = (
            strength
            if self.active.peak_score is None
            else max(self.active.peak_score, strength)
        )
        self.active.score_path.append(
            {"snapshot_id": projection.snapshot_id, "timestamp": projection.generated_at, "strength": strength}
        )
        if len(self.active.score_path) > 5_000:
            del self.active.score_path[: len(self.active.score_path) - 5_000]
        for band in self.BANDS:
            if strength >= band and band not in self.active.band_crossings:
                self.active.band_crossings[band] = projection.generated_at
        self.active.reversal_states.append(
            {"timestamp": projection.generated_at, "state": projection.reversal_state.value}
        )
        if futures_price is not None and self.active.futures_price is not None:
            signed_move = (futures_price - self.active.futures_price) * (1 if self.active.direction == "CALL" else -1)
            if self.active.mfe is None or signed_move > self.active.mfe:
                self.active.mfe = signed_move
                self.active.time_to_mfe_ms = elapsed_ms
            if self.active.mae is None or signed_move < self.active.mae:
                self.active.mae = signed_move
                self.active.time_to_mae_ms = elapsed_ms
            if elapsed_ms is not None:
                for label, horizon in (("100ms", 100), ("250ms", 250), ("500ms", 500), ("1s", 1000), ("3s", 3000), ("5s", 5000), ("10s", 10000), ("30s", 30000)):
                    if elapsed_ms >= horizon and self.active.horizons[label] is None:
                        self.active.horizons[label] = signed_move
        return self.active

    def close_session(self, result: str = "SESSION_CLOSE") -> Episode | None:
        return self._close(result, None)

    def drain_closed(self) -> tuple[Episode, ...]:
        """Return terminal episodes once so persistence remains append-only/idempotent."""
        values = tuple(self._closed_pending)
        self._closed_pending.clear()
        return values

    def _close(self, result: str, futures_price: float | None) -> Episode | None:
        episode = self.active
        if episode is None:
            return None
        episode.final_result = result
        episode.complete = True
        self.completed.append(episode)
        self._closed_pending.append(episode)
        if len(self.completed) > 2_048:
            del self.completed[: len(self.completed) - 2_048]
        self.active = None
        return episode
