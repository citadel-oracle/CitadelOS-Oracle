import hashlib
import json
from pathlib import Path
import pytest
from scripts.run_e8d_month_replay import run_replay as run_e8d_replay, MONTH_SESSIONS as E8D_SESSIONS
from scripts.run_e9_month_replay import run_full_month, RESULTS_DIR as E9_RESULTS_DIR


CERTIFIED_BASELINE_DIR = Path(
    "reports/personal_strategy_replay/e9_certified_ledger_baseline_20260808"
)
CERTIFIED_LEDGER_HASHES = {
    "S01_TRADES.jsonl": "3b9c52e89853d77eb3e64a27101adb07731d9f4651f6426cec719511484799cf",
    "S05_CE_TRADES.jsonl": "faaf9c37f1f243096bfa8ee38777e520f05822a6d3778c5bafd4536dea4b439f",
    "S05_PE_TRADES.jsonl": "77ff1ed6ca5ac272d7eb4f5283cd6216faa29442748df099c1e56ca6ddf5a414",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_e9_trade_lifecycle_parity():
    """E9 output must match the explicitly certified E9 ledger baseline.

    The source E8D-R1 ledger files are a documented missing legacy artifact;
    this test deliberately never presents the E9 baseline as recovered E8D-R1
    data.
    """
    
    # Run full month E9 replay generator
    run_full_month()
    
    # Load E9 trade output jsonl files
    s01_lines = [json.loads(l) for l in open(E9_RESULTS_DIR / "S01_TRADES.jsonl")]
    ce_lines  = [json.loads(l) for l in open(E9_RESULTS_DIR / "S05_CE_TRADES.jsonl")]
    pe_lines  = [json.loads(l) for l in open(E9_RESULTS_DIR / "S05_PE_TRADES.jsonl")]
    
    assert len(s01_lines) == 10, f"Expected 10 S01 trades, got {len(s01_lines)}"
    assert len(ce_lines) == 3, f"Expected 3 S05_CE trades, got {len(ce_lines)}"
    assert len(pe_lines) == 1, f"Expected 1 S05_PE trade, got {len(pe_lines)}"
    
    total_trades = len(s01_lines) + len(ce_lines) + len(pe_lines)
    assert total_trades == 14, f"Expected 14 total trades, got {total_trades}"

    metrics = json.loads((CERTIFIED_BASELINE_DIR / "METRICS.json").read_text())
    assert metrics["metric_baseline"] == {
        "s01_trades": 10,
        "s05_ce_trades": 3,
        "s05_pe_trades": 1,
        "total_trades": 14,
        "partial_signals": 257,
        "valid_triggers": 14,
    }
    assert metrics["legacy_e8d_r1_source_ledger_artifact"] == "MISSING_LEGACY_ARTIFACT"

    for ledger_name, expected_hash in CERTIFIED_LEDGER_HASHES.items():
        baseline_path = CERTIFIED_BASELINE_DIR / ledger_name
        generated_path = E9_RESULTS_DIR / ledger_name
        assert _sha256(baseline_path) == expected_hash, f"Certified baseline corrupt: {ledger_name}"
        assert _sha256(generated_path) == expected_hash, f"E9 ledger regression: {ledger_name}"


def test_dashboard_does_not_drive_scanner():
    """Verify GET Oracle/dashboard projection call does not trigger strategy re-evaluation."""
    from src.eye.oracle_projection.projection_service import EyeOracleProjectionService
    
    svc = EyeOracleProjectionService()
    
    # Count evaluations or snapshots before
    eval_count_before = getattr(svc.runtime_state, "_eval_count", 0)
    
    # Call get_projection
    proj = svc.get_projection("NIFTY", "5m")
    
    eval_count_after = getattr(svc.runtime_state, "_eval_count", 0)
    
    assert eval_count_before == eval_count_after, "Dashboard GET endpoint triggered strategy evaluation!"
