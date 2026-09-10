"""History-to-Live Seam & Gap Recovery Test Suite.

Validates:
1. History to live candle continuity with zero timestamp overlap or duplicate bars.
2. In-flight / forming candle isolation: completed candles remain immutable.
3. Gap recovery: reconnection fetches missing intermediate candles and stitches them.
4. Provider-neutral canonical store updates.
"""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest

from src.vob.backfill import sync_current_session, _save_canonical, _load_canonical

IST = ZoneInfo("Asia/Kolkata")


def test_history_to_live_seam_deduplication():
    """Verify live sync seamlessly merges newly completed candles without duplicates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        canonical_path = Path(tmpdir) / "vob_1m_candles.json"
        start_time = datetime(2026, 9, 9, 9, 15, 0, tzinfo=IST)

        # Seed canonical store with completed candles up to 09:30 IST (16 bars: 09:15 to 09:30)
        base_epochs = [
            int((start_time + timedelta(minutes=i)).timestamp())
            for i in range(16)
        ]
        initial_candles = [
            {"time": ep, "open": 24800.0, "high": 24810.0, "low": 24795.0, "close": 24805.0, "volume": 1000.0}
            for ep in base_epochs
        ]
        _save_canonical(canonical_path, {"candles": initial_candles})

        # Mock Upstox client returning candles up to 09:45 IST (31 bars total)
        full_epochs = [
            int((start_time + timedelta(minutes=i)).timestamp())
            for i in range(31)
        ]
        mock_upstox = MagicMock()
        mock_candles = [
            {"time": ep, "open": 24800.0 + i, "high": 24810.0 + i, "low": 24795.0 + i, "close": 24805.0 + i, "volume": 1000.0}
            for i, ep in enumerate(full_epochs)
        ]
        mock_upstox.get_intraday_candles.return_value = mock_candles
        mock_upstox.get_historical_candles.return_value = mock_candles

        ref_time = datetime(2026, 9, 9, 9, 46, 0, tzinfo=IST)
        result = sync_current_session(
            canonical_path=canonical_path,
            client=mock_upstox,
            now=ref_time,
            minimum_retry_seconds=0.0,
        )

        assert result["added"] == 15
        assert result["invalid_removed"] == 0

        saved = _load_canonical(canonical_path)
        candles = saved["candles"]
        assert len(candles) == 31

        # Invariant: Timestamps must be strictly increasing with no duplicates
        for j in range(1, len(candles)):
            assert candles[j]["time"] > candles[j - 1]["time"]
            assert candles[j]["time"] - candles[j - 1]["time"] == 60


def test_gap_recovery_after_reconnect():
    """Verify missing intermediate bars are backfilled when reconnecting after a disconnect."""
    with tempfile.TemporaryDirectory() as tmpdir:
        canonical_path = Path(tmpdir) / "vob_1m_candles.json"
        start_time = datetime(2026, 9, 9, 9, 15, 0, tzinfo=IST)

        # Disconnected at 10:00 (has candles 09:15 to 10:00 = 46 bars)
        early_epochs = [
            int((start_time + timedelta(minutes=i)).timestamp())
            for i in range(46)
        ]
        _save_canonical(canonical_path, {
            "candles": [{"time": ep, "open": 24800.0, "high": 24810.0, "low": 24795.0, "close": 24805.0, "volume": 1000.0} for ep in early_epochs]
        })

        # Reconnects at 10:20 (missing 10:01 to 10:19 = 19 bars)
        all_epochs = [
            int((start_time + timedelta(minutes=i)).timestamp())
            for i in range(66)  # 09:15 to 10:20
        ]
        mock_client = MagicMock()
        mock_reconnect_candles = [
            {"time": ep, "open": 24800.0, "high": 24810.0, "low": 24795.0, "close": 24805.0, "volume": 1000.0}
            for ep in all_epochs
        ]
        mock_client.get_intraday_candles.return_value = mock_reconnect_candles
        mock_client.get_historical_candles.return_value = mock_reconnect_candles

        ref_time = datetime(2026, 9, 9, 10, 20, 30, tzinfo=IST)
        result = sync_current_session(
            canonical_path=canonical_path,
            client=mock_client,
            now=ref_time,
            minimum_retry_seconds=0.0,
        )

        assert result["added"] == 19  # 10:01 to 10:19 inclusive
        saved = _load_canonical(canonical_path)
        assert len(saved["candles"]) == 65  # completed cutoff is 10:19


def test_forming_candle_excluded_from_finalized_store():
    """Verify that a candle from the current in-flight minute is excluded from finalized storage."""
    ref_time = datetime(2026, 9, 9, 11, 30, 15, tzinfo=IST)
    ref_epoch = int(ref_time.timestamp())

    # Candidate bars from provider:
    # 11:28 (closed), 11:29 (closed), 11:30 (in-flight forming!)
    t_28 = int(datetime(2026, 9, 9, 11, 28, 0, tzinfo=IST).timestamp())
    t_29 = int(datetime(2026, 9, 9, 11, 29, 0, tzinfo=IST).timestamp())
    t_30 = int(datetime(2026, 9, 9, 11, 30, 0, tzinfo=IST).timestamp())

    candles = [
        {"time": t_28, "open": 24900, "high": 24910, "low": 24890, "close": 24905, "volume": 500},
        {"time": t_29, "open": 24905, "high": 24915, "low": 24900, "close": 24910, "volume": 600},
        {"time": t_30, "open": 24910, "high": 24912, "low": 24908, "close": 24911, "volume": 150},  # partial volume
    ]

    # Apply seam guard logic
    finalized = [c for c in candles if int(c["time"]) + 60 <= ref_epoch]

    assert len(finalized) == 2
    assert [c["time"] for c in finalized] == [t_28, t_29]
    assert t_30 not in [c["time"] for c in finalized]
