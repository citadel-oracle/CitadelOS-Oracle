"""Abrupt Termination & Crash Recovery Manager for Eye Engine Option Capture."""

import json
from pathlib import Path
from typing import Tuple, List, Dict, Any


class RecoveryManager:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.journal_file = session_dir / "raw_packets" / "raw_journal.jsonl"
        self.index_file = session_dir / "raw_packets" / "raw_packet_index.jsonl"

    def scan_and_recover(self) -> Tuple[bool, int, int]:
        """Scans raw_journal.jsonl for corrupt tail lines and truncates to valid JSON line boundary.

        Returns:
            Tuple[recovered_flag, valid_line_count, truncated_bytes]
        """
        if not self.journal_file.exists():
            return False, 0, 0

        content = self.journal_file.read_bytes()
        lines = content.split(b"\n")

        valid_lines = []
        truncated_bytes = 0
        corrupt_tail_found = False

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                # Test line parsing
                json.loads(line.decode("utf-8"))
                valid_lines.append(line)
            except Exception:
                # Incomplete or truncated trailing line
                corrupt_tail_found = True
                truncated_bytes += len(line)

        if corrupt_tail_found:
            new_content = b"\n".join(valid_lines) + (b"\n" if valid_lines else b"")
            self.journal_file.write_bytes(new_content)

            rec_report = {
                "recovered": True,
                "valid_lines_retained": len(valid_lines),
                "corrupt_bytes_truncated": truncated_bytes,
                "status": "WAL_RECOVERY_SUCCESS",
            }
            (self.session_dir / "recovery_report.json").write_text(json.dumps(rec_report, indent=2))
            return True, len(valid_lines), truncated_bytes

        return False, len(valid_lines), 0
