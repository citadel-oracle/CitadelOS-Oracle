"""Focused contracts for canonical ARGUS full-market evidence."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.argus.market_snapshot import ArgusMarketSnapshotProvider
from src.argus.option_chain_engine import OptionChainEngine
from src.argus.prime import ArgusPrimeProjection


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class Dhan:
    def __init__(self):
        self.calls = 0
        self.price = 24_310.0

    def get_full_quotes(self, watchlist):
        self.calls += 1
        result = {}
        for name, item in watchlist.items():
            raw = {
                "average_price": 24_280.0,
                "buy_quantity": 600_000,
                "sell_quantity": 400_000,
                "last_price": self.price if name == "NIFTY_FUT" else 150.0,
                "last_quantity": 65,
                "last_trade_time": "29/07/2026 10:00:00",
                "oi": 13_800_000,
                "oi_day_high": 13_900_000,
                "oi_day_low": 13_500_000,
                "volume": 2_700_000,
                "ohlc": {"close": 24_100.0},
                "depth": {
                    "buy": [{"price": 24_309.0, "quantity": 500}] * 5,
                    "sell": [{"price": 24_311.0, "quantity": 250}] * 5,
                },
            }
            result[name] = {
                "status": "AVAILABLE",
                "security_id": str(item["security_id"]),
                "raw": raw,
            }
        return result


def projection(now):
    return {
        "data": {
            "underlying": {
                "ltp": 24_250.0,
                "fetched_at": now.isoformat(),
            },
            "atm_window": [
                {
                    "strike": 24_250.0,
                    "ce": {"security_id": 1001},
                    "pe": {"security_id": 1002},
                }
            ],
        }
    }


def rows():
    return [
        {
            "UNDERLYING_SYMBOL": "BANKNIFTY",
            "INSTRUMENT": "FUTIDX",
            "SECURITY_ID": "99999",
            "SYMBOL_NAME": "BANKNIFTY-Aug2026-FUT",
            "LOT_SIZE": "15",
            "SM_EXPIRY_DATE": "2026-08-25",
        },
        {
            "UNDERLYING_SYMBOL": "NIFTY",
            "INSTRUMENT": "FUTIDX",
            "SECURITY_ID": "58072",
            "SYMBOL_NAME": "NIFTY-Aug2026-FUT",
            "LOT_SIZE": "65",
            "SM_EXPIRY_DATE": "2026-08-25",
        },
        {
            "UNDERLYING_SYMBOL": "NIFTY",
            "INSTRUMENT": "FUTIDX",
            "SECURITY_ID": "68407",
            "SYMBOL_NAME": "NIFTY-Sep2026-FUT",
            "LOT_SIZE": "65",
            "SM_EXPIRY_DATE": "2026-09-29",
        },
    ]


def provider(tmp_path, clock, dhan):
    return ArgusMarketSnapshotProvider(
        dhan,
        state_path=tmp_path / "market.json",
        master_path=tmp_path / "master.json",
        clock=clock,
        master_loader=rows,
    )


def test_near_month_full_quote_is_atomic_batched_and_restart_safe(tmp_path):
    now = datetime(2026, 7, 29, 10, 0, 1, tzinfo=IST)
    clock = Clock(now)
    dhan = Dhan()
    service = provider(tmp_path, clock, dhan)
    first = service.refresh(projection(now))
    second = service.refresh(projection(now))
    assert dhan.calls == 1
    assert first == second
    assert first["futures"]["security_id"] == 58072
    assert first["futures"]["expiry"] == "2026-08-25"
    assert first["futures"]["lot_size"] == 65
    assert first["futures"]["five_level_depth"]["buy"]
    assert set(first["option_market_depth"]) == {"1001", "1002"}
    assert len(json.loads((tmp_path / "master.json").read_text())["rows"]) == 2
    restarted = provider(tmp_path, clock, Dhan())
    assert restarted.latest() == first


def test_snapshot_deltas_use_real_elapsed_time_and_do_not_rewrite_timestamps(tmp_path):
    now = datetime(2026, 7, 29, 10, 0, 1, tzinfo=IST)
    clock = Clock(now)
    dhan = Dhan()
    service = provider(tmp_path, clock, dhan)
    service.refresh(projection(now))
    clock.value = now + timedelta(seconds=60)
    dhan.price += 10
    second = service.refresh(projection(clock.value))
    assert second["futures"]["price_change"] == 10
    assert second["futures"]["price_acceleration_per_minute"] == 10
    assert second["futures"]["source_timestamp"] == "2026-07-29T10:00:00+05:30"
    assert second["futures"]["source_age_seconds"] == 61


def test_fetch_dedup_applies_only_to_the_same_argus_source_snapshot(tmp_path):
    now = datetime(2026, 7, 29, 10, 0, 1, tzinfo=IST)
    clock = Clock(now)
    dhan = Dhan()
    service = provider(tmp_path, clock, dhan)
    service.refresh(projection(now))
    assert dhan.calls == 1

    clock.value = now + timedelta(seconds=1)
    service.refresh(projection(clock.value))

    assert dhan.calls == 2


def test_latest_matches_retained_previous_argus_source(tmp_path):
    now = datetime(2026, 7, 29, 10, 0, 1, tzinfo=IST)
    clock = Clock(now)
    service = provider(tmp_path, clock, Dhan())
    first = service.refresh(projection(now))
    for seconds in range(1, 5):
        clock.value = now + timedelta(seconds=seconds)
        service.refresh(projection(clock.value))

    assert service.latest(first["argus_source_timestamp"]) == first
    assert service.latest("2026-07-29T09:59:59+05:30") is None


def test_futures_confirmation_is_directional_and_stale_fails_closed():
    value = {
        "status": "AVAILABLE",
        "security_id": 58072,
        "symbol": "NIFTY-Aug2026-FUT",
        "expiry": "2026-08-25",
        "source_age_seconds": 1,
        "price_change": 10,
        "price_acceleration_per_minute": 5,
        "oi_change": 1000,
        "quantity_imbalance_percentage": 10,
        "depth_imbalance_percentage": 20,
        "basis_change": 2,
    }
    call = ArgusPrimeProjection._futures_confirmation(value, "CALL")
    put = ArgusPrimeProjection._futures_confirmation(value, "PUT")
    hold = ArgusPrimeProjection._futures_confirmation(value, "HOLD")
    assert call["state"] == "CONFIRMED"
    assert put["state"] == "DIVERGENT"
    assert hold["state"] == "BULLISH"
    assert hold["score"] is None
    assert hold["evidence_coverage"] == 6
    assert hold["reason"] == "LAST_COHERENT_FUTURES_DIRECTIONAL_READ"
    assert hold["directional_score"]["CALL"] > hold["directional_score"]["PUT"]
    stale = ArgusPrimeProjection._futures_confirmation(
        {**value, "source_age_seconds": 21}, "CALL"
    )
    assert stale["status"] == "UNAVAILABLE"
    assert stale["reason"] == "FUTURES_SOURCE_STALE"
    last_good = ArgusPrimeProjection._futures_confirmation(
        {**value, "source_age_seconds": 21},
        "HOLD",
        allow_last_good=True,
    )
    assert last_good["status"] == "AVAILABLE"
    assert last_good["state"] == "BULLISH"


def test_score_smoothing_is_time_aware_and_material_updates_are_bounded():
    first = ArgusPrimeProjection._smooth_score(
        key="hero",
        raw_score=28,
        source_timestamp="2026-07-29T10:00:00+05:30",
        previous_projection=None,
    )
    prior = {
        "argus_prime": {
            "source_timestamp": "2026-07-29T10:00:00+05:30",
            "smoothed_score": first["smoothed_score"],
            "display_score": first["display_score"],
        }
    }
    second = ArgusPrimeProjection._smooth_score(
        key="hero",
        raw_score=47,
        source_timestamp="2026-07-29T10:00:01+05:30",
        previous_projection=prior,
    )
    assert second["raw_score"] == 47
    assert 28 < second["smoothed_score"] < 47
    assert second["display_score"] < 47


def test_previous_prepared_schema_keeps_new_optional_quote_fields_null():
    engine = object.__new__(OptionChainEngine)
    values = {
        "security_id": 1,
        "ltp": 100.0,
        "previous_close": 95.0,
        "oi": 1_000,
        "previous_oi": 900,
        "volume": 10_000,
        "iv": 12.5,
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
        "top_ask_price": None,
        "top_ask_quantity": None,
        "top_bid_price": None,
        "top_bid_quantity": None,
    }

    leg = engine._build_leg(values, "CE", None)

    assert leg.previous_volume is None
    assert leg.average_price is None
