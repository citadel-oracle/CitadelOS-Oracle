"""Phase O — Fresh Process Determinism Test Suite across PYTHONHASHSEED values."""

import os
import sys
import subprocess
import pytest


def test_fresh_process_determinism_across_hash_seeds():
    cmd = [
        sys.executable,
        "-c",
        "from datetime import datetime, timezone; from src.eye.contracts import PriceAtom, InstrumentIdentity; from src.eye.detectors.input_model import DetectorBar, DetectorContext; from src.eye.detectors.displacement import DisplacementDetector; now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc); inst = InstrumentIdentity(raw_symbol='NSE:NIFTY', normalized_symbol='NIFTY', exchange='NSE', instrument_type='UNDERLYING_INDEX', underlying='NIFTY', source='DHAN', market='NSE'); ctx = DetectorContext(instrument=inst, timeframe='5m', as_of=now); bar = DetectorBar(instrument_key='UNDERLYING_INDEX:NIFTY', timeframe='5m', open_time=now, expected_close_time=now, available_at=now, bar_key='NIFTY:5m:0', open=PriceAtom(ticks=2440000), high=PriceAtom(ticks=2455000), low=PriceAtom(ticks=2440000), close=PriceAtom(ticks=2454000), is_closed=True, volume=1000); res = DisplacementDetector().detect([bar], ctx); print(res.records[0].event_key)"
    ]

    seeds = ["0", "42", "1337", "2026"]
    hashes = []
    for s in seeds:
        env = {**os.environ, "PYTHONHASHSEED": s, "PYTHONPATH": "."}
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True, cwd="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/eye-e2bc-validation")
        hashes.append(proc.stdout.strip())

    assert len(set(hashes)) == 1
