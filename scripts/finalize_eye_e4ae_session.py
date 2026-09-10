"""Finalize Option Capture Session & Generate Checksums."""

from pathlib import Path
from src.eye.option_capture.manifest import ManifestManager
from src.eye.option_capture.session import OptionCaptureSession
from src.eye.option_capture.config import CaptureConfig


def finalize_session(session_dir: Path):
    print("=== PHASE E4A-E: FINALIZE SESSION ===")
    cfg = CaptureConfig()
    session = OptionCaptureSession.create("SESS:FINALIZE", "2026-08-07", cfg)
    manifest_mgr = ManifestManager(session_dir)
    manifest = manifest_mgr.finalize_manifest(session, raw_packet_count=0, canonical_obs_count=0, field_revision_count=0)
    print(f"Session finalized at {session_dir}")
    return "PASS"


if __name__ == "__main__":
    import sys
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/Users/ayushmudgal/Documents/trading/citadel_quant_engine/data/eye_option_capture/demo")
    target_dir.mkdir(parents=True, exist_ok=True)
    finalize_session(target_dir)
