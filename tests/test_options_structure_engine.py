"""Focused certification for the advisory Options Structure Engine."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.ose.engine import OptionsStructureEngine
from src.strategy_lab.option_charts import OptionChartCandleFeed
from src.strategy_lab.service import StrategyLabService


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


class Master:
    def resolve(self, *, security_id, expiry, strike, option_type, underlying="NIFTY"):
        assert underlying == "NIFTY"
        return {
            "security_id": str(security_id), "exchange_segment": "NSE_FNO",
            "lot_size": 65, "source": "TEST_INSTRUMENT_MASTER",
        }


class Dhan:
    def __init__(self, now: datetime):
        self.now = now
        self.calls = []

    def get_intraday_candles(self, **kwargs):
        self.calls.append(kwargs)
        security_id = int(kwargs["security_id"])
        rising = security_id % 2 == 1
        rows = []
        start = self.now.replace(hour=9, minute=15, second=0, microsecond=0)
        minutes = int((self.now.replace(second=0, microsecond=0) - start).total_seconds() // 60)
        for index in range(max(0, minutes)):
            stamp = start + timedelta(minutes=index)
            base = 120 + (index * 0.12 if rising else -index * 0.04)
            rows.append({
                "time": int(stamp.timestamp()), "open": base, "high": base + 1.5,
                "low": base - 1.0, "close": base + (0.7 if rising else -0.3),
                "volume": 1000 + index,
            })
        return {"success": True, "candles": rows}


def option_row(strike: int, base: int):
    return {
        "strike": float(strike),
        "ce": {"security_id": base + 1, "ltp": 150.0 + (24000 - strike) / 10, "volume": 100_000},
        "pe": {"security_id": base + 2, "ltp": 150.0 + (strike - 24000) / 10, "volume": 120_000},
    }


def snapshot(now: datetime, spot: float = 24002.0, expiry: str = "2026-07-28"):
    rows = [option_row(strike, 63000 + index * 2) for index, strike in enumerate(range(23700, 24301, 50))]
    return {
        "status": "available",
        "data": {
            "underlying": {
                "symbol": "NIFTY", "ltp": spot, "expiry": expiry,
                "fetched_at": now.isoformat(), "trading_date": now.date().isoformat(),
            },
            "atm_window": rows,
        },
    }


def participation_snapshot(now: datetime, *, status: str = "available", market_state: str = "OPEN"):
    value = snapshot(now)
    value["status"] = status
    value["data"]["underlying"]["market_state"] = market_state
    value["data"]["dominance"] = {
        "writer_dominance_percentage": 78.0,
        "buyer_dominance_percentage": 22.0,
        "call_writing_score": 41.0,
        "put_writing_score": 37.0,
        "call_buying_score": 11.0,
        "put_buying_score": 11.0,
        "formula": "FROZEN_TEST_FORMULA",
    }
    for row in value["data"]["atm_window"]:
        for side in ("ce", "pe"):
            row[side].update({
                "intraday_price_change": 2.0 if side == "ce" else -2.0,
                "intraday_change_oi": 20.0 if side == "ce" else -20.0,
                "iv": 12.0,
                "top_bid_price": 99.8,
                "top_ask_price": 100.2,
                "top_bid_quantity": 120,
                "top_ask_quantity": 80,
            })
    return value


def spot_file(path: Path, start: datetime, closes: list[float]):
    rows = []
    for index, close in enumerate(closes):
        stamp = start + timedelta(minutes=index)
        rows.append({
            "timestamp": stamp.isoformat(), "time": stamp.timestamp(),
            "open": close - 1, "high": close + 2, "low": close - 2, "close": close,
            "volume": 1000, "closed": True, "is_closed": True,
        })
    path.write_text(json.dumps({"candles": rows}), encoding="utf-8")


def engine(tmp_path: Path, now: datetime):
    spot_path = tmp_path / "vob_1m_candles.json"
    spot_file(spot_path, now.replace(hour=9, minute=15), [24000.0] * max(5, int((now.replace(second=0, microsecond=0) - now.replace(hour=9, minute=15, second=0, microsecond=0)).total_seconds() // 60)))
    return OptionsStructureEngine(
        dhan=Dhan(now), instrument_master=Master(), state_root=tmp_path / "ose",
        spot_candle_path=spot_path, clock=lambda: now,
    )


@pytest.mark.parametrize("spot,anchor", [(23949.9, 23900), (23950, 24000), (24049.9, 24000), (24050, 24100)])
def test_nearest_100_anchor_resolution(spot, anchor):
    assert OptionsStructureEngine.nearest_anchor(spot) == anchor


@pytest.mark.parametrize(
    "spot,ce,pe",
    [
        (24099, 23900, 24200),
        (24100, 24000, 24200),
        (24149, 24000, 24300),
        (24150, 24000, 24300),
        (24199, 24000, 24300),
        (24200, 24100, 24300),
        (24201, 24100, 24400),
        (24299, 24100, 24400),
        (24300, 24200, 24400),
    ],
)
def test_locked_100_point_strike_boundaries(spot, ce, pe):
    selection = OptionsStructureEngine.selection_for_spot(spot)
    assert selection["CE"] == ce
    assert selection["PE"] == pe
    assert selection["CE"] % 100 == selection["PE"] % 100 == 0


def test_pair_is_exactly_100_point_itm_and_same_expiry(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))
    result = ose.projection()
    assert result["anchor"] == 24000
    assert result["contracts"]["CE"]["contract"]["strike"] == 23900
    assert result["contracts"]["PE"]["contract"]["strike"] == 24200
    assert result["contracts"]["CE"]["contract"]["strike"] % 100 == 0
    assert result["contracts"]["PE"]["contract"]["strike"] % 100 == 0
    assert result["contracts"]["CE"]["contract"]["expiry"] == result["contracts"]["PE"]["contract"]["expiry"]
    assert result["contracts"]["CE"]["contract"]["security_id"] != result["contracts"]["PE"]["contract"]["security_id"]


def test_live_flow_and_participation_keep_independent_freshness_when_values_hold(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    first = participation_snapshot(now)
    ose.ingest(first)
    initial = ose.projection()
    initial_flow = initial["option_flow"]
    initial_participation = initial["participation_baseline"]

    later = now + timedelta(minutes=20)
    ose.clock = lambda: later
    ose.dhan.now = later
    ose.ingest(participation_snapshot(later))
    refreshed = ose.projection()

    assert refreshed["option_flow"]["source_timestamp"] == later.isoformat()
    assert refreshed["option_flow"]["status"] == "LIVE"
    assert refreshed["participation_baseline"]["status"] == "LIVE"
    assert refreshed["participation_baseline"]["source_timestamp"] == later.isoformat()
    assert refreshed["participation_baseline"]["values"] == initial_participation["values"]
    assert refreshed["participation_baseline"]["calculation_revision"] != initial_participation["calculation_revision"]
    assert refreshed["option_flow"]["state"] == initial_flow["state"]


def test_stale_source_is_not_masked_by_recalculation_or_publication_time(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(participation_snapshot(now))
    fresh = ose.projection()

    later = now + timedelta(seconds=25)
    ose.clock = lambda: later
    ose.dhan.now = later
    stale = participation_snapshot(now, status="stale")
    stale["data"]["underlying"]["market_state"] = "OPEN"
    ose.ingest(stale)
    result = ose.projection()

    assert result["option_flow"]["status"] == "DATA STALE"
    assert result["option_flow"]["source_timestamp"] == fresh["option_flow"]["source_timestamp"]
    assert result["participation_baseline"]["status"] == "STALE"
    assert result["participation_baseline"]["source_timestamp"] == fresh["participation_baseline"]["source_timestamp"]


def test_post_market_participation_keeps_last_valid_snapshot_without_false_live(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(participation_snapshot(now))
    last_valid = ose.projection()["participation_baseline"]

    closed_at = now + timedelta(minutes=20)
    ose.clock = lambda: closed_at
    ose.dhan.now = closed_at
    ose.ingest(participation_snapshot(closed_at, status="stale", market_state="CLOSED"))
    result = ose.projection()

    assert result["market_state"] == "CLOSED"
    assert result["participation_baseline"]["status"] == "MARKET_CLOSED"
    assert result["participation_baseline"]["values"] == last_valid["values"]
    assert result["participation_baseline"]["source_timestamp"] == last_valid["source_timestamp"]


def test_completed_three_and_five_minute_buckets_reject_forming_groups(tmp_path):
    start = datetime(2026, 7, 22, 9, 15, tzinfo=IST)
    rows = [{
        "timestamp": (start + timedelta(minutes=index)).isoformat(),
        "open": 100 + index, "high": 102 + index, "low": 99 + index,
        "close": 101 + index, "volume": 10, "closed": True,
    } for index in range(9)]
    assert len(OptionsStructureEngine._resample(rows, 3)) == 3
    assert len(OptionsStructureEngine._resample(rows, 5)) == 1
    assert OptionsStructureEngine._resample(rows[:2], 3) == []


def test_spot_boundary_rollover_is_atomic(tmp_path):
    now = datetime(2026, 7, 22, 9, 35, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now, 24000))
    old = ose.projection()
    old_ids = {side: old["contracts"][side]["contract"]["security_id"] for side in ("CE", "PE")}
    later = now + timedelta(minutes=1)
    ose.dhan.now = later
    ose.ingest(snapshot(later, 24100))
    new = ose.projection()
    assert new["anchor"] == 24100
    assert new["contracts"]["CE"]["contract"]["strike"] == 24000
    assert new["contracts"]["PE"]["contract"]["strike"] == 24200
    assert all(new["contracts"][side]["contract"]["security_id"] != old_ids[side] for side in ("CE", "PE"))
    assert new["rollover"]["audit"][0]["from_anchor"] == 24000


def test_expiry_rollover_replaces_both_legs_and_context_atomically(tmp_path):
    now = datetime(2026, 7, 22, 9, 35, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now, 24000, "2026-07-28"))
    old = ose.projection()
    later = now + timedelta(minutes=1)
    ose.dhan.now = later
    ose.ingest(snapshot(later, 24000, "2026-08-04"))
    result = ose.projection()
    assert result["expiry"] == "2026-08-04"
    assert {
        result["contracts"][side]["contract"]["expiry"] for side in ("CE", "PE")
    } == {"2026-08-04"}
    assert result["market_context"]["expiry_source"] == "DHAN_INSTRUMENT_MASTER_OPTION_CHAIN"
    assert result["canonical_digest"] != old["canonical_digest"]
    assert result["rollover"]["audit"][-1]["reason"] == "AUTHORITATIVE_EXPIRY_ROLLOVER"


def test_ce_pe_vob_state_is_isolated_and_completed_only(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))
    result = ose.projection()
    ce, pe = result["contracts"]["CE"], result["contracts"]["PE"]
    assert ce["contract"]["security_id"] != pe["contract"]["security_id"]
    assert ce["candle_buffer_size"] == pe["candle_buffer_size"]
    assert ce["structures"]["3m"]["completed_bucket"] is True
    assert ce["structures"]["5m"]["completed_bucket"] is True
    assert set(ce["structures"]) == {"3m", "5m"}
    assert set(pe["structures"]) == {"3m", "5m"}
    assert (tmp_path / "ose" / f"vob_CE_{ce['contract']['security_id']}_3m.json").exists()
    assert (tmp_path / "ose" / f"vob_PE_{pe['contract']['security_id']}_3m.json").exists()


def test_vob_direction_and_retest_classification_is_deterministic():
    contract = {"trading_symbol": "NIFTY 28 JUL 23900 CE", "security_id": "1"}
    zone = {
        "zone_id": "z", "role": "RESISTANCE", "zone_low": 100, "zone_high": 105,
        "status": "BROKEN", "broken_at": "2026-07-22T09:15:00+05:30", "touch_count": 1,
        "freshness": "FRESH", "distance_points": 2, "strength_score": 80,
    }
    raw = {"timeframe": "5m", "nearest_bullish_support": None, "nearest_bearish_resistance": None, "recently_broken": [zone], "evaluated_through": "2026-07-22T09:25:00+05:30"}
    candles = [{"timestamp": "2026-07-22T09:20:00+05:30", "low": 104, "high": 110, "close": 108}]
    ose = object.__new__(OptionsStructureEngine)
    result = ose._classify_structure(raw, candles, contract)
    assert result["state"] == "BULLISH"
    assert result["supply_break"] is True
    assert result["bullish_retest"] is True
    bearish_zone = {**zone, "role": "SUPPORT", "zone_low": 95, "zone_high": 100}
    bearish_raw = {**raw, "recently_broken": [bearish_zone]}
    bearish_candles = [{"timestamp": "2026-07-22T09:20:00+05:30", "low": 90, "high": 99, "close": 92}]
    bearish = ose._classify_structure(bearish_raw, bearish_candles, contract)
    assert bearish["state"] == "BEARISH"
    assert bearish["demand_break"] is True
    assert bearish["bearish_retest"] is True


def test_ema_21_50_supertrend_and_volatility_zones_use_completed_5m_calculations():
    values = [float(index) for index in range(1, 61)]
    assert OptionsStructureEngine.ema(values, 50) == pytest.approx(35.5, rel=1e-6)
    start = datetime(2026, 7, 22, 9, 15, tzinfo=IST)
    candles = [{
        "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
        "candle_closed_at": (start + timedelta(minutes=5 * (index + 1))).isoformat(),
        "open": 100 + index, "high": 102 + index, "low": 99 + index,
        "close": 101.5 + index, "volume": 100,
    } for index in range(60)]
    value, direction = OptionsStructureEngine.supertrend(candles, 10, 3.4)
    assert value is not None
    assert direction == "POSITIVE"
    ose = object.__new__(OptionsStructureEngine)
    trend = ose._trend(candles)
    assert trend["state"] == "ULTRA BULLISH"
    assert trend["ema_21"] == pytest.approx(
        OptionsStructureEngine.ema([row["close"] for row in candles], 21)
    )
    assert trend["ema_50"] == pytest.approx(
        OptionsStructureEngine.ema([row["close"] for row in candles], 50)
    )
    assert trend["evaluated_through"] == candles[-1]["timestamp"]
    assert trend["atr_period"] == 10 and trend["multiplier"] == 3.4
    assert trend["atr"] == pytest.approx(
        OptionsStructureEngine.atr(candles, 10)
    )
    assert trend["ema_21_zone"]["width"] == pytest.approx(
        max(0.2, trend["atr"] * 0.16), abs=0.1
    )
    assert trend["supertrend_zone"]["low"] < trend["supertrend_value"]
    assert trend["supertrend_zone"]["high"] > trend["supertrend_value"]


def test_argus_selected_contract_technicals_reuse_completed_option_candles(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    result = ose.contract_technicals(
        {
            "side": "CE",
            "security_id": "63001",
            "strike": 24000,
            "expiry": "2026-07-28",
            "trading_symbol": "NIFTY 28 JUL 24000 CE",
            "premium": 184.25,
        },
        now.isoformat(),
    )
    assert result["status"] == "AVAILABLE"
    assert result["security_id"] == "63001"
    assert result["current_premium"] == 184.25
    assert result["completed_5m_premium"] != result["current_premium"]
    assert result["trend"]["ema_21"] is not None
    assert result["trend"]["ema_50"] is not None
    assert result["trend"]["supertrend_value"] is not None
    assert result["vob_3m"]["evaluated_through"] == result["completed_3m_timestamp"]
    assert result["forming_candle_excluded"] is True
    assert result["source"] == "DHAN_DATA_API_COMPLETED_OPTION_CANDLES"
    calls = len(ose.dhan.calls)
    repeated = ose.contract_technicals(
        {
            "side": "CE",
            "security_id": "63001",
            "strike": 24000,
            "expiry": "2026-07-28",
            "premium": 184.25,
        },
        now.isoformat(),
    )
    assert repeated == result
    assert len(ose.dhan.calls) == calls


def test_mixed_trend_and_stale_quality_are_truthful(monkeypatch):
    start = datetime(2026, 7, 22, 9, 15, tzinfo=IST)
    candles = [{
        "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
        "candle_closed_at": (start + timedelta(minutes=5 * (index + 1))).isoformat(),
        "open": 100 + index, "high": 102 + index, "low": 99 + index,
        "close": 101 + index, "volume": 100,
    } for index in range(60)]
    monkeypatch.setattr(OptionsStructureEngine, "supertrend", staticmethod(lambda *_: (200.0, "NEGATIVE")))
    ose = object.__new__(OptionsStructureEngine)
    assert ose._trend(candles)["state"] == "NEUTRAL / MIXED"
    quality = ose._quality(candles, candles, datetime(2026, 7, 23, 9, 15, tzinfo=IST))
    assert quality["freshness"] == "STALE"
    assert quality["status"] == "STALE"


def test_composite_and_duel_scoring_are_transparent_and_deterministic():
    assert OptionsStructureEngine._composite({"state": "ULTRA BULLISH"}, {"state": "ULTRA BULLISH"})["state"] == "FULL BULLISH ALIGNMENT"
    assert OptionsStructureEngine._composite({"state": "BULLISH"}, {"state": "ULTRA BEARISH"})["state"] == "CONFLICT"
    transition = OptionsStructureEngine._composite({"state": "ULTRA BULLISH"}, {"state": "NEUTRAL / MIXED"})
    assert transition == {
        "state": "TRANSITION", "vob_direction": "BULLISH", "trend_direction": "NEUTRAL",
        "explanation": ["VOB strongly bullish", "Trend confirmation incomplete"],
    }
    bearish = OptionsStructureEngine._composite({"state": "BEARISH"}, {"state": "ULTRA BEARISH"})
    assert bearish["explanation"] == ["VOB bearish", "Trend strongly bearish"]
    assert OptionsStructureEngine._duel(84, 31) == {"ce_score": 84, "pe_score": 31, "delta": 53, "state": "CLEAR CALL ADVANTAGE", "label": "CALL +53"}
    assert sum(OptionsStructureEngine.SCORE_WEIGHTS.values()) == 100


def test_projection_serializer_explains_legacy_cached_composites(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose._projection = {
        "contracts": {"PE": {
            "vob": {"state": "ULTRA BULLISH"},
            "trend": {"state": "NEUTRAL / MIXED"},
            "composite": {"state": "TRANSITION", "vob_direction": "BULLISH", "trend_direction": "NEUTRAL"},
        }},
        "performance": {},
    }
    result = ose.projection()
    assert result["contracts"]["PE"]["composite"]["explanation"] == [
        "VOB strongly bullish", "Trend confirmation incomplete",
    ]
    assert "explanation" not in ose._projection["contracts"]["PE"]["composite"]


def test_stale_argus_refresh_preserves_flow_snapshot_and_canonical_digest(tmp_path):
    now = datetime(2026, 7, 22, 16, 0, tzinfo=IST)
    ose = engine(tmp_path, now)
    first = snapshot(now)
    first["status"] = "stale"
    ose.ingest(first)
    initial = ose.projection()
    second = snapshot(now + timedelta(minutes=1))
    second["status"] = "stale"
    ose.ingest(second)
    refreshed = ose.projection()
    assert refreshed["option_flow"]["evaluated_at"] == initial["option_flow"]["evaluated_at"]
    assert refreshed["canonical_digest"] == initial["canonical_digest"]


def test_available_argus_refresh_clears_prior_stale_runtime_state(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))
    stale = snapshot(now + timedelta(seconds=10))
    stale["status"] = "stale"
    ose.ingest(stale)
    assert ose.projection()["status"] == "STALE"

    ose.ingest(snapshot(now + timedelta(seconds=20)))

    result = ose.projection()
    assert result["status"] == "LIVE"
    assert result["runtime_status"] == "LIVE"
    assert result["source_freshness"] == "AVAILABLE"
    assert result["reason"] is None


def test_stale_wrapper_does_not_override_fresh_canonical_open_market_source(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    value = snapshot(now)
    value["status"] = "stale"
    value["cache"] = {"projection_freshness_seconds": 20.0}
    value["data"]["underlying"].update({
        "market_state": "OPEN",
        "source_event_time": (now - timedelta(seconds=2)).isoformat(),
        "fetched_at": (now - timedelta(seconds=30)).isoformat(),
    })

    ose.ingest(value)

    result = ose.projection()
    assert result["status"] == "LIVE"
    assert result["runtime_status"] == "LIVE"
    assert result["source_freshness"] == "AVAILABLE"
    assert result["source_timestamp"] == (now - timedelta(seconds=2)).isoformat()


def test_option_chain_quote_bucket_is_never_persisted_as_authoritative_ohlcv(
    tmp_path,
):
    now = datetime(2026, 7, 22, 10, 30, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))

    later = now + timedelta(minutes=1)
    ose.dhan.now = later
    ose.ingest(snapshot(later))

    for side in ("CE", "PE"):
        contract = ose._state["pair"]["contracts"][side]
        rows = ose._read_candles(contract)
        assert rows
        assert {row["source"] for row in rows} == {"DHAN_DATA_API"}


def test_projection_exposes_canonical_ssi_context_and_agreement_without_score_mutation(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))
    result = ose.projection()
    assert result["score_weights"] == OptionsStructureEngine.SCORE_WEIGHTS
    for side in ("CE", "PE"):
        contract = result["contracts"][side]
        assert contract["ssi"]["score"] == contract["score"]
        assert sum(row["points"] for row in contract["ssi"]["breakdown"]) == contract["score"]
        assert contract["decision_window"]["advisory_only"] is True
        assert contract["engine_agreement"]["execution_influence"] == 0
        assert "latest_state_change" in contract
    assert set(result["engine_agreement"]) == {"CE", "PE"}
    assert len(result["structural_read"]["lines"]) == 3
    assert result["structural_read"]["execution_influence"] == 0


def test_missing_side_degrades_without_inference(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    ose = engine(tmp_path, now)
    broken = snapshot(now)
    broken["data"]["atm_window"] = [row for row in broken["data"]["atm_window"] if row["strike"] != 24200]
    ose.ingest(broken)
    result = ose.projection()
    assert result["status"] == "UNAVAILABLE"
    assert result["contracts"] == {}


def test_option_feed_fanout_is_single_ingestion_and_advisory_failure_isolated(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    feed = OptionChartCandleFeed(dhan=Dhan(now), instrument_master=Master())
    calls = []
    feed.subscribe(lambda value: calls.append(value))
    feed.subscribe(lambda value: (_ for _ in ()).throw(RuntimeError("advisory failure")))
    value = snapshot(now)
    feed.ingest(value)
    feed.ingest(value)
    assert calls == [value]
    assert feed.status()["single_ingestion"] is True
    assert feed.status()["additional_polling"] is False


def test_option_feed_primes_restart_subscriber_from_existing_argus_projection():
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    value = snapshot(now)
    provider_calls = []
    feed = OptionChartCandleFeed(
        dhan=Dhan(now), instrument_master=Master(),
        projection_provider=lambda: provider_calls.append("cached") or value,
    )
    first = []
    second = []

    feed.subscribe(first.append)
    feed.subscribe(second.append)

    assert provider_calls == ["cached"]
    assert first == [value]
    assert second == [value]
    assert feed.status()["additional_polling"] is False


def test_stale_post_market_argus_restores_ose_without_ingesting_strategy_feed(tmp_path):
    now = datetime(2026, 7, 22, 15, 42, tzinfo=IST)
    value = snapshot(now)
    value["status"] = "stale"
    ose = engine(tmp_path, now)
    feed = OptionChartCandleFeed(
        dhan=Dhan(now), instrument_master=Master(), projection_provider=lambda: value,
    )

    feed.subscribe(ose.ingest)

    assert ose.projection()["status"] == "STALE"
    assert feed.status()["status"] == "WAITING_FOR_ARGUS"
    assert feed.status()["sides"]["CE"]["completed_1m"] == 0


def test_service_api_projection_preserves_zero_execution_influence(tmp_path):
    provider = lambda: {
        "status": "LIVE", "executionInfluence": "ZERO", "execution_influence": 0,
        "strategy_influence": 0, "advisory_only": True, "paper_only": True,
        "live_trading_enabled": False, "broker_submission": False,
    }
    service = StrategyLabService(str(tmp_path / "lab"), options_structure_provider=provider)
    result = service.execution_projection([])["options_structure"]
    assert result["executionInfluence"] == "ZERO"
    assert result["execution_influence"] == 0
    assert result["live_trading_enabled"] is False
    assert result["broker_submission"] is False


def test_persisted_pair_and_candles_restore_without_shared_vob_state(tmp_path):
    now = datetime(2026, 7, 22, 15, 12, tzinfo=IST)
    first = engine(tmp_path, now)
    first.ingest(snapshot(now))
    before = first.projection()
    restarted = OptionsStructureEngine(
        dhan=Dhan(now), instrument_master=Master(), state_root=tmp_path / "ose",
        spot_candle_path=tmp_path / "vob_1m_candles.json", clock=lambda: now,
    )
    after = restarted.projection()
    assert after["anchor"] == before["anchor"]
    assert after["contracts"]["CE"]["contract"] == before["contracts"]["CE"]["contract"]
    assert not (tmp_path / "vob_state.json").exists()


def test_restored_large_reservoir_reconciles_current_session_gaps(tmp_path):
    now = datetime(2026, 7, 22, 10, 18, tzinfo=IST)
    first = engine(tmp_path, now)
    first.ingest(snapshot(now))
    pair = first._state["pair"]
    prior_start = now.replace(day=21, hour=9, minute=15, second=0, microsecond=0)
    prior = [{
        "timestamp": (prior_start + timedelta(minutes=index)).isoformat(),
        "candle_closed_at": (prior_start + timedelta(minutes=index + 1)).isoformat(),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": 1000.0, "closed": True, "is_closed": True,
    } for index in range(300)]
    missing_minutes = {7, 23, 41}
    for side in ("CE", "PE"):
        contract = pair["contracts"][side]
        current = [
            row for row in first._read_candles(contract)
            if OptionsStructureEngine._aware(row["timestamp"]).minute not in {
                (now.replace(hour=9, minute=15) + timedelta(minutes=index)).minute
                for index in missing_minutes
            }
        ]
        first._write_candles(contract, [*prior, *current])
        assert len(first._read_candles(contract)) > 250
        assert len(first._current_session_missing(first._read_candles(contract), now)) == 3

    dhan = Dhan(now)
    restarted = OptionsStructureEngine(
        dhan=dhan, instrument_master=Master(), state_root=tmp_path / "ose",
        spot_candle_path=tmp_path / "vob_1m_candles.json", clock=lambda: now,
    )
    restarted.ingest(snapshot(now))

    assert len(dhan.calls) == 2
    assert all(call["from_date"] == now.date().isoformat() for call in dhan.calls)
    for side in ("CE", "PE"):
        contract = restarted._state["pair"]["contracts"][side]
        candles = restarted._read_candles(contract)
        assert restarted._current_session_missing(candles, now) == []
        assert restarted.projection()["contracts"][side]["quality"]["data_gap_count"] == 0


def test_completed_history_reconciles_each_new_minute_and_advances_5m_boundary(tmp_path):
    now = datetime(2026, 7, 22, 10, 15, tzinfo=IST)
    ose = engine(tmp_path, now)
    ose.ingest(snapshot(now))
    before = ose.projection()["contracts"]["CE"]["trend"]["evaluated_through"]
    calls_before = len(ose.dhan.calls)

    later = now + timedelta(minutes=5)
    ose.dhan.now = later
    ose.ingest(snapshot(later))
    after = ose.projection()["contracts"]["CE"]["trend"]["evaluated_through"]

    assert len(ose.dhan.calls) == calls_before + 2
    assert before == now.replace(minute=10).isoformat()
    assert after == now.isoformat()


def test_ose_cache_latency_resilience(tmp_path):
    now = datetime(2026, 7, 22, 10, 45, tzinfo=IST)

    class DelayedDhan(Dhan):
        def __init__(self, now: datetime):
            super().__init__(now)
            self.delay_candle = True

        def get_intraday_candles(self, **kwargs):
            res = super().get_intraday_candles(**kwargs)
            if self.delay_candle and res["success"] and len(res["candles"]) > 0:
                res["candles"] = res["candles"][:-1]
            return res


    dhan = DelayedDhan(now)
    spot_path = tmp_path / "vob_1m_candles.json"
    spot_file(spot_path, now.replace(hour=9, minute=15), [24000.0] * 100)

    ose = OptionsStructureEngine(
        dhan=dhan, instrument_master=Master(), state_root=tmp_path / "ose",
        spot_candle_path=spot_path, clock=lambda: now,
    )

    # Ingest 1: 10:44:00 candle is delayed/missing from Dhan
    ose.ingest(snapshot(now))
    calls_after_first = len(dhan.calls)
    assert ose._history_reconciled_key is None

    # Now simulate Dhan delivering the delayed candle
    dhan.delay_candle = False

    # Ingest 2: same minute, attempt throttle blocks retry
    ose.ingest(snapshot(now + timedelta(seconds=10)))
    assert len(dhan.calls) == calls_after_first

    # Ingest 3: next minute (10:46:00), same 5-minute bucket
    later_same_bucket = now + timedelta(minutes=1)
    dhan.now = later_same_bucket
    ose.ingest(snapshot(later_same_bucket))
    assert len(dhan.calls) == calls_after_first + 2
    assert ose._history_reconciled_key is not None

    # Ingest 4: next minute (10:47:00), still same 5-minute bucket
    even_later_same_bucket = now + timedelta(minutes=2)
    dhan.now = even_later_same_bucket
    calls_before_cache = len(dhan.calls)
    ose.ingest(snapshot(even_later_same_bucket))
    # Verification: Dhan is NOT called because caching intercepts early
    assert len(dhan.calls) == calls_before_cache

    # Ingest 5: next 5-minute boundary (10:50:00). reconciliation key advances to 10:49:00
    next_boundary = now + timedelta(minutes=5)
    dhan.now = next_boundary
    ose.ingest(snapshot(next_boundary))
    assert len(dhan.calls) == calls_before_cache + 2
