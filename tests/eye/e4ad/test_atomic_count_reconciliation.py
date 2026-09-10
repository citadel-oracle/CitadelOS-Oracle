"""E4A-D Test for Atomic Event Count Reconciliation."""

import pytest
from scripts.run_eye_e3e_historical_composition import run_e3e_historical_composition


def test_e3_historical_composition_atomic_count_execution():
    res = run_e3e_historical_composition()
    assert res == "PASS"
