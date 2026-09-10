"""Real Data Forensic Replacement & Interactive Eye Acceptance Test Suite for Phase E7A-R."""

import json, os, hashlib, pytest
from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    StrategyLifecycleState,
)
from src.eye.personal_strategies.registry import PersonalStrategyRegistry
from src.eye.personal_strategies.indicators import (
    compute_rsi,
    compute_bollinger_bands,
    compute_atr,
    compute_ema,
    compute_traditional_pivots,
)
from src.eye.personal_strategies.resampler import SessionResampler
from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator
from src.eye.personal_strategies.strategies.s06_opening_momentum_recovery import S06Evaluator
from src.eye.personal_strategies.engine import PersonalStrategyEngine

REAL_COHORT_DIR = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_personal_strategy_acceptance/20260807_real"
QUARANTINE_DIR = "/Users/ayushmudgal/Developer/CitadelOS/reports/eye_personal_strategy_acceptance/e7a_invalid_synthetic_20260807"


def test_acceptance_fixture_has_real_provenance():
    manifest_path = os.path.join(REAL_COHORT_DIR, "manifest.json")
    assert os.path.exists(manifest_path)
    with open(manifest_path) as f:
        data = json.load(f)

    assert data["synthetic"] is False
    assert data["source"] == "AUTHORITATIVE_DHAN_GOLDEN_REPLAY_STREAM"
    assert data["underlying_rows"] == 385
    # security_id=41024: authoritative from logs/dhan_instrument_master.json
    # (previous E7AR value of 10024700 was an agent fabrication — corrected in E7AR-2)
    assert data["option_pe_security_id"] == "41024"
    assert data["option_pe_contract"] == "NIFTY-Aug2026-24700-PE"


def test_synthetic_fixture_cannot_claim_real_acceptance():
    invalidation_path = os.path.join(QUARANTINE_DIR, "STATISTICAL_INVALIDATION.json")
    assert os.path.exists(invalidation_path)
    with open(invalidation_path) as f:
        data = json.load(f)

    assert data["status"] == "STATISTICALLY_INVALIDATED"
    assert data["reason"] == "SYNTHETIC_DATA_MISLABELLED_AS_AUTHORITATIVE_REAL_MARKET_DATA"


def test_acceptance_rows_match_source_hash():
    pe_dest = os.path.join(REAL_COHORT_DIR, "option_pe_24700_1m.json")
    with open(pe_dest, "rb") as f:
        pe_hash = hashlib.sha256(f.read()).hexdigest()

    manifest_path = os.path.join(REAL_COHORT_DIR, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert manifest["synthetic_false_proof"]["pe_sha256"] == pe_hash


def test_real_resampler():
    with open(os.path.join(REAL_COHORT_DIR, "option_pe_24700_1m.json")) as f:
        bars_1m = json.load(f)

    formatted_1m = []
    for b in bars_1m:
        formatted_1m.append({
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "volume": b["volume"],
            "timestamp": "09:15:00"
        })

    res_3 = SessionResampler.resample_1m_to_tf(formatted_1m[:3], 3)
    assert len(res_3) == 1
    assert res_3[0]["is_confirmed"] is True
    assert res_3[0]["open"] == bars_1m[0]["open"]
    assert res_3[0]["close"] == bars_1m[2]["close"]


def test_real_s05_pe_trace():
    with open(os.path.join(REAL_COHORT_DIR, "option_pe_24700_1m.json")) as f:
        bars_1m = json.load(f)

    formatted_1m = []
    for b in bars_1m:
        formatted_1m.append({
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "volume": b["volume"],
            "timestamp": "09:15:00"
        })

    bars_3m = SessionResampler.resample_1m_to_tf(formatted_1m, 3)
    bars_5m = SessionResampler.resample_1m_to_tf(formatted_1m, 5)

    eval_pe = S05Evaluator(option_type="PE")
    sig = eval_pe.evaluate("NIFTY11AUG2624700PE", bars_3m, bars_5m, 180.0, 150.0, 165.0, "15:30:00", bars_3m[-1]["close"])

    assert sig.strategy_id == PersonalStrategyId.S05
    assert sig.direction == "BUY_PE"


def test_s01_missing_ce_data_blocked():
    manifest_path = os.path.join(REAL_COHORT_DIR, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert manifest["option_ce_data_available"] is False


def test_s07_runtime_evaluator_absent():
    engine = PersonalStrategyEngine.get_instance()
    bus = engine.get_signal_bus_summary()
    assert bus["s07_runtime_evaluator_exists"] is False
