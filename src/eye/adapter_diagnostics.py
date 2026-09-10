"""Adapter Diagnostics & Diagnostic Auditing Utilities for Eye Engine E2A."""

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple
from src.eye.adapter_result import AdapterResult, AdapterDiagnostics, AdapterAbstention


@dataclass(frozen=True, kw_only=True, slots=True)
class AdapterDiagnosticSummary:
    total_records: int
    total_abstentions: int
    total_diagnostics: int
    max_rounding_delta: float
    producers_audited: Tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_abstentions": self.total_abstentions,
            "total_diagnostics": self.total_diagnostics,
            "max_rounding_delta": self.max_rounding_delta,
            "producers_audited": list(self.producers_audited),
        }


def summarize_diagnostics(results: Sequence[AdapterResult]) -> AdapterDiagnosticSummary:
    rec_count = 0
    abs_count = 0
    diag_count = 0
    max_delta = 0.0
    producers = set()

    for r in results:
        producers.add(r.producer)
        rec_count += len(r.records)
        abs_count += len(r.abstentions)
        diag_count += len(r.diagnostics)
        for d in r.diagnostics:
            if d.rounding_delta > max_delta:
                max_delta = d.rounding_delta

    return AdapterDiagnosticSummary(
        total_records=rec_count,
        total_abstentions=abs_count,
        total_diagnostics=diag_count,
        max_rounding_delta=max_delta,
        producers_audited=tuple(sorted(producers)),
    )
