"""E4A-C Test for E3 Benchmark Scenario Truth & Checksum Distinction."""

import pytest
from scripts.benchmark_eye_e3e_real import generate_benchmark_scenario_events
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def test_no_match_control_produces_zero_candidates():
    events = generate_benchmark_scenario_events(500, "NO_MATCH_CONTROL")
    defs = [d for d in get_e3_setup_definitions() if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "ACTIVE")]
    composer = SetupComposer(defs)

    cands = []
    for e in events:
        cands.extend(composer.process_event(e))

    assert len(cands) == 0
    assert len(composer.candidates) == 0


def test_multi_step_moderate_produces_candidates():
    events = generate_benchmark_scenario_events(500, "MULTI_STEP_MODERATE")
    defs = [d for d in get_e3_setup_definitions() if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "ACTIVE")]
    composer = SetupComposer(defs)

    cands = []
    for e in events:
        cands.extend(composer.process_event(e))

    assert len(cands) > 0
    assert len(composer.candidates) > 0
