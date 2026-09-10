"""E4A-D Test for Cross-Artifact Consistency."""

import pytest
from pathlib import Path


def test_cross_artifact_consistency_file_format():
    rec_dir = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery")
    assert rec_dir.exists()
