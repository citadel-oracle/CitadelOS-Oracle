"""Offline Raw-to-Canonical Replay Runner for Eye Engine Option Capture."""

from pathlib import Path
from src.eye.option_capture.replay import OfflineReplayEngine
from src.eye.option_capture.raw_journal import RawJournalWriter
from src.eye.option_capture.contracts import RawPacketType


def replay_session(session_dir: Path):
    print("=== PHASE E4A-E: OFFLINE REPLAY RUNNER ===")
    journal_dir = session_dir / "raw_packets"
    if not journal_dir.exists():
        writer = RawJournalWriter(session_dir)
        writer.write_packet("SESS:1", RawPacketType.REST_RESPONSE, "/v2/optionchain", b'{"status": "ok"}')

    engine = OfflineReplayEngine(session_dir)
    status, summary = engine.execute_replay()
    print(f"Replay Result: {status} | Packets: {summary['raw_packets_replayed']}")
    return status


if __name__ == "__main__":
    import sys
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/Users/ayushmudgal/Documents/trading/citadel_quant_engine/data/eye_option_capture/demo")
    target_dir.mkdir(parents=True, exist_ok=True)
    replay_session(target_dir)
