"""E4A-C Test for Requirement Traceability Matrix Integrity."""

import pytest
from pathlib import Path


def test_requirement_traceability_matrix_file_exists():
    matrix_file = Path(__file__).parent / "E4AC_REQUIREMENT_MATRIX.md"
    assert matrix_file.exists()
    content = matrix_file.read_text()
    assert "PROVEN_BY_TEST" in content
    assert "PROVEN_BY_DIRECT_EXECUTION" in content
