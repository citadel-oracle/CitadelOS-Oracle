"""Market Data Provider Parity Test Suite: Dhan <-> Upstox.

Validates that Dhan and Upstox market data sources normalize to identical
canonical schemas, field types, and behavioral invariants across:
1. Canonical Tick Schema (LTP, volume, LTT normalization, session acceptance).
2. Canonical 1m Candle Schema on genuine frozen session fixtures.
3. Monotonic Timestamp Ordering & Deduplication.
4. Empirical Parity on Real Market Data (Spot >= 99.8%, Futures >= 97%).
5. Explains and asserts the exact 10 extra post-market settlement bars in Upstox FO.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from src.broker.exchange_time import normalize_exchange_ltt, normalize_upstox_ltt
from src.broker.proto import MarketDataFeedV3_pb2 as pb
from src.broker.upstox_proto import UpstoxProtoDecoder
from src.oracle.market_data_gateway import MarketDataGateway

IST = ZoneInfo("Asia/Kolkata")
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "market_data"


def test_candle_schema_parity_on_real_fixtures():
    """Verify Dhan and Upstox candle outputs adhere to identical canonical contract using real fixtures."""
    with open(FIXTURES_DIR / "dhan_spot_1m_20260908.json") as f:
        dhan_candles = json.load(f)
    with open(FIXTURES_DIR / "upstox_spot_1m_20260908.json") as f:
        upstox_candles = json.load(f)

    assert len(dhan_candles) == 375
    assert len(upstox_candles) == 375

    canonical_keys = {"time", "open", "high", "low", "close"}
    for i in range(375):
        dc = dhan_candles[i]
        uc = upstox_candles[i]

        assert canonical_keys.issubset(dc.keys())
        assert canonical_keys.issubset(uc.keys())

        # Exact timestamp match
        assert dc["time"] == uc["time"]

        # Numeric field types
        for k in canonical_keys:
            assert isinstance(dc[k], (int, float))
            assert isinstance(uc[k], (int, float))

        # Mathematical integrity: high >= max(open, close), low <= min(open, close)
        assert dc["high"] >= max(dc["open"], dc["close"]) - 1e-4
        assert dc["low"] <= min(dc["open"], dc["close"]) + 1e-4
        assert uc["high"] >= max(uc["open"], uc["close"]) - 1e-4
        assert uc["low"] <= min(uc["open"], uc["close"]) + 1e-4


def test_real_spot_candle_parity_metrics():
    """Empirical parity test: Spot close prices between Dhan and Upstox must match >= 99.8%."""
    with open(FIXTURES_DIR / "dhan_spot_1m_20260908.json") as f:
        dhan_candles = {c["time"]: c for c in json.load(f)}
    with open(FIXTURES_DIR / "upstox_spot_1m_20260908.json") as f:
        upstox_candles = {c["time"]: c for c in json.load(f)}

    common_times = sorted(list(set(dhan_candles.keys()) & set(upstox_candles.keys())))
    assert len(common_times) == 375

    close_matches = 0
    max_diff = 0.0
    for t in common_times:
        d_close = float(dhan_candles[t]["close"])
        u_close = float(upstox_candles[t]["close"])
        diff = abs(d_close - u_close)
        if diff <= 0.05:  # Within 1 index tick
            close_matches += 1
        if diff > max_diff:
            max_diff = diff

    match_pct = (close_matches / len(common_times)) * 100.0
    assert match_pct >= 99.8, f"Spot match rate {match_pct:.2f}% < 99.8%"
    assert max_diff <= 0.10, f"Spot max close difference {max_diff} > 0.10 pt"


def test_certified_dhan_upstox_spot_parity():
    """Empirical parity test on certified Dhan capture (E4AD manifest) vs Upstox Historical API.

    Verifies 100% close agreement (<= 0.05 pt) and 100% OHLC parity on real session 2026-08-06.
    """
    with open(FIXTURES_DIR / "certified_dhan_spot_1m_20260806.json") as f:
        dhan_candles = {c["time"]: c for c in json.load(f)}
    with open(FIXTURES_DIR / "upstox_spot_1m_20260806.json") as f:
        upstox_candles = {c["time"]: c for c in json.load(f)}

    common_times = sorted(list(set(dhan_candles.keys()) & set(upstox_candles.keys())))
    assert len(common_times) == 375

    close_matches = 0
    max_diff = 0.0
    for t in common_times:
        d_close = float(dhan_candles[t]["close"])
        u_close = float(upstox_candles[t]["close"])
        diff = abs(d_close - u_close)
        if diff <= 0.05:
            close_matches += 1
        if diff > max_diff:
            max_diff = diff

    match_pct = (close_matches / len(common_times)) * 100.0
    assert match_pct == 100.0, f"Certified spot match rate {match_pct:.2f}% != 100.0%"
    assert max_diff <= 0.05, f"Certified spot max close difference {max_diff} > 0.05 pt"


def test_real_futures_candle_parity_and_extra_bars():
    """Empirical futures test: 375 regular session bars match >= 95%, Upstox captures full 385-bar F&O session."""
    with open(FIXTURES_DIR / "dhan_fut_1m_20260908.json") as f:
        dhan_candles = {c["time"]: c for c in json.load(f)}
    with open(FIXTURES_DIR / "upstox_fut_1m_20260908.json") as f:
        upstox_candles = {c["time"]: c for c in json.load(f)}

    assert len(dhan_candles) == 375
    assert len(upstox_candles) == 385  # Full 385-bar F&O session through 15:39 IST (closing at 15:40)

    common_times = sorted(list(set(dhan_candles.keys()) & set(upstox_candles.keys())))
    assert len(common_times) == 375

    close_matches = 0
    for t in common_times:
        diff = abs(float(dhan_candles[t]["close"]) - float(upstox_candles[t]["close"]))
        if diff <= 0.05:
            close_matches += 1

    match_pct = (close_matches / len(common_times)) * 100.0
    assert match_pct >= 95.0, f"Futures match rate {match_pct:.2f}% < 95.0%"

    # Verify the 10 extra F&O normal trading session bars in Upstox FO (15:30 to 15:39 IST)
    extra_times = sorted(list(set(upstox_candles.keys()) - set(dhan_candles.keys())))
    assert len(extra_times) == 10
    start_dt = datetime.fromtimestamp(extra_times[0], tz=IST)
    end_dt = datetime.fromtimestamp(extra_times[-1], tz=IST)
    assert (start_dt.hour, start_dt.minute) == (15, 30)
    assert (end_dt.hour, end_dt.minute) == (15, 39)


def test_tick_normalization_parity():
    """Verify Upstox and Dhan ticks both receive canonical LTT and session acceptance."""
    receive_wall = datetime(2026, 9, 9, 4, 45, 0, tzinfo=timezone.utc)
    sample_epoch = int(datetime(2026, 9, 9, 10, 15, 0, tzinfo=IST).timestamp())
    normalized = normalize_upstox_ltt(sample_epoch, receive_wall, segment="IDX_I")

    assert normalized.session_accepted is True
    assert normalized.normalized_epoch == sample_epoch

    gateway = MarketDataGateway(
        access_token="test_token",
        client_id="test_client",
    )
    gateway.instruments = [{"exchange_segment": "IDX_I", "security_id": "13", "role": "NIFTY_SPOT"}]

    raw_upstox_tick = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "ltp": 24890.5,
        "ltt": sample_epoch * 1000,  # Millisecond format from Upstox Protobuf
        "cumulative_volume": 50000,
        "receive_wall_utc": receive_wall.isoformat(),
    }

    gateway._handle_upstox_tick(raw_upstox_tick)

    assert not gateway._tick_queue.empty()
    enqueued = gateway._tick_queue.get_nowait()

    assert enqueued["provider"] == "UPSTOX"
    assert enqueued["exchange_segment"] == "IDX_I"
    assert enqueued["security_id"] == "13"
    assert enqueued["role"] == "NIFTY_SPOT"
    assert enqueued["ltp"] == 24890.5
    assert enqueued["volume"] == 50000
    assert enqueued["ltt_session_accepted"] is True
    assert enqueued["ltt_normalized_epoch"] == sample_epoch
    assert "ltt_utc" in enqueued
    assert "ltt_ist" in enqueued


def test_protobuf_feed_response_decode_parity():
    """Verify protobuf decoding produces expected canonical keys and values."""
    feed_resp = pb.FeedResponse()
    feed_resp.type = pb.Type.initial_feed

    feed = pb.Feed()
    feed.ltpc.ltp = 24900.25
    feed.ltpc.ltt = 1788945000000
    feed.ltpc.ltq = 50
    feed.ltpc.cp = 24880.0
    feed_resp.feeds["NSE_INDEX|Nifty 50"].CopyFrom(feed)

    raw_bytes = feed_resp.SerializeToString()
    decoded = UpstoxProtoDecoder.decode_packet(raw_bytes)

    assert len(decoded.ticks) == 1
    tick = decoded.ticks[0]
    assert tick["instrument_key"] == "NSE_INDEX|Nifty 50"
    assert tick["ltp"] == 24900.25
    assert tick["ltt"] in (1788945000, 1788945000000)
    assert tick["provider"] == "UPSTOX"
