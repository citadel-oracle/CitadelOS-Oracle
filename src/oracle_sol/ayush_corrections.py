"""User-labelled analysis corrections. Never market evidence or an auto-training feed."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime


class AyushCorrectionLedger:
    """Explicit isolated root; append-only, fsynced, idempotent user records.

    No HTTP/provider dependency. A caller must supply an actual user correction
    and its original thesis identity; nothing is pre-labelled by the model.
    """
    def __init__(self, storage_dir: str):
        self.root = Path(storage_dir)

    def append(self, *, session_id: str, recorded_at: str, thesis_id: str,
               input_revision: int, model_thesis: dict, user_choice: str,
               disagreement: str, prioritized_evidence: list[str],
               overweighted_evidence: list[str], missed_evidence: list[str],
               category: str, author: str = "Ayush") -> str:
        import fcntl
        stamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None or not all((session_id, thesis_id, user_choice, disagreement, author)):
            raise ValueError("A timestamped, attributed correction and thesis identity are required")
        if not isinstance(input_revision, int) or isinstance(input_revision, bool):
            raise ValueError("input_revision must be an integer")
        payload = dict(session_id=session_id, recorded_at=recorded_at, thesis_id=thesis_id,
            input_revision=input_revision, model_thesis=model_thesis, user_choice=user_choice,
            disagreement=disagreement, prioritized_evidence=prioritized_evidence,
            overweighted_evidence=overweighted_evidence, missed_evidence=missed_evidence,
            category=category, author=author, status="USER_ANNOTATION_NOT_CANONICAL_EVIDENCE")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = hashlib.sha256(encoded.encode()).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "ayush_corrections.jsonl").open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            records = [json.loads(line) for line in stream if line.strip()]
            if not any(row["correction_id"] == identity for row in records):
                stream.write(json.dumps({"correction_id": identity, **payload}, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return identity
