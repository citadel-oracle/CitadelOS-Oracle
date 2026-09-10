from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.data.data_engine import DataEngine
from src.broker.dhan_client import DhanClient
from src.scanner.indicator_builder import IndicatorBuilder
from src.scanner.market_scanner import MarketScanner
from src.timeframe.timeframe_engine import TimeframeEngine


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


class FakeDhan:
    def __init__(self, candles=None):
        self.candles = candles or []
        self.calls = []

    def get_intraday_candles(self, **kwargs):
        self.calls.append(kwargs)
        return {"candles": [dict(candle) for candle in self.candles]}


def at(hour, minute, second=0):
    return datetime(2026, 7, 10, hour, minute, second, tzinfo=IST)


def candle(timestamp, open_price, high, low, close, volume=0):
    return {
        "time": int(timestamp.timestamp()),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_repeated_polls_update_one_current_minute_candle():
    engine = DataEngine(dhan=FakeDhan())

    for second, price in enumerate([100, 102, 99, 101, 103], start=1):
        engine.update_live_price("NIFTY", price, at(9, 17, second))

    candles = engine.get_candles("NIFTY")
    assert len(candles) == 1
    assert candles[0]["time"] == int(at(9, 17).timestamp())
    assert candles[0]["open"] == 100
    assert candles[0]["high"] == 103
    assert candles[0]["low"] == 99
    assert candles[0]["close"] == 103
    assert candles[0]["volume"] is None
    assert candles[0]["authoritative"] is False


def test_new_minute_appends_once_and_same_minute_keeps_updating():
    engine = DataEngine(dhan=FakeDhan())
    engine.update_live_price("NIFTY", 100, at(9, 17, 5))
    engine.update_live_price("NIFTY", 101, at(9, 18, 1))
    engine.update_live_price("NIFTY", 98, at(9, 18, 20))

    candles = engine.get_candles("NIFTY")
    assert len(candles) == 2
    assert [item["time"] for item in candles] == [
        int(at(9, 17).timestamp()),
        int(at(9, 18).timestamp()),
    ]
    assert candles[-1]["open"] == 101
    assert candles[-1]["high"] == 101
    assert candles[-1]["low"] == 98
    assert candles[-1]["close"] == 98


def test_history_is_deduplicated_sorted_and_provider_values_are_preserved():
    history = [
        candle(at(9, 16), 99, 103, 97, 101, 14),
        candle(at(9, 15), 95, 100, 94, 99, 12),
        candle(at(9, 16, 45), 99, 104, 96, 102, 15),
    ]
    fake = FakeDhan(history)
    engine = DataEngine(dhan=fake)

    loaded = engine.load_history("NIFTY", "IDX_I", "13", interval="1")

    assert len(fake.calls) == 1
    assert len(loaded) == 2
    assert [item["time"] for item in loaded] == sorted(
        item["time"] for item in loaded
    )
    assert loaded[0] == candle(at(9, 15), 95, 100, 94, 99, 12)
    assert loaded[1] == candle(at(9, 16), 99, 104, 96, 102, 15)


def test_live_update_does_not_mutate_closed_historical_candle():
    engine = DataEngine(dhan=FakeDhan())
    historical = candle(at(9, 15), 95, 100, 94, 99, 12)
    engine.set_history("NIFTY", [historical])
    closed_snapshot = dict(engine.get_candles("NIFTY")[0])

    engine.update_live_price("NIFTY", 101, at(9, 16, 2))

    assert engine.get_candles("NIFTY")[0] == closed_snapshot
    assert len(engine.get_candles("NIFTY")) == 2


def test_live_update_merges_with_provider_current_bucket_and_preserves_volume():
    engine = DataEngine(dhan=FakeDhan())
    engine.set_history(
        "NIFTY", [candle(at(9, 17), 100, 102, 98, 101, volume=27)]
    )

    engine.update_live_price("NIFTY", 103, at(9, 17, 40))

    current = engine.get_candles("NIFTY")[0]
    assert current["open"] == 100
    assert current["high"] == 103
    assert current["low"] == 98
    assert current["close"] == 103
    assert current["volume"] == 27


def test_stale_quote_is_ignored_and_symbols_are_independent():
    engine = DataEngine(dhan=FakeDhan())
    engine.update_live_price("NIFTY", 100, at(9, 18))
    before = [dict(item) for item in engine.get_candles("NIFTY")]

    result = engine.update_live_price("NIFTY", 50, at(9, 17, 59))
    engine.update_live_price("SENSEX", 80_000, at(9, 18, 10))

    assert result["action"] == "ignored_stale"
    assert engine.get_candles("NIFTY") == before
    assert len(engine.get_candles("SENSEX")) == 1
    assert engine.get_candles("SENSEX")[0]["close"] == 80_000


def test_exchange_buckets_are_derived_in_asia_kolkata():
    utc_time = datetime(2026, 7, 10, 3, 47, 30, tzinfo=timezone.utc)

    bucket = DataEngine.bucket_start(utc_time, interval_minutes=5)

    assert bucket.tzinfo == IST
    assert (bucket.hour, bucket.minute, bucket.second) == (9, 15, 0)


def test_non_one_minute_live_bucket_has_one_candle_per_interval():
    engine = DataEngine(dhan=FakeDhan())
    engine.update_live_price("NIFTY", 100, at(9, 16), interval_minutes=5)
    engine.update_live_price("NIFTY", 104, at(9, 19), interval_minutes=5)
    engine.update_live_price("NIFTY", 103, at(9, 20), interval_minutes=5)

    candles = engine.get_candles("NIFTY")
    assert len(candles) == 2
    assert candles[0]["time"] == int(at(9, 15).timestamp())
    assert candles[0]["open"] == 100
    assert candles[0]["high"] == 104
    assert candles[0]["close"] == 104
    assert candles[1]["time"] == int(at(9, 20).timestamp())


def test_higher_timeframes_use_unique_exchange_time_buckets():
    source = [
        candle(at(9, 15), 100, 102, 99, 101, 10),
        candle(at(9, 16), 101, 103, 100, 102, 11),
        candle(at(9, 17), 102, 103, 100, 101, 12),
        candle(at(9, 18), 101, 102, 99, 100, 13),
        candle(at(9, 19), 100, 104, 98, 99, 14),
        candle(at(9, 20), 99, 101, 97, 100, 13),
    ]

    resampled = TimeframeEngine()._resample(source, 5)

    assert len(resampled) == 1
    assert resampled[0] == candle(at(9, 15), 100, 104, 98, 99, 60)


def test_higher_timeframe_never_publishes_a_forming_bucket():
    source = [
        candle(at(9, 15 + index), 100, 102, 99, 101, 10)
        for index in range(3)
    ]

    assert TimeframeEngine()._resample(source, 3)
    assert TimeframeEngine()._resample(source, 5) == []


class ScannerDhan:
    def __init__(self, rows, *, failures=0):
        self.rows = rows
        self.failures = failures
        self.history_calls = []

    def get_intraday_candles(self, **kwargs):
        self.history_calls.append(kwargs)
        if len(self.history_calls) <= self.failures:
            return {
                "success": False,
                "candles": [],
                "error": "provider timeout",
            }
        return {
            "success": True,
            "candles": [dict(item) for item in self.rows],
        }

    @staticmethod
    def get_multiple_quotes(_watchlist):
        return {
            "NIFTY": {
                "ltp": 205.0,
                "previous_close": 199.0,
                "change_percent": 3.02,
                "updated": "LIVE",
            }
        }


def session_rows(day, start_hour, start_minute, count, base):
    rows = []
    opened = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=IST)
    for index in range(count):
        timestamp = opened + timedelta(minutes=index)
        price = base + index * 0.1
        rows.append(candle(timestamp, price, price + 1, price - 1, price + 0.5, 10))
    return rows


def test_nifty_bootstrap_uses_500_completed_rows_and_today_only_vwap():
    previous = (
        session_rows(datetime(2026, 7, 23), 9, 15, 375, 50)
        + session_rows(datetime(2026, 7, 24), 9, 15, 375, 100)
    )
    today = [
        candle(datetime(2026, 7, 27, 9, 15, tzinfo=IST), 199, 202, 198, 200, 10),
        # Duplicate is resolved deterministically to the last provider row.
        candle(datetime(2026, 7, 27, 9, 15, 30, tzinfo=IST), 200, 203, 199, 201, 10),
        # Still forming at the 09:16:30 observation and must be excluded.
        candle(datetime(2026, 7, 27, 9, 16, tzinfo=IST), 201, 999, 1, 500, 10),
    ]
    provider = ScannerDhan(previous + today)
    now = datetime(2026, 7, 27, 9, 16, 30, tzinfo=IST)
    scanner = MarketScanner(
        dhan=provider,
        clock=lambda: now,
        sleeper=lambda _seconds: None,
    )

    row = scanner.scan()[0]
    completed = scanner.data_engine.completed_candles("NIFTY", now=now)
    indicators = row["context"].indicators

    assert scanner.history_metadata["loaded_candles"] == 500
    assert len(completed) == 500
    assert len({item["time"] for item in completed}) == 500
    assert completed == sorted(completed, key=lambda item: item["time"])
    assert all(
        datetime.fromtimestamp(item["time"], IST) < datetime(2026, 7, 27, 9, 16, tzinfo=IST)
        for item in completed
    )
    assert all(
        indicators[key] is not None
        for key in ("ema_21", "ema_38", "rsi_14", "adx_14", "atr_14", "vwap")
    )
    assert indicators["vwap"] == 201.0
    assert scanner.history_loaded is True
    assert row["technical_readiness"]["vwap_session_date"] == "2026-07-27"
    assert provider.history_calls == [{
        "segment": "IDX_I",
        "security_id": "13",
        "instrument": "INDEX",
        "interval": "1",
        "from_date": "2026-07-23",
        "to_date": "2026-07-27",
    }]

    scanner.scan()
    buckets = [item["time"] for item in scanner.data_engine.get_candles("NIFTY")]
    assert len(buckets) == len(set(buckets))
    assert len(provider.history_calls) == 1


def test_quote_only_bucket_never_becomes_a_completed_indicator_candle():
    engine = DataEngine(dhan=FakeDhan())
    engine.update_live_price("NIFTY", 100, at(9, 17, 5))

    assert engine.completed_candles("NIFTY", now=at(9, 18, 1)) == []

    authoritative = candle(at(9, 17), 99, 102, 98, 101, 25)
    engine.set_history("NIFTY", [authoritative])
    assert engine.completed_candles("NIFTY", now=at(9, 18, 1)) == [
        authoritative
    ]


def test_nifty_history_retries_twice_then_fails_closed():
    provider = ScannerDhan([], failures=3)
    waits = []
    now = datetime(2026, 7, 27, 9, 16, 30, tzinfo=IST)
    scanner = MarketScanner(
        dhan=provider,
        clock=lambda: now,
        sleeper=waits.append,
    )

    row = scanner.scan()[0]

    assert len(provider.history_calls) == 3
    assert waits == [0.25, 0.5]
    assert scanner.history_loaded is False
    assert row["technical_readiness"]["reason"] == "DHAN_HISTORY_UNAVAILABLE"
    assert row["context"].indicators == IndicatorBuilder()._empty([])


def test_warm_minute_reconciliation_uses_one_attempt_then_retries_next_cycle():
    previous = (
        session_rows(datetime(2026, 7, 23), 9, 15, 375, 50)
        + session_rows(datetime(2026, 7, 24), 9, 15, 375, 100)
    )
    today = session_rows(datetime(2026, 7, 27), 9, 15, 2, 200)
    provider = ScannerDhan(previous + today)
    current = [datetime(2026, 7, 27, 9, 16, 30, tzinfo=IST)]
    scanner = MarketScanner(
        dhan=provider,
        clock=lambda: current[0],
        sleeper=lambda _seconds: None,
    )
    scanner.scan()
    assert scanner.history_bootstrapped is True

    current[0] = datetime(2026, 7, 27, 9, 17, 30, tzinfo=IST)
    provider.failures = len(provider.history_calls) + 1
    scanner.scan()

    assert len(provider.history_calls) == 2
    assert scanner.history_reason == "DHAN_HISTORY_UNAVAILABLE"


def test_indicator_requirement_is_period_derived_and_vwap_resets_per_session():
    builder = IndicatorBuilder()
    prior = session_rows(datetime(2026, 7, 24), 14, 52, 38, 100)
    today = [
        candle(datetime(2026, 7, 27, 9, 15, tzinfo=IST), 200, 202, 198, 200, 10)
    ]

    result = builder.build(prior + today, session_date=datetime(2026, 7, 27).date())

    assert builder.required_candle_count == max(
        max(builder.EMA_PERIODS),
        builder.SMA_PERIOD,
        builder.RSI_PERIOD + 1,
        builder.ATR_PERIOD + 1,
        builder.ADX_PERIOD + 2,
        builder.RANGE_PERIOD,
    )
    assert result["ema_38"] is not None
    assert result["vwap"] == 200.0


def test_indicators_use_tradingview_compatible_recursive_formulas():
    start = datetime(2026, 7, 27, 9, 15, tzinfo=IST)
    rows = []
    for index in range(120):
        close = 24_000 + ((index % 17) - 8) * 0.7 + index * 0.03
        rows.append(
            candle(
                start + timedelta(minutes=index),
                close - 0.2,
                close + 1.1 + (index % 3) * 0.1,
                close - 1.0 - (index % 4) * 0.1,
                close,
                1_000 + index * 13,
            )
        )

    result = IndicatorBuilder().build(rows, session_date=start.date())

    assert result["ema_21"] == 24_004.16
    assert result["ema_38"] == 24_003.55
    assert result["rsi_14"] == 37.11
    assert result["atr_14"] == 3.35
    assert result["adx_14"] == 19.38
    assert result["vwap"] == 24_002.12


def test_vwap_is_unavailable_when_authoritative_volume_is_missing():
    start = datetime(2026, 7, 27, 9, 15, tzinfo=IST)
    rows = session_rows(start, 9, 15, 50, 100)
    rows[-1]["volume"] = None

    result = IndicatorBuilder().build(rows, session_date=start.date())

    assert result["ema_21"] is not None
    assert result["vwap"] is None


def test_scanner_reports_volume_unavailable_instead_of_ready():
    previous = (
        session_rows(datetime(2026, 7, 23), 9, 15, 375, 50)
        + session_rows(datetime(2026, 7, 24), 9, 15, 375, 100)
    )
    today = session_rows(datetime(2026, 7, 27), 9, 15, 1, 200)
    for row in previous + today:
        row["volume"] = None
    now = datetime(2026, 7, 27, 9, 16, 30, tzinfo=IST)
    scanner = MarketScanner(
        dhan=ScannerDhan(previous + today),
        clock=lambda: now,
        sleeper=lambda _seconds: None,
    )

    row = scanner.scan()[0]

    assert row["context"].indicators["vwap"] is None
    assert row["technical_readiness"]["status"] == "NOT_READY"
    assert row["technical_readiness"]["reason"] == "VOLUME_UNAVAILABLE"


def test_dhan_history_error_payload_never_reports_success(monkeypatch):
    client = DhanClient(access_token="test", client_id="test")
    monkeypatch.setattr(
        client,
        "_post",
        lambda *_args, **_kwargs: {
            "errorType": "Invalid_Authentication",
            "errorCode": "DH-901",
            "errorMessage": "credentials rejected",
        },
    )

    result = client.get_intraday_candles(
        segment="IDX_I",
        security_id="13",
        instrument="INDEX",
        interval="1",
        from_date="2026-07-27",
        to_date="2026-07-27",
    )

    assert result["success"] is False
    assert result["candles"] == []
    assert result["error"] == "DH-901:credentials rejected"
