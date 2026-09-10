"""Unit tests for Provider-Neutral Exchange LTT Normalization."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest

from src.broker.exchange_time import normalize_exchange_ltt, normalize_upstox_ltt

IST = ZoneInfo("Asia/Kolkata")


def test_upstox_millisecond_ltt_normalization():
    """Verify Upstox millisecond timestamps (> 1e11) are cleanly converted to epoch seconds."""
    # 2026-09-09 10:30:00 IST = 1788930000 sec = 1788930000000 ms
    epoch_ms = 1788930000000
    receive_wall = datetime(2026, 9, 9, 5, 0, 0, tzinfo=timezone.utc)

    norm = normalize_upstox_ltt(epoch_ms, receive_wall, segment="IDX_I")
    assert norm.normalized_epoch == 1788930000
    assert norm.raw_epoch == 1788930000
    assert norm.session_accepted is True
    assert norm.event_session_accepted is True


def test_spot_session_boundary_rejection_at_1531():
    """Spot index trades 09:15 to 15:30 IST. A spot tick at 15:31 must be marked session_accepted=False."""
    # 2026-09-09 15:31:00 IST
    t_1531 = int(datetime(2026, 9, 9, 15, 31, 0, tzinfo=IST).timestamp())
    receive_wall = datetime.fromtimestamp(t_1531, tz=timezone.utc)

    norm_spot = normalize_exchange_ltt(t_1531, receive_wall, segment="IDX_I", provider="UPSTOX")
    assert norm_spot.session_accepted is False
    assert norm_spot.event_session_accepted is False


def test_futures_session_acceptance_through_1540():
    """NSE Equity Derivatives normal trading session runs 09:15 to 15:40 IST.

    A futures tick at 15:35 is a normal trading session tick and must be marked session_accepted=True.
    """
    # 2026-09-09 15:35:00 IST
    t_1535 = int(datetime(2026, 9, 9, 15, 35, 0, tzinfo=IST).timestamp())
    receive_wall = datetime.fromtimestamp(t_1535, tz=timezone.utc)

    norm_fut = normalize_upstox_ltt(t_1535, receive_wall, segment="NSE_FNO")
    assert norm_fut.session_accepted is True
    assert norm_fut.event_session_accepted is True

    # But at 15:41 IST, futures is closed
    t_1541 = int(datetime(2026, 9, 9, 15, 41, 0, tzinfo=IST).timestamp())
    receive_wall_41 = datetime.fromtimestamp(t_1541, tz=timezone.utc)
    norm_fut_closed = normalize_upstox_ltt(t_1541, receive_wall_41, segment="NSE_FNO")
    assert norm_fut_closed.session_accepted is False


def test_dhan_compatibility_wrapper():
    """Verify dhan_time.normalize_dhan_ltt works identically with full backwards compatibility."""
    from src.broker.dhan_time import normalize_dhan_ltt

    # 10:15 IST
    sample_epoch = int(datetime(2026, 9, 9, 10, 15, 0, tzinfo=IST).timestamp())
    receive_wall = datetime(2026, 9, 9, 4, 45, 0, tzinfo=timezone.utc)

    res = normalize_dhan_ltt(sample_epoch, receive_wall)
    assert res.normalized_epoch == sample_epoch
    assert res.session_accepted is True
    assert hasattr(res, "raw_receive_skew_ms")
    assert hasattr(res, "receive_skew_ms")
