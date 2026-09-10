"""E4A-F Test for Pytest Collection Count Truth."""

import pytest
import subprocess
import sys


def test_pytest_collection_truth():
    cmd = [sys.executable, "-m", "pytest", "tests/eye/", "--collect-only", "-q"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "collected" in res.stdout or "items" in res.stdout
