"""Checkpoint & State Recovery Manager for Eye Engine Option Capture."""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class CaptureCheckpoint:
    checkpoint_id: str
    session_id: str
    created_at_utc: str
    connection_epoch: int
    latest_universe_revision_number: int
    last_raw_packet_id: str
    last_raw_byte_offset: int
    canonical_observation_count: int
    field_revision_count: int
    manifest_fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointManager:
    def __init__(self, session_dir: Path):
        self.chk_dir = session_dir / "checkpoints"
        self.chk_dir.mkdir(parents=True, exist_ok=True)

    def create_checkpoint(
        self,
        session_id: str,
        connection_epoch: int,
        universe_revision_number: int,
        last_raw_packet_id: str,
        last_raw_byte_offset: int,
        canonical_observation_count: int,
        field_revision_count: int,
    ) -> CaptureCheckpoint:
        """Writes a periodic checkpoint file to disk."""
        now_str = datetime.now(timezone.utc).isoformat()
        chk_count = len(list(self.chk_dir.glob("checkpoint_*.json"))) + 1
        chk_id = f"CHK:{chk_count}"

        raw_str = f"{session_id}:{chk_id}:{last_raw_byte_offset}:{canonical_observation_count}"
        fp = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

        chk = CaptureCheckpoint(
            checkpoint_id=chk_id,
            session_id=session_id,
            created_at_utc=now_str,
            connection_epoch=connection_epoch,
            latest_universe_revision_number=universe_revision_number,
            last_raw_packet_id=last_raw_packet_id,
            last_raw_byte_offset=last_raw_byte_offset,
            canonical_observation_count=canonical_observation_count,
            field_revision_count=field_revision_count,
            manifest_fingerprint=fp,
        )

        file_path = self.chk_dir / f"checkpoint_{chk_count:04d}.json"
        file_path.write_text(json.dumps(chk.to_dict(), indent=2))
        return chk

    def load_latest_checkpoint(self) -> Optional[CaptureCheckpoint]:
        """Loads the most recent valid checkpoint file if present."""
        chk_files = sorted(self.chk_dir.glob("checkpoint_*.json"))
        if not chk_files:
            return None
        latest = chk_files[-1]
        try:
            data = json.loads(latest.read_text())
            return CaptureCheckpoint(**data)
        except Exception:
            return None
