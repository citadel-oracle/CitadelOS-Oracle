"""Append-Only Raw Packet Journal Writer for Eye Engine Option Capture."""

import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.eye.option_capture.contracts import RawPacketRecord, RawPacketType
from src.eye.option_capture.endpoint_guard import redact_text


class RawJournalWriter:
    def __init__(self, session_dir: Path):
        self.raw_dir = session_dir / "raw_packets"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self.journal_file = self.raw_dir / "raw_journal.jsonl"
        self.index_file = self.raw_dir / "raw_packet_index.jsonl"

        self.byte_offset = self.journal_file.stat().st_size if self.journal_file.exists() else 0
        self.packet_count = 0

    def write_packet(
        self,
        session_id: str,
        packet_type: RawPacketType,
        endpoint_or_feed: str,
        payload: bytes,
        sequence_number: Optional[int] = None,
        security_id: Optional[str] = None,
        response_code: Optional[int] = None,
        declared_length: Optional[int] = None,
        actual_length: Optional[int] = None,
        exchange_segment: Optional[int] = None,
        decode_status: str = "SUCCESS",
    ) -> RawPacketRecord:
        """Appends a raw packet to the journal file and writes a raw index record."""
        t_utc = datetime.now(timezone.utc).isoformat()
        t_mono = time.monotonic_ns()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        payload_len = len(payload)
        actual_len = actual_length if actual_length is not None else payload_len

        self.packet_count += 1
        pkt_id = f"PKT:{self.packet_count}"

        # Write raw bytes/text securely with credential redaction
        if isinstance(payload, bytes):
            try:
                text_payload = payload.decode("utf-8")
                safe_text = redact_text(text_payload)
                line_data = json.dumps({
                    "packet_id": pkt_id,
                    "session_id": session_id,
                    "packet_type": packet_type.value,
                    "endpoint_or_feed": endpoint_or_feed,
                    "received_at_utc": t_utc,
                    "payload": safe_text,
                }) + "\n"
            except UnicodeDecodeError:
                line_data = json.dumps({
                    "packet_id": pkt_id,
                    "session_id": session_id,
                    "packet_type": packet_type.value,
                    "endpoint_or_feed": endpoint_or_feed,
                    "received_at_utc": t_utc,
                    "payload_sha256": payload_sha256,
                    "payload_len": payload_len,
                }) + "\n"

        line_bytes = line_data.encode("utf-8")
        current_offset = self.byte_offset

        with open(self.journal_file, "ab") as f:
            f.write(line_bytes)
            f.flush()

        self.byte_offset += len(line_bytes)

        rec = RawPacketRecord(
            packet_id=pkt_id,
            session_id=session_id,
            packet_type=packet_type,
            endpoint_or_feed=endpoint_or_feed,
            received_at_utc=t_utc,
            received_monotonic_ns=t_mono,
            payload_size_bytes=payload_len,
            payload_sha256=payload_sha256,
            raw_journal_file=str(self.journal_file),
            byte_offset=current_offset,
            sequence_number=sequence_number,
            security_id=security_id,
            response_code=response_code,
            declared_length=declared_length,
            actual_length=actual_len,
            exchange_segment=exchange_segment,
            decode_status=decode_status,
        )

        with open(self.index_file, "a") as f_idx:
            idx_dict = {
                "packet_id": rec.packet_id,
                "session_id": rec.session_id,
                "packet_type": rec.packet_type.value,
                "endpoint_or_feed": rec.endpoint_or_feed,
                "received_at_utc": rec.received_at_utc,
                "received_monotonic_ns": rec.received_monotonic_ns,
                "payload_size_bytes": rec.payload_size_bytes,
                "payload_sha256": rec.payload_sha256,
                "raw_journal_file": rec.raw_journal_file,
                "byte_offset": rec.byte_offset,
                "sequence_number": rec.sequence_number,
                "security_id": rec.security_id,
                "response_code": rec.response_code,
                "declared_length": rec.declared_length,
                "actual_length": rec.actual_length,
                "exchange_segment": rec.exchange_segment,
                "decode_status": rec.decode_status,
            }
            f_idx.write(json.dumps(idx_dict) + "\n")

        return rec
