from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone

from src.order_flow.contracts import (
    DataQuality,
    DepthLevel,
    InstrumentIdentity,
    MarketEvent,
)


def full_packet(
    *,
    security_id: int = 43210,
    ltp: float = 100.0,
    ltq: int = 10,
    ltt: int = 1786083900,
    volume: int = 1000,
    bid: float = 99.95,
    ask: float = 100.0,
    bid_qty: int = 500,
    ask_qty: int = 400,
    oi: int = 50_000,
) -> bytes:
    packet = bytearray(162)
    struct.pack_into("<BHBi", packet, 0, 8, 162, 2, security_id)
    struct.pack_into("<f", packet, 8, ltp)
    struct.pack_into("<H", packet, 12, ltq)
    struct.pack_into("<I", packet, 14, ltt)
    struct.pack_into("<f", packet, 18, ltp - 0.25)
    struct.pack_into("<I", packet, 22, volume)
    struct.pack_into("<I", packet, 26, 40_000)
    struct.pack_into("<I", packet, 30, 50_000)
    struct.pack_into("<I", packet, 34, oi)
    struct.pack_into("<I", packet, 38, oi + 1_000)
    struct.pack_into("<I", packet, 42, oi - 1_000)
    struct.pack_into("<f", packet, 46, ltp - 2.0)
    struct.pack_into("<f", packet, 50, ltp - 1.0)
    struct.pack_into("<f", packet, 54, ltp + 2.0)
    struct.pack_into("<f", packet, 58, ltp - 3.0)
    for index in range(5):
        offset = 62 + index * 20
        struct.pack_into(
            "<IIHHff",
            packet,
            offset,
            bid_qty - index * 10,
            ask_qty - index * 10,
            10 + index,
            8 + index,
            bid - index * 0.05,
            ask + index * 0.05,
        )
    return bytes(packet)


def identity(
    security_id: str = "43210",
    role: str = "NIFTY_FUTURE",
    option_type: str | None = None,
    strike: float | None = None,
) -> InstrumentIdentity:
    return InstrumentIdentity("NSE_FNO", security_id, role, "2026-08-27", strike, option_type)


def event(
    *,
    event_id: str = "event-1",
    security_id: str = "43210",
    role: str = "NIFTY_FUTURE",
    option_type: str | None = None,
    ltp: float = 100.0,
    ltq: int = 10,
    ltt: int = 1786083900,
    volume: int = 1000,
    bid: float = 99.95,
    ask: float = 100.0,
    bid_qty: int = 500,
    ask_qty: int = 400,
    generation: int = 1,
    receive_ns: int = 1_000_000_000,
    quality: DataQuality = DataQuality.GOOD,
) -> MarketEvent:
    levels = tuple(
        DepthLevel(
            index + 1,
            bid - index * 0.05,
            bid_qty - index * 10,
            10 + index,
            ask + index * 0.05,
            ask_qty - index * 10,
            8 + index,
        )
        for index in range(5)
    )
    return MarketEvent(
        1,
        "2026-08-07",
        generation,
        event_id,
        "NSE_FNO",
        security_id,
        role,
        "2026-08-27",
        24500.0 if option_type else None,
        option_type,
        ltt,
        datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc).isoformat(),
        receive_ns,
        receive_ns + 10_000,
        ltp,
        ltq,
        volume,
        ltp - 0.25,
        50_000,
        51_000,
        49_000,
        50_000,
        40_000,
        levels,
        quality,
        hashlib.sha256(event_id.encode()).hexdigest(),
    )
