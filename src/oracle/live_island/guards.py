"""Architectural Guards for Stability, Snapshot Reconnection, and Universe Integrity."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class StableUniverseGuard:
    """Guards cross-strike detectors against spurious alerts caused by dynamic ATM rolling.

    When underlying spot moves and the active strike window (ATM +/- N) shifts, newly added
    or dropped strikes would otherwise create artificial jumps in aggregate metrics (like
    aggregate PCR, Buyers/Writers share, or total Call/Put OI).

    This guard ensures that rolling comparison only evaluates the INTERSECTION of identical
    strikes present in both the reference window and the current sample.
    """

    def __init__(self, initial_universe_version: str = "v1") -> None:
        self.universe_version = initial_universe_version
        self._current_strikes: Set[str] = set()
        self._reference_strikes: Dict[str, Set[str]] = {}  # window_name -> set of strike keys

    def update_universe(self, strike_keys: List[str], version: Optional[str] = None) -> bool:
        """Updates the active constituent strike universe. Returns True if universe keys changed."""
        new_set = set(k for k in strike_keys if k)
        if version:
            self.universe_version = version
        if new_set != self._current_strikes:
            self._current_strikes = new_set
            return True
        return False

    def get_common_intersection(
        self,
        current_data: Dict[str, Any],
        baseline_data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """Filters both current and baseline strike dictionaries to the exact mutual intersection.

        Returns (filtered_current, filtered_baseline, common_strike_count).
        """
        common_keys = set(current_data.keys()) & set(baseline_data.keys())
        filtered_curr = {k: current_data[k] for k in common_keys}
        filtered_base = {k: baseline_data[k] for k in common_keys}
        return filtered_curr, filtered_base, len(common_keys)

    def validate_cross_strike_sample(
        self,
        current_keys: Set[str],
        reference_keys: Set[str],
        min_overlap_ratio: float = 0.70,
    ) -> bool:
        """Checks if sufficient strike overlap exists to compute a reliable delta."""
        if not reference_keys:
            return False
        common = current_keys & reference_keys
        overlap = len(common) / float(len(reference_keys))
        return overlap >= min_overlap_ratio


class SnapshotSuppressionGuard:
    """Suppresses fake market-change alerts during initial snapshot hydration and reconnects.

    During feed type 0 (initial_feed) or after an epoch increment, market data packets reflect
    cumulative session state rather than a sudden live delta. This guard ensures detectors only
    arm after BASELINE_READY has been achieved.
    """

    def __init__(self) -> None:
        self._current_feed_epoch: int = 1
        self._is_baseline_ready: bool = False

    def on_feed_epoch_change(self, new_epoch: int) -> None:
        """Called when WebSocket reconnects or increments epoch."""
        if new_epoch != self._current_feed_epoch:
            self._current_feed_epoch = new_epoch
            self._is_baseline_ready = False
            logger.info("SnapshotSuppressionGuard: Feed epoch updated to %d. Baselines disarmed.", new_epoch)

    def set_baseline_ready(self, ready: bool) -> None:
        self._is_baseline_ready = ready

    def should_suppress(self, is_snapshot: bool, feed_epoch: int) -> bool:
        """Returns True if the packet must NOT trigger live delta alerts."""
        if is_snapshot:
            return True
        if feed_epoch != self._current_feed_epoch:
            return True
        if not self._is_baseline_ready:
            return True
        return False
