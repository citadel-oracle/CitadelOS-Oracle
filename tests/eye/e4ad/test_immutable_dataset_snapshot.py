"""E4A-D Test for Immutable Dataset Snapshot Verification."""

import hashlib
import json
from pathlib import Path
import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "e4ad"


def test_immutable_snapshot_exists_and_matches_sha256():
    snap_path = FIXTURE_DIR / "vob_1m_candles_snapshot_20260806.json"
    assert snap_path.exists(), f"Snapshot file missing at {snap_path}"

    content = snap_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    assert sha256 == "41f77bcea60d0e47c97442dea99a5056139f34f672ea840da1e0f41c4acc1ee2"

    manifest_path = FIXTURE_DIR / "CERTIFIED_MANIFEST.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["source_sha256"] == sha256
    assert manifest["fixture_sha256"] == sha256
    assert manifest["size_bytes"] == len(content)
    assert (FIXTURE_DIR / "SHA256SUMS").read_text().strip() == (
        f"{sha256}  {snap_path.name}"
    )
