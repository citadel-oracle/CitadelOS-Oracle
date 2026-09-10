"""E4A-E Test for Deterministic Offline Raw-to-Canonical Replay."""

import pytest
from pathlib import Path
from src.eye.option_capture.replay import OfflineReplayEngine
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.contracts import RawPacketType


def test_offline_replay_engine(tmp_path):
    writer = RawJournalWriter(tmp_path)
    writer.write_packet("SESS:1", RawPacketType.REST_RESPONSE, "/v2/optionchain", b'{"status": "ok"}')

    replay_engine = OfflineReplayEngine(tmp_path)
    status, summary = replay_engine.execute_replay()

    assert status == "REPLAY_PARITY_PASS"
    assert summary["raw_packets_replayed"] == 1
