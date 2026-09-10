"""Session Life-Cycle & Metadata Identity for Eye Engine Option Capture."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.eye.option_capture.contracts import CaptureSessionState
from src.eye.option_capture.config import CaptureConfig


@dataclass
class OptionCaptureSession:
    session_id: str
    capture_date: str
    started_at_utc: str
    state: CaptureSessionState
    config: CaptureConfig
    instrument_master_fingerprint: str = ""
    expiry_list_fingerprint: str = ""
    coverage_policy_fingerprint: str = ""
    software_commit: str = "4db6dfd"
    finalized_at_utc: Optional[str] = None
    authority: str = "READ_ONLY_OBSERVATION"
    execution_authority: bool = False

    @classmethod
    def create(cls, session_id: str, capture_date: str, config: CaptureConfig) -> "OptionCaptureSession":
        config.validate()
        now_str = datetime.now(timezone.utc).isoformat()
        return cls(
            session_id=session_id,
            capture_date=capture_date,
            started_at_utc=now_str,
            state=CaptureSessionState.PLANNED,
            config=config,
        )

    def transition_to(self, new_state: CaptureSessionState) -> None:
        self.state = new_state
        if new_state in (CaptureSessionState.COMPLETE, CaptureSessionState.FINALIZING):
            if not self.finalized_at_utc:
                self.finalized_at_utc = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["config"] = asdict(self.config)
        d["config"]["storage_root"] = str(self.config.storage_root)
        return d
