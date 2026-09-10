"""E4A-D Test for Git Scope Integrity."""

import pytest
from pathlib import Path


def test_git_scope_cleanliness():
    # Verify no raw datasets or credentials in test directory
    test_dir = Path(__file__).parent
    for f in test_dir.rglob("*.json"):
        assert "key" not in f.name.lower()
        assert "secret" not in f.name.lower()
