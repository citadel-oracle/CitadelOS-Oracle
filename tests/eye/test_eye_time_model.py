"""Tests for Bitemporal Time Model and No-Lookahead Watermarks."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import EvaluationContext, EyeContractError


def test_timezone_aware_validation():
    now_utc = datetime.now(timezone.utc)
    ctx = EvaluationContext(
        market_time=now_utc,
        available_at=now_utc,
        detected_at=now_utc,
        as_of=now_utc,
    )
    assert ctx.market_time.tzinfo is not None

    # Naive datetime input MUST raise EyeContractError
    naive_dt = datetime.now()
    with pytest.raises(EyeContractError, match="must be timezone-aware"):
        EvaluationContext(
            market_time=naive_dt,
            available_at=now_utc,
            detected_at=now_utc,
            as_of=now_utc,
        )


def test_no_lookahead_watermark():
    now_utc = datetime.now(timezone.utc)
    future_time = now_utc + timedelta(minutes=5)

    # available_at cannot exceed evaluation watermark as_of
    with pytest.raises(EyeContractError, match="available_at cannot exceed evaluation watermark as_of"):
        EvaluationContext(
            market_time=now_utc,
            available_at=future_time,
            detected_at=now_utc,
            as_of=now_utc,
        )


def test_timezone_normalization():
    # IST (+05:30) timestamp
    ist = timezone(timedelta(hours=5, minutes=30))
    dt_ist = datetime(2026, 8, 6, 15, 30, 0, tzinfo=ist)

    # Equal UTC timestamp
    dt_utc = datetime(2026, 8, 6, 10, 0, 0, tzinfo=timezone.utc)

    ctx1 = EvaluationContext(market_time=dt_ist, available_at=dt_ist, detected_at=dt_ist, as_of=dt_ist)
    ctx2 = EvaluationContext(market_time=dt_utc, available_at=dt_utc, detected_at=dt_utc, as_of=dt_utc)

    assert ctx1.market_time == ctx2.market_time
    assert ctx1.to_dict()["market_time"] == "2026-08-06T10:00:00+00:00"
