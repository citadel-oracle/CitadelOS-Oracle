"""E3 Fresh Process Determinism Test Suite across PYTHONHASHSEED values."""

import os
import sys
import subprocess
import pytest


def test_fresh_process_determinism_across_hash_seeds():
    cmd = [
        sys.executable,
        "-c",
        "from src.eye.composer.deduplication import generate_setup_key; print(generate_setup_key('S1', 'UNDERLYING_INDEX:NIFTY', 'BULLISH', ['E1', 'E2']))"
    ]

    seeds = ["0", "42", "1337", "2026"]
    hashes = []
    for s in seeds:
        env = {**os.environ, "PYTHONHASHSEED": s, "PYTHONPATH": "."}
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True, cwd="/Users/ayushmudgal/Developer/CitadelOS-Worktrees/eye-e3-composer")
        hashes.append(proc.stdout.strip())

    assert len(set(hashes)) == 1
