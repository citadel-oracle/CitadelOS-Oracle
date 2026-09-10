"""E4A-G Test for Fresh Process Offline Raw-to-Canonical Replay Parity."""

import pytest
from src.eye.option_capture.replay import OfflineReplayEngine
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.contracts import RawPacketType


def test_offline_raw_to_canonical_replay_parity(tmp_path):
    writer = RawJournalWriter(tmp_path)
    writer.write_packet(
        session_id="SESS:REPLAY:30M",
        packet_type=RawPacketType.REST_RESPONSE,
        endpoint_or_feed="/v2/optionchain/expirylist",
        payload=b'{"data":["2026-08-11"]}',
    )

    engine = OfflineReplayEngine(tmp_path)
    status, summary = engine.execute_replay()

    assert status == "REPLAY_PARITY_PASS"
    assert summary["raw_packets_replayed"] == 1
