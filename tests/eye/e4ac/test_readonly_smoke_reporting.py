"""E4A-C Test for Read-Only Smoke Reporting Integrity."""

import pytest
from scripts.run_eye_e4a_readonly_smoke import run_smoke


def test_readonly_smoke_execution():
    # Executes without error or order endpoint invocation
    run_smoke()
