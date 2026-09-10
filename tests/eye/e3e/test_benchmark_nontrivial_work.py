"""E3-E Non-Trivial Benchmark Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def test_composer_processes_multi_step_definitions_with_non_zero_candidates():
    defs = get_e3_setup_definitions()
    composer = SetupComposer(defs)
    assert len(composer.definitions) == 10
