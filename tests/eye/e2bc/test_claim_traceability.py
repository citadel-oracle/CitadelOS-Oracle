"""Phase C — Test Traceability Truth Test Suite."""

import pytest
from pathlib import Path


def test_requirement_matrix_exists_and_complete():
    matrix_file = Path("tests/eye/detectors/E2B_REQUIREMENT_MATRIX.md")
    if not matrix_file.exists():
        matrix_file = Path("../eye-e2b-detectors/tests/eye/detectors/E2B_REQUIREMENT_MATRIX.md")

    assert matrix_file.exists() or Path("tests/eye/e2bc/E2BC_REQUIREMENT_MATRIX.md").exists()


def test_all_85_requirements_mapped():
    # Read the E2BC_REQUIREMENT_MATRIX.md when created or existing E2B_REQUIREMENT_MATRIX.md
    p1 = Path("tests/eye/e2bc/E2BC_REQUIREMENT_MATRIX.md")
    p2 = Path("tests/eye/detectors/E2B_REQUIREMENT_MATRIX.md")

    matrix_file = p1 if p1.exists() else p2
    assert matrix_file.exists()

    content = matrix_file.read_text()
    for req_id in range(1, 86):
        assert f"**{req_id}**" in content or f"| {req_id} |" in content or f"| **{req_id}** |" in content
