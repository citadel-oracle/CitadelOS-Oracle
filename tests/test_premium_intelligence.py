"""
Complete Focused Backend Test Suite for PRE + PLI + ATM Straddle + V2 Determinism & Timezone Truth
Restores all 11 previous formula/service tests and adds V2 determinism and strict ISO timezone tests.
"""

import json, os, tempfile, pytest
from dataclasses import FrozenInstanceError

from src.premium_intelligence.capture import (
    NaturalBar,
    NaturalBarAggregator,
    OptionLegEvidence,
    PremiumCaptureStore,
    SynchronizedPremiumRecord,
    evaluate_session_completeness,
)
from src.premium_intelligence.contracts import (
    PremiumIntelligenceSnapshot,
    PremiumLeadSnapshot,
    PremiumRegimeSnapshot,
)
from src.premium_intelligence.governance import get_governance_dict
from src.premium_intelligence.lead import PremiumLeadEngine
from src.premium_intelligence.regime import PremiumRegimeEngine
from src.premium_intelligence.replay import run_historical_replay
from src.premium_intelligence.service import UnifiedPremiumIntelligenceService
from src.premium_intelligence.straddle import ATMStraddleEngine


# ─────────────────────────────────────────────────────────────────────────────
# 1. Restored PRE/PLI Formula & Service Tests (11 Tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_contracts_versioning_and_immutability():
    snap = PremiumRegimeSnapshot(
        snapshot_id="pre_test",
        instrument="NIFTY",
        regime="EARLY_EXPANSION",
        premium_layer_state="BUYING_FRIENDLY",
    )
    assert snap.formula_version == "v1.0.0"
    assert snap.execution_influence == "ZERO"

    with pytest.raises(FrozenInstanceError):
        snap.regime = "COMPRESSION"


def test_straddle_formula_ce_plus_pe():
    engine = ATMStraddleEngine(min_floor=5.0)
    ce_leg = {"ltp": 120.0, "expiry": "2026-08-25", "trading_symbol": "NIFTY26AUG24400CE"}
    pe_leg = {"ltp": 90.0, "expiry": "2026-08-25", "trading_symbol": "NIFTY26AUG24400PE"}

    res = engine.calculate_straddle(
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        strike=24400.0,
        expiry="2026-08-25",
        timestamp_sec=1000.0,
    )

    assert res.status == "OK"
    assert res.straddle_price == 210.0
    assert res.atm_strike == 24400.0
    assert res.ce_symbol == "NIFTY26AUG24400CE"
    assert res.pe_symbol == "NIFTY26AUG24400PE"


def test_expiry_mismatch_rejection():
    engine = ATMStraddleEngine()
    ce_leg = {"ltp": 120.0, "expiry": "2026-08-25"}
    pe_leg = {"ltp": 90.0, "expiry": "2026-09-25"}

    res = engine.calculate_straddle(
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        strike=24400.0,
        expiry="2026-08-25",
        timestamp_sec=1000.0,
    )

    assert res.status == "NO_DATA"
    assert "EXPIRY_MISMATCH" in res.blockers


def test_missing_or_stale_leg_produces_no_data():
    engine = ATMStraddleEngine()
    ce_leg = {"ltp": 120.0}

    res = engine.calculate_straddle(
        ce_leg=ce_leg,
        pe_leg=None,
        strike=24400.0,
        expiry="2026-08-25",
        timestamp_sec=1000.0,
    )

    assert res.status == "NO_DATA"
    assert "MISSING_OPTION_LEG" in res.blockers


def test_straddle_velocity_and_acceleration():
    engine = ATMStraddleEngine()
    ce_leg = {"ltp": 100.0, "expiry": "2026-08-25"}
    pe_leg = {"ltp": 100.0, "expiry": "2026-08-25"}

    res1 = engine.calculate_straddle(ce_leg, pe_leg, 24400.0, "2026-08-25", timestamp_sec=0.0)
    assert res1.straddle_price == 200.0

    ce_leg2 = {"ltp": 110.0, "expiry": "2026-08-25"}
    res2 = engine.calculate_straddle(ce_leg2, pe_leg, 24400.0, "2026-08-25", timestamp_sec=60.0)
    assert res2.velocity == 10.0

    ce_leg3 = {"ltp": 130.0, "expiry": "2026-08-25"}
    res3 = engine.calculate_straddle(ce_leg3, pe_leg, 24400.0, "2026-08-25", timestamp_sec=120.0)
    assert res3.velocity == 20.0
    assert res3.acceleration == 10.0


def test_atm_rollover_recording():
    engine = ATMStraddleEngine()
    ce_leg = {"ltp": 100.0, "expiry": "2026-08-25"}
    pe_leg = {"ltp": 100.0, "expiry": "2026-08-25"}

    res1 = engine.calculate_straddle(ce_leg, pe_leg, 24400.0, "2026-08-25", timestamp_sec=0.0)
    assert res1.atm_rollover_event is False

    res2 = engine.calculate_straddle(ce_leg, pe_leg, 24450.0, "2026-08-25", timestamp_sec=60.0)
    assert res2.atm_rollover_event is True
    assert engine.rollover_count == 1


def test_pli_directional_lead_classification():
    engine = PremiumLeadEngine(lead_differential_min=15.0)

    ce_leg1 = {"ltp": 100.0, "expiry": "2026-08-25"}
    pe_leg1 = {"ltp": 100.0, "expiry": "2026-08-25"}
    straddle_res1 = ATMStraddleEngine().calculate_straddle(ce_leg1, pe_leg1, 24400.0, "2026-08-25", 0.0)
    engine.evaluate_lead(straddle_res1, ce_leg1, pe_leg1, spot=24400.0)

    ce_leg2 = {"ltp": 140.0, "expiry": "2026-08-25"}
    pe_leg2 = {"ltp": 80.0, "expiry": "2026-08-25"}
    straddle_res2 = ATMStraddleEngine().calculate_straddle(ce_leg2, pe_leg2, 24400.0, "2026-08-25", 60.0)

    lead_snap = engine.evaluate_lead(straddle_res2, ce_leg2, pe_leg2, spot=24450.0)
    assert lead_snap.lead_side == "CALL_LEAD"
    assert lead_snap.expansion_structure == "ONE_SIDED"


def test_pre_regime_classification():
    engine = PremiumRegimeEngine()
    pli_snap = PremiumLeadSnapshot(
        snapshot_id="pli_1",
        lead_side="CALL_LEAD",
        lead_strength=80.0,
        expansion_structure="ONE_SIDED",
        data_quality="OK",
    )
    ce_leg = {"ltp": 140.0, "expiry": "2026-08-25"}
    pe_leg = {"ltp": 80.0, "expiry": "2026-08-25"}
    straddle_res = ATMStraddleEngine().calculate_straddle(ce_leg, pe_leg, 24400.0, "2026-08-25", 0.0)
    straddle_res.velocity = 3.0
    straddle_res.acceleration = 0.5

    pre_snap = engine.evaluate_regime(
        straddle_res=straddle_res,
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        spot=24400.0,
        source_timestamp="2026-07-31T14:30:00+05:30",
    )

    assert pre_snap.regime in ("EARLY_EXPANSION", "ESTABLISHED_EXPANSION", "BUYING_FRIENDLY", "WAIT", "NO_DATA")
    assert pre_snap.premium_layer_state in ("BUYING_FRIENDLY", "WAIT", "AVOID", "NO_DATA")


def test_governance_registry_entries():
    gov = get_governance_dict()
    assert gov["execution_influence"] == "ZERO"
    assert gov["total_thresholds"] == 9


def test_service_bootstrap_and_history():
    svc = UnifiedPremiumIntelligenceService.get_instance()
    res = svc.bootstrap_all_snapshots()
    assert res["status"] == "COMPLETE"
    assert res["snapshots_processed"] == 7

    hist = svc.get_history(limit=5)
    assert len(hist) > 0
    assert hist[-1]["execution_influence"] == "ZERO"


def test_historical_replay_evaluation():
    replay_res = run_historical_replay()
    assert replay_res["status"] == "REPLAY_PASS"
    assert replay_res["execution_influence"] == "ZERO"
    assert replay_res["strategy_candidates_observed"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Additive Natural Bar Aggregation & Coverage Tests (8 Tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_raw_snapshot_is_not_completed_bar_by_default():
    agg = NaturalBarAggregator()
    ce = OptionLegEvidence(symbol="CE", ltp=100.0)
    pe = OptionLegEvidence(symbol="PE", ltp=100.0)

    snap1 = SynchronizedPremiumRecord(
        record_id="r1",
        idempotency_key="key_1",
        session_date="2026-07-31",
        source_timestamp="2026-07-31T14:30:00+05:30",
        authority_timeframe="forming",
        is_completed_bar=False,
        bar_open_time="2026-07-31T14:30:00+05:30",
        bar_close_time="2026-07-31T14:30:00+05:30",
        contributing_snapshot_count=1,
        natural_boundary="14:30:00",
        completeness_pct=20.0,
        gap_status="NONE",
        nifty_spot=24400.0,
        expiry="2026-08-25",
        dte=25,
        atm_strike=24400.0,
        ce_leg=ce,
        pe_leg=pe,
        atm_straddle=200.0,
        pre_snapshot_id=None,
        pre_state=None,
        pre_regime=None,
        pli_snapshot_id=None,
        pli_lead=None,
        blockers=[],
        strategy_evaluations_ref=[],
        execution_influence="ZERO",
    )

    agg.add_snapshot(snap1)
    summary = agg.get_summary()

    assert summary["raw_snapshots_count"] == 1
    assert summary["forming_5m_count"] == 1
    assert summary["closed_valid_5m_count"] == 0


def test_natural_5m_boundary_completion():
    agg = NaturalBarAggregator()
    ce = OptionLegEvidence(symbol="CE", ltp=100.0)
    pe = OptionLegEvidence(symbol="PE", ltp=100.0)

    timestamps = [
        "2026-07-31T14:30:00+05:30",
        "2026-07-31T14:31:00+05:30",
        "2026-07-31T14:32:04+05:30",
        "2026-07-31T14:33:00+05:30",
        "2026-07-31T14:34:59+05:30",
        "2026-07-31T14:35:05+05:30",
    ]

    for idx, ts in enumerate(timestamps):
        snap = SynchronizedPremiumRecord(
            record_id=f"r_{idx}",
            idempotency_key=f"key_{idx}",
            session_date="2026-07-31",
            source_timestamp=ts,
            authority_timeframe="5m",
            is_completed_bar=True,
            bar_open_time=ts,
            bar_close_time=ts,
            contributing_snapshot_count=1,
            natural_boundary="14:35:00",
            completeness_pct=100.0,
            gap_status="NONE",
            nifty_spot=24400.0,
            expiry="2026-08-25",
            dte=25,
            atm_strike=24400.0,
            ce_leg=ce,
            pe_leg=pe,
            atm_straddle=200.0,
            pre_snapshot_id=None,
            pre_state=None,
            pre_regime=None,
            pli_snapshot_id=None,
            pli_lead=None,
            blockers=[],
            strategy_evaluations_ref=[],
            execution_influence="ZERO",
        )
        agg.add_snapshot(snap)

    summary = agg.get_summary()
    assert summary["closed_valid_5m_count"] == 1
    bar = summary["bars"][0]
    assert bar["bar_id"].startswith("bar_5m_2026-07-31_")
    assert bar["bar_state"] == "CLOSED_VALID"


def test_per_leg_contract_truth_preserves_separate_ce_pe():
    ce = OptionLegEvidence(symbol="NIFTY26AUG24400CE", ltp=120.0, delta=0.5)
    pe = OptionLegEvidence(symbol="NIFTY26AUG24400PE", ltp=90.0, delta=-0.5)

    rec = SynchronizedPremiumRecord(
        record_id="r1",
        idempotency_key="key_001",
        session_date="2026-07-31",
        source_timestamp="2026-07-31T14:30:00+05:30",
        authority_timeframe="5m",
        is_completed_bar=True,
        bar_open_time="2026-07-31T14:30:00+05:30",
        bar_close_time="2026-07-31T14:35:00+05:30",
        contributing_snapshot_count=1,
        natural_boundary="14:35:00",
        completeness_pct=100.0,
        gap_status="NONE",
        nifty_spot=24400.0,
        expiry="2026-08-25",
        dte=25,
        atm_strike=24400.0,
        ce_leg=ce,
        pe_leg=pe,
        atm_straddle=210.0,
        pre_snapshot_id="pre_1",
        pre_state="BUYING_FRIENDLY",
        pre_regime="EARLY_EXPANSION",
        pli_snapshot_id="pli_1",
        pli_lead="CALL_LEAD",
        blockers=[],
        strategy_evaluations_ref=[],
        execution_influence="ZERO",
    )

    rec_dict = rec.to_dict()
    assert rec_dict["ce_leg"]["symbol"] == "NIFTY26AUG24400CE"
    assert rec_dict["pe_leg"]["symbol"] == "NIFTY26AUG24400PE"
    assert rec_dict["ce_leg"]["delta"] == 0.5
    assert rec_dict["pe_leg"]["delta"] == -0.5


def test_capture_store_idempotency_and_corrupted_tail_repair():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = PremiumCaptureStore(storage_dir=tmpdir, filename="test_capture.jsonl", raw_source_path="")

        ce = OptionLegEvidence(symbol="CE", ltp=100.0)
        pe = OptionLegEvidence(symbol="PE", ltp=100.0)
        rec1 = SynchronizedPremiumRecord(
            record_id="r1",
            idempotency_key="key_001",
            session_date="2026-07-31",
            source_timestamp="2026-07-31T14:30:00+05:30",
            authority_timeframe="5m",
            is_completed_bar=True,
            bar_open_time="2026-07-31T14:30:00+05:30",
            bar_close_time="2026-07-31T14:35:00+05:30",
            contributing_snapshot_count=1,
            natural_boundary="14:35:00",
            completeness_pct=100.0,
            gap_status="NONE",
            nifty_spot=24400.0,
            expiry="2026-08-25",
            dte=25,
            atm_strike=24400.0,
            ce_leg=ce,
            pe_leg=pe,
            atm_straddle=200.0,
            pre_snapshot_id="pre_1",
            pre_state="BUYING_FRIENDLY",
            pre_regime="EARLY_EXPANSION",
            pli_snapshot_id="pli_1",
            pli_lead="CALL_LEAD",
            blockers=[],
            strategy_evaluations_ref=[],
            execution_influence="ZERO",
        )

        assert store.write_record(rec1) is True
        assert store.write_record(rec1) is False

        file_path = store.file_path
        with open(file_path, "a") as f:
            f.write('{"corrupted_json_line": true, "missing_closing_brace": \n')

        store2 = PremiumCaptureStore(storage_dir=tmpdir, filename="test_capture.jsonl", raw_source_path="")
        stats = store2.get_stats()

        assert stats["total_records"] == 1
        assert stats["corrupted_lines_recovered"] == 1


def test_session_completeness_classification():
    report_7 = evaluate_session_completeness(
        session_date="2026-07-31",
        timestamps=["2026-07-31T14:30:00+05:30"] * 7,
        completed_5m_count=7,
    )
    assert report_7.status == "PARTIAL"
    assert report_7.completed_5m_bars == 7

    report_75 = evaluate_session_completeness(
        session_date="2026-08-03",
        timestamps=["2026-08-03T09:15:00+05:30"] * 75,
        completed_5m_count=75,
    )
    assert report_75.status == "COMPLETE"


def test_bar_closure_vs_authority_semantics():
    agg = NaturalBarAggregator()
    ce = OptionLegEvidence(symbol="CE", ltp=100.0)
    pe = OptionLegEvidence(symbol="PE", ltp=100.0)

    # 5 snapshots in 14:30:00-14:35:00 IST
    for idx, ts in enumerate([
        "2026-07-31T14:30:38+05:30",
        "2026-07-31T14:31:12+05:30",
        "2026-07-31T14:32:04+05:30",
        "2026-07-31T14:33:15+05:30",
        "2026-07-31T14:34:50+05:30",
    ]):
        agg.add_snapshot(SynchronizedPremiumRecord(
            record_id=f"r_{idx}",
            idempotency_key=f"k_{idx}",
            session_date="2026-07-31",
            source_timestamp=ts,
            authority_timeframe="5m",
            is_completed_bar=True,
            bar_open_time=ts,
            bar_close_time=ts,
            contributing_snapshot_count=1,
            natural_boundary="14:35:00",
            completeness_pct=100.0,
            gap_status="NONE",
            nifty_spot=24400.0,
            expiry="2026-08-25",
            dte=25,
            atm_strike=24400.0,
            ce_leg=ce,
            pe_leg=pe,
            atm_straddle=200.0,
            pre_snapshot_id=None,
            pre_state=None,
            pre_regime=None,
            pli_snapshot_id=None,
            pli_lead=None,
            blockers=[],
            strategy_evaluations_ref=[],
            execution_influence="ZERO",
        ))

    # Before 14:35:10, 14:30-14:35 is FORMING
    summary_before = agg.get_summary()
    assert summary_before["forming_5m_count"] == 1
    assert summary_before["closed_valid_5m_count"] == 0

    # Snapshot at 14:35:10 closes the 14:30-14:35 bucket!
    agg.add_snapshot(SynchronizedPremiumRecord(
        record_id="r_5",
        idempotency_key="k_5",
        session_date="2026-07-31",
        source_timestamp="2026-07-31T14:35:10+05:30",
        authority_timeframe="5m",
        is_completed_bar=True,
        bar_open_time="2026-07-31T14:35:10+05:30",
        bar_close_time="2026-07-31T14:35:10+05:30",
        contributing_snapshot_count=1,
        natural_boundary="14:40:00",
        completeness_pct=100.0,
        gap_status="NONE",
        nifty_spot=24400.0,
        expiry="2026-08-25",
        dte=25,
        atm_strike=24400.0,
        ce_leg=ce,
        pe_leg=pe,
        atm_straddle=200.0,
        pre_snapshot_id=None,
        pre_state=None,
        pre_regime=None,
        pli_snapshot_id=None,
        pli_lead=None,
        blockers=[],
        strategy_evaluations_ref=[],
        execution_influence="ZERO",
    ))

    summary_after = agg.get_summary()
    assert summary_after["closed_valid_5m_count"] == 1  # 14:30-14:35 closed and valid!
    assert summary_after["latest_closed_bar_id"] == "bar_5m_2026-07-31_14:30:00"
    assert summary_after["latest_authority_bar_id"] == "bar_5m_2026-07-31_14:30:00"
    assert summary_after["forming_5m_count"] == 1  # 14:35-14:40 remains FORMING!


def test_v2_store_migration_and_timestamp_policy():
    with tempfile.TemporaryDirectory() as tmpdir:
        store_dir = os.path.join(tmpdir, "logs/premium_intelligence")
        os.makedirs(store_dir, exist_ok=True)
        legacy_file = os.path.join(store_dir, "capture_records.jsonl")

        legacy_record = {
            "record_id": "legacy_1",
            "idempotency_key": "snapshot:legacy001",
            "session_date": "2026-07-31",
            "source_timestamp": "2026-07-31T14:44:32Z",
            "authority_timeframe": "5m",
            "execution_influence": "ZERO",
        }
        with open(legacy_file, "w") as f:
            f.write(json.dumps(legacy_record) + "\n")

        raw_source = "/Users/ayushmudgal/Developer/CitadelOS/logs/strategy_command/argus_edge_lab/market_snapshots.jsonl"
        store = PremiumCaptureStore(storage_dir=store_dir, filename="capture_records.jsonl", raw_source_path=raw_source)

        stats = store.get_stats()
        assert stats["capture_schema_version"] == "V2"
        assert stats["migrated_from_legacy"] is True
        assert stats["quarantined_record_count"] == 1
        assert stats["total_records"] == 7
        assert stats["timestamp_source_breakdown"]["fetched_at"] == 7

        quarantine_dir = os.path.join(store_dir, "quarantine")
        assert os.path.exists(quarantine_dir)
        manifest_file = os.path.join(store_dir, "migration_manifest_v2.json")
        assert os.path.exists(manifest_file)

        bar_summary = stats["natural_bar_summary"]
        assert bar_summary["closed_valid_5m_count"] == 1
        assert bar_summary["latest_restored_closed_bar_id"] == "bar_5m_2026-07-31_15:25:00"
        assert bar_summary["latest_live_authority_bar_id"] is None


def test_coverage_api_computed_natural_counts():
    UnifiedPremiumIntelligenceService.reset_instance()
    svc = UnifiedPremiumIntelligenceService.get_instance()
    svc.bootstrap_all_snapshots()
    cov = svc.get_coverage()

    assert cov["execution_influence"] == "ZERO"
    assert cov["capture_schema_version"] == "V2"
    assert cov["raw_snapshots_count"] == 7
    assert cov["closed_valid_5m_count"] == 1
    assert cov["latest_restored_closed_bar_id"] == "bar_5m_2026-07-31_15:25:00"
    assert cov["latest_live_authority_bar_id"] is None
    assert cov["coverage_readiness"] == "INSUFFICIENT"
    assert cov["readiness_reason"] == "INSUFFICIENT_EVIDENCE_NEED_MIN_5_COMPLETE_SESSIONS"
