"""Offline Replay Harness for Eye Engine E2B Atomic Detectors."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.eye.contracts import InstrumentIdentity, EvaluationContext
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorReplayParityResult:
    detector_family: str
    is_parity: bool
    incremental_records_count: int
    full_records_count: int
    matching_event_keys: Tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_family": self.detector_family,
            "is_parity": self.is_parity,
            "incremental_records_count": self.incremental_records_count,
            "full_records_count": self.full_records_count,
            "matching_event_keys": list(self.matching_event_keys),
        }


class OfflineDetectorReplayHarness:
    def __init__(self) -> None:
        self._detectors = {
            "swing": SwingStateDetector(),
            "structure": StructureBreakDetector(),
            "liquidity": LiquidityDetector(),
            "displacement": DisplacementDetector(),
            "fvg": FVGClusterDetector(),
        }

    def run_detector_replay(
        self,
        *,
        detector_key: str,
        bars: Sequence[DetectorBar],
        instrument_identity: InstrumentIdentity,
        timeframe: str,
    ) -> Sequence[DetectorResult]:
        detector = self._detectors.get(detector_key)
        if not detector:
            raise ValueError(f"Unknown detector key: {detector_key}")

        results: List[DetectorResult] = []

        for i in range(1, len(bars) + 1):
            sub_bars = bars[:i]
            t = sub_bars[-1].expected_close_time
            ctx = DetectorContext(instrument=instrument_identity, timeframe=timeframe, as_of=t)
            res = detector.detect(sub_bars, ctx)
            results.append(res)

        return results
