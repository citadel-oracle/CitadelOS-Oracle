import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pytest

from src.argus.baseline_store import ArgusBaselineStore
from src.argus.baseline_store import BaselineStoreError
from src.argus.option_chain_engine import OptionChainEngine
from src.api.v2_integration import ProjectionProcessWorker


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


class MutableNow:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class NoNetworkDhan:
    def get_option_expiries(self, **kwargs):
        raise AssertionError("Tests must not call Dhan")

    def get_option_chain(self, **kwargs):
        raise AssertionError("Tests must not call Dhan")


def leg(ltp=100, oi=1000, previous_close=95, previous_oi=800):
    return {
        "security_id": 1,
        "last_price": ltp,
        "previous_close_price": previous_close,
        "oi": oi,
        "previous_oi": previous_oi,
        "volume": 10000,
        "implied_volatility": 12.5,
    }


def chain_response(overrides=None):
    overrides = overrides or {}
    chain = {}
    for strike in range(23950, 24451, 50):
        legs = {"ce": leg(), "pe": leg()}
        for side in ("ce", "pe"):
            legs[side].update(overrides.get((float(strike), side), {}))
        chain[f"{strike:.6f}"] = legs
    return {"status": "success", "data": {"last_price": 24200, "oc": chain}}


def updated_response():
    return chain_response(
        {
            (23950.0, "ce"): {"last_price": 110, "oi": 1100},
            (23950.0, "pe"): {"last_price": 90, "oi": 1100},
            (24000.0, "ce"): {"last_price": 110, "oi": 900},
            (24000.0, "pe"): {"last_price": 90, "oi": 400},
            (24050.0, "ce"): {"last_price": 90, "oi": 1100},
            (24050.0, "pe"): {"last_price": 110, "oi": 1100},
            (24100.0, "ce"): {"last_price": 90, "oi": 900},
            (24100.0, "pe"): {"last_price": 110, "oi": 6000},
            (24150.0, "pe"): {"last_price": 110, "oi": 900},
            (24250.0, "ce"): {"last_price": None},
            (24300.0, "ce"): {"last_price": 90, "oi": 5000},
            (24400.0, "ce"): {"last_price": 90, "oi": 500},
        }
    )


def make_engine(path, now):
    store = ArgusBaselineStore(path=path, now_provider=now)
    return OptionChainEngine(
        dhan=NoNetworkDhan(),
        baseline_store=store,
        now_provider=now,
    )


def build(engine, response, expiry="2026-07-14"):
    return engine.build_snapshot(
        symbol="NIFTY",
        segment="IDX_I",
        security_id="13",
        expiry=expiry,
        response=response,
    )


def strike(snapshot, value):
    return next(row for row in snapshot.strikes if row.strike == value)


def test_phase_one_snapshot_contains_real_chain_foundation_fields():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        snapshot = build(make_engine(path, now), chain_response())

        assert snapshot.symbol == "NIFTY"
        assert snapshot.underlying_ltp == 24200
        assert snapshot.atm_strike == 24200
        assert len(snapshot.strikes) == 11
        assert snapshot.totals.ce_oi == 11000
        assert snapshot.totals.pe_oi == 11000
        assert snapshot.totals.pcr == 1.0
        assert snapshot.totals.day_change_pcr == 1.0
        assert snapshot.walls.highest_ce_oi is not None
        assert snapshot.walls.highest_pe_oi is not None
        assert snapshot.missing_fields == []


def test_process_built_argus_snapshot_matches_in_process_projection():
    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        engine = make_engine(Path(directory) / "baseline.json", now)
        prepared = engine.prepare_snapshot_input(
            "NIFTY", "IDX_I", "13", "2026-07-14", chain_response(),
        )
        expected = engine.build_prepared_snapshot(prepared).to_dict()
        worker = ProjectionProcessWorker(timeout_seconds=5)
        try:
            actual = worker.run("argus_snapshot", prepared)
        finally:
            worker.stop()

        assert actual == expected


def test_baseline_is_created_once_and_survives_restart():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        first = build(make_engine(path, now), chain_response())

        assert first.baseline_status == "ESTABLISHED"
        assert strike(first, 23950).ce.intraday_change_oi == 0
        baseline_timestamp = first.baseline_timestamp
        records = json.loads(path.read_text())["records"]
        assert len(records) == 22

        now.value = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        second = build(make_engine(path, now), updated_response())

        assert second.baseline_status == "AVAILABLE"
        assert second.baseline_timestamp == baseline_timestamp
        assert strike(second, 23950).ce.baseline_oi == 1000
        assert strike(second, 23950).ce.intraday_change_oi == 100
        assert len(json.loads(path.read_text())["records"]) == 22


def test_new_date_and_expiry_create_new_baseline_identities():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        engine = make_engine(path, now)
        build(engine, chain_response(), expiry="2026-07-14")
        assert len(json.loads(path.read_text())["records"]) == 22

        build(engine, chain_response(), expiry="2026-07-21")
        assert len(json.loads(path.read_text())["records"]) == 44

        now.value = datetime(2026, 7, 13, 9, 20, tzinfo=IST)
        build(engine, chain_response(), expiry="2026-07-21")
        assert len(json.loads(path.read_text())["records"]) == 66


def test_day_and_intraday_deltas_and_all_activity_classes_are_distinct():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        engine = make_engine(path, now)
        build(engine, chain_response())
        now.value = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        snapshot = build(engine, updated_response())

        first = strike(snapshot, 23950)
        assert first.ce.day_change_oi == 300
        assert first.ce.intraday_change_oi == 100
        assert first.ce.day_price_change == 15
        assert first.ce.intraday_price_change == 10
        assert first.ce.change_oi_basis == "previous_day"
        assert first.ce.intraday_change_oi_basis == "session_baseline"
        assert first.ce.activity == "CALL_BUYING"
        assert first.pe.activity == "PUT_WRITING"
        assert strike(snapshot, 24000).ce.activity == "CALL_SHORT_COVERING"
        assert strike(snapshot, 24000).pe.activity == "PUT_LONG_UNWINDING"
        assert strike(snapshot, 24050).ce.activity == "CALL_WRITING"
        assert strike(snapshot, 24050).pe.activity == "PUT_BUYING"
        assert strike(snapshot, 24100).ce.activity == "CALL_LONG_UNWINDING"
        assert strike(snapshot, 24100).pe.activity == "PUT_BUYING"
        assert strike(snapshot, 24150).pe.activity == "PUT_SHORT_COVERING"
        assert strike(snapshot, 24200).ce.positioning == "NEUTRAL"
        assert strike(snapshot, 24250).ce.positioning == "INSUFFICIENT_DATA"


def test_window_walls_dominance_and_verdict_are_deterministic():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 9, 20, tzinfo=IST))
        engine = make_engine(path, now)
        build(engine, chain_response())
        now.value = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        snapshot = build(engine, updated_response())

        assert snapshot.atm_strike == 24200
        assert len(snapshot.atm_window) == 11
        assert snapshot.ce_itm_strikes == [23950, 24000, 24050, 24100, 24150]
        assert snapshot.ce_otm_strikes == [24250, 24300, 24350, 24400, 24450]
        assert snapshot.walls.highest_ce_oi.strike == 24300
        assert snapshot.walls.highest_pe_oi.strike == 24100
        assert snapshot.walls.highest_intraday_ce_oi_addition.value == 4000
        assert snapshot.walls.highest_intraday_pe_oi_addition.value == 5000
        assert snapshot.walls.strongest_ce_unwind.value == -500
        assert snapshot.walls.strongest_pe_unwind.value == -600
        scores = snapshot.dominance
        for value in (
            scores.call_writing_score,
            scores.put_writing_score,
            scores.call_buying_score,
            scores.put_buying_score,
            scores.writer_dominance_percentage,
            scores.buyer_dominance_percentage,
            scores.evidence_coverage_percentage,
        ):
            assert 0 <= value <= 100
        assert snapshot.verdict.reasons
        assert any("writer dominance" in reason for reason in snapshot.verdict.reasons)
        assert 0 <= snapshot.verdict.confidence <= 100


def test_outside_session_does_not_create_baseline_and_reset_is_explicit():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        now = MutableNow(datetime(2026, 7, 10, 8, 0, tzinfo=IST))
        engine = make_engine(path, now)
        snapshot = build(engine, chain_response())

        assert snapshot.market_state == "PRE_MARKET"
        assert snapshot.baseline_status == "UNAVAILABLE_OUTSIDE_SESSION"
        assert snapshot.baseline_timestamp is None
        assert snapshot.verdict.regime == "INSUFFICIENT_DATA"
        assert not path.exists()

        now.value = datetime(2026, 7, 10, 9, 20, tzinfo=IST)
        build(engine, chain_response())
        assert path.exists()
        engine.baseline_store.reset(symbol="NIFTY")
        assert json.loads(path.read_text())["records"] == {}


def test_corrupt_persistence_never_silently_resets_baseline():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "baseline.json"
        path.write_text("not-json")
        now = MutableNow(datetime(2026, 7, 10, 10, 0, tzinfo=IST))
        engine = make_engine(path, now)

        try:
            build(engine, chain_response())
        except BaselineStoreError:
            pass
        else:
            raise AssertionError("Corrupt persistence must fail closed")

        assert path.read_text() == "not-json"
