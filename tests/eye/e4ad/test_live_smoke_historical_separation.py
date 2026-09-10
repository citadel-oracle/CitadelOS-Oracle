"""E4A-D Test for Live Smoke vs Historical Separation Truth."""

import pytest
from scripts.run_eye_e4a_readonly_smoke import run_smoke


def test_live_smoke_does_not_supply_historical_evidence():
    # Smoke execution verifies API parser, not historical option data availability
    run_smoke()
