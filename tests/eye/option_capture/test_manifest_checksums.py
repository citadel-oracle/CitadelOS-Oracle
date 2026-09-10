"""E4A-E Test for Manifest Generation & SHA-256 Checksums File."""

import pytest
from pathlib import Path
from src.eye.option_capture.manifest import ManifestManager
from src.eye.option_capture.session import OptionCaptureSession
from src.eye.option_capture.config import CaptureConfig


def test_manifest_and_checksum_generation(tmp_path):
    mgr = ManifestManager(tmp_path)
    (tmp_path / "test_data.txt").write_text("sample content")

    cfg = CaptureConfig()
    sess = OptionCaptureSession.create("SESS:1", "2026-08-07", cfg)
    manifest = mgr.finalize_manifest(sess, raw_packet_count=10, canonical_obs_count=5, field_revision_count=8)

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "checksums.sha256").exists()
    assert manifest["counts"]["raw_packets"] == 10
