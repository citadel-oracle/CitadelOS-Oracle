"""Canonical Knowledge-Time Event Ordering for Eye Engine E3."""

from typing import List, Sequence
from src.eye.contracts import EyeEventRecord


def get_event_knowledge_time(event: EyeEventRecord):
    """Return canonical sorting key tuple representing knowledge availability time."""
    t_as_of = event.evaluation_context.as_of
    t_detected = event.detected_at
    t_close = event.source_bars[-1].expected_close_time if event.source_bars else t_detected
    return (t_as_of, t_detected, t_close, event.event_key, event.event_revision)


def sort_events_canonically(events: Sequence[EyeEventRecord]) -> List[EyeEventRecord]:
    """Sort sequence of EyeEventRecord objects canonically by knowledge availability time."""
    return sorted(events, key=get_event_knowledge_time)
