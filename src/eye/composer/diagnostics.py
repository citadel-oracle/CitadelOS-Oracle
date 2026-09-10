"""Composer Diagnostics & Summary Reporting for Eye Engine E3."""

from dataclasses import dataclass
from typing import Sequence
from src.eye.composer.contracts import SetupCandidateRecord, PartialMatch


@dataclass(frozen=True)
class ComposerSummary:
    total_candidates: int
    confirmed_candidates: int
    invalidated_candidates: int
    families_represented: tuple


def summarize_composition(candidates: Sequence[SetupCandidateRecord]) -> ComposerSummary:
    confirmed = sum(1 for c in candidates if c.status.value == "CONFIRMED")
    invalidated = sum(1 for c in candidates if c.status.value == "INVALIDATED")
    families = tuple(sorted(set(c.setup_family for c in candidates)))
    return ComposerSummary(
        total_candidates=len(candidates),
        confirmed_candidates=confirmed,
        invalidated_candidates=invalidated,
        families_represented=families,
    )
