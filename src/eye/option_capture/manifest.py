"""Manifest & SHA-256 Checksum Manager for Eye Engine Option Capture."""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from src.eye.option_capture.session import OptionCaptureSession


class ManifestManager:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.manifest_path = session_dir / "manifest.json"
        self.checksums_path = session_dir / "checksums.sha256"

    def generate_checksums(self) -> Dict[str, str]:
        """Calculates SHA-256 hash for every file in the session directory."""
        checksums = {}
        lines = []
        for file in sorted(self.session_dir.rglob("*")):
            if file.is_file() and file.name not in ("checksums.sha256", "manifest.json"):
                rel_path = str(file.relative_to(self.session_dir))
                sha = hashlib.sha256(file.read_bytes()).hexdigest()
                checksums[rel_path] = sha
                lines.append(f"{sha}  {rel_path}\n")

        self.checksums_path.write_text("".join(lines))
        return checksums

    def finalize_manifest(
        self,
        session: OptionCaptureSession,
        raw_packet_count: int,
        canonical_obs_count: int,
        field_revision_count: int,
        finalization_status: str = "COMPLETE_SESSION",
    ) -> Dict[str, Any]:
        """Finalizes and writes manifest.json and checksums.sha256."""
        checksums = self.generate_checksums()
        session_dict = session.to_dict()

        manifest_data = {
            "schema_version": "1.0.0",
            "session": session_dict,
            "counts": {
                "raw_packets": raw_packet_count,
                "canonical_observations": canonical_obs_count,
                "field_revisions": field_revision_count,
            },
            "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
            "finalization_status": finalization_status,
            "checksums": checksums,
        }

        self.manifest_path.write_text(json.dumps(manifest_data, indent=2))
        return manifest_data
