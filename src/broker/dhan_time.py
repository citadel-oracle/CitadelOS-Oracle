"""Canonical Dhan exchange-time normalization.

Dhan Full packets can carry an implausible epoch-shaped LTT. Raw evidence is
always retained. For genuine live packets, the trusted receive clock owns
transport/session validity and event ordering whenever raw LTT is implausible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
_RAW_LTT_PLAUSIBILITY_SECONDS = 30


from src.broker.exchange_time import ExchangeLtt, normalize_exchange_ltt

DhanLtt = ExchangeLtt


def normalize_dhan_ltt(raw_epoch: int, receive_wall_utc: str | datetime | None = None) -> DhanLtt:
    """Preserve raw LTT and fail over to receive time without fixed offsets."""
    return normalize_exchange_ltt(
        raw_epoch=raw_epoch,
        receive_wall_utc=receive_wall_utc,
        segment="IDX_I",
        provider="DHAN",
        plausibility_seconds=_RAW_LTT_PLAUSIBILITY_SECONDS,
    )
