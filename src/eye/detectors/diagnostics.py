"""Detector Diagnostics Aggregation Utilities for Eye Engine E2B."""

from dataclasses import dataclass
from typing import Any, Sequence, Tuple
from src.eye.detectors.detector_result import DetectorResult


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectorDiagnosticSummary:
    total_records: int
    total_abstentions: int
    families_detected: Tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_abstentions": self.total_abstentions,
            "families_detected": list(self.families_detected),
        }


def summarize_detector_results(results: Sequence[DetectorResult]) -> DetectorDiagnosticSummary:
    rec_count = sum(len(r.records) for r in results)
    abs_count = sum(len(r.abstentions) for r in results)
    families = tuple(sorted(set(r.detector_family for r in results)))

    return DetectorDiagnosticSummary(
        total_records=rec_count,
        total_abstentions=abs_count,
        families_detected=families,
    )
