"""E3-D Real Computational Work Benchmark Test Suite."""

import pytest
from scripts.benchmark_eye_e3_composer import generate_benchmark_events
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def test_benchmark_events_generate_non_zero_candidates():
    events = generate_benchmark_events(50)
    composer = SetupComposer(get_e3_setup_definitions())
    for e in events:
        composer.process_event(e)
    assert len(composer.candidates) > 0
