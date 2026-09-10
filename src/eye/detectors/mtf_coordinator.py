"""Multi-Timeframe Non-Repainting Closed-Bar Coordinator for Eye Engine E2B."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult, DetectorAbstention, DetectorAbstentionReason


class MultiTimeframeCoordinator:
    def __init__(self, target_timeframes: Sequence[str] = ("1m", "3m", "5m", "15m")) -> None:
        self.target_timeframes = tuple(target_timeframes)

    def validate_htf_completion(
        self,
        base_bars_1m: Sequence[DetectorBar],
        htf_timeframe: str,
        context: DetectorContext,
    ) -> Tuple[bool, Optional[DetectorAbstention]]:
        """Verifies if higher-timeframe bar is 100% closed and available as of evaluation watermark."""
        if not base_bars_1m:
            return False, DetectorAbstention(
                code=DetectorAbstentionReason.MISSING_CONSTITUENT_BAR,
                reason="Base 1m bars sequence is empty",
            )

        # Check for duplicate constituent bars
        seen_keys = set()
        for b in base_bars_1m:
            if b.bar_key in seen_keys:
                return False, DetectorAbstention(
                    code=DetectorAbstentionReason.DUPLICATE_BAR,
                    reason=f"Duplicate constituent 1m bar {b.bar_key} found in HTF aggregation",
                )
            seen_keys.add(b.bar_key)

        htf_minutes = 3 if htf_timeframe == "3m" else 5 if htf_timeframe == "5m" else 15 if htf_timeframe == "15m" else 1
        if len(base_bars_1m) < htf_minutes:
            return False, DetectorAbstention(
                code=DetectorAbstentionReason.INCOMPLETE_HIGHER_TIMEFRAME,
                reason=f"Insufficient constituent 1m bars ({len(base_bars_1m)}/{htf_minutes}) for complete {htf_timeframe} bar",
            )

        last_bar = base_bars_1m[-1]
        if not last_bar.is_closed or last_bar.available_at > context.as_of:
            return False, DetectorAbstention(
                code=DetectorAbstentionReason.INCOMPLETE_HIGHER_TIMEFRAME,
                reason=f"Final 1m constituent bar is not closed or available as of {context.as_of.isoformat()}",
            )

        return True, None
