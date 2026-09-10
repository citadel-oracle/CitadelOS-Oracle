"""E4A-G Test for Continuous Timestamped Underlying Feed Observation."""

from datetime import datetime, timezone
import pytest
from src.eye.option_capture.canonical_writer import CanonicalWriter


def test_continuous_underlying_observations(tmp_path):
    writer = CanonicalWriter(tmp_path)

    # Emit multiple continuous timestamped underlying observations
    timestamps = [
        "2026-08-07T10:15:00.000Z",
        "2026-08-07T10:15:05.000Z",
        "2026-08-07T10:15:10.000Z",
        "2026-08-07T10:15:15.000Z",
    ]
    prices = [24590.0, 24592.5, 24595.0, 24597.8]

    for idx, (ts, px) in enumerate(zip(timestamps, prices)):
        obs = {
            "observation_id": f"UND:{idx+1}",
            "instrument_key": "NSE:NIFTY:UNDERLYING_INDEX",
            "observed_at": ts,
            "available_at": ts,
            "evaluation_as_of": ts,
            "index_value": px,
        }
        writer.write_underlying_observation(obs)

    assert writer.underlying_count == 4
    # Ensure underlying observation file exists and contains 4 lines
    u_file = tmp_path / "underlying_observations.jsonl"
    assert u_file.exists()
    lines = u_file.read_text().strip().split("\n")
    assert len(lines) == 4
