"""Official DhanHQ v2 162-byte Full-packet decoder.

This is the shared non-EYE broker seam.  Frozen EYE code is intentionally not
imported or modified.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Any


FULL_RESPONSE_CODE = 8
FULL_PACKET_LENGTH = 162
DISCONNECT_RESPONSE_CODE = 50
DISCONNECT_PACKET_LENGTH = 12


class DhanPacketError(ValueError):
    """Packet is malformed, truncated, or unsupported."""


@dataclass(frozen=True, slots=True)
class DecodedPacket:
    response_code: int
    message_length: int
    exchange_segment: int
    security_id: str
    values: dict[str, Any]
    packet_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_code": self.response_code,
            "message_length": self.message_length,
            "exchange_segment": self.exchange_segment,
            "security_id": self.security_id,
            "packet_fingerprint": self.packet_fingerprint,
            **self.values,
        }


class DhanFullPacketDecoder:
    """Decode little-endian Dhan v2 packets without side effects."""

    @classmethod
    def decode_packet(cls, packet: bytes) -> DecodedPacket:
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            raise DhanPacketError("DHAN_PACKET_TYPE_INVALID")
        raw = bytes(packet)
        if len(raw) < 8:
            raise DhanPacketError("DHAN_PACKET_TRUNCATED_HEADER")
        response_code, declared_length, segment, security_id = struct.unpack_from(
            "<BHBi", raw, 0
        )
        if declared_length < 8:
            raise DhanPacketError("DHAN_PACKET_LENGTH_INVALID")
        if len(raw) != declared_length:
            raise DhanPacketError("DHAN_PACKET_LENGTH_MISMATCH")
        fingerprint = hashlib.sha256(raw).hexdigest()
        if response_code == FULL_RESPONSE_CODE:
            if declared_length != FULL_PACKET_LENGTH:
                raise DhanPacketError("DHAN_FULL_PACKET_LENGTH_INVALID")
            values = cls._decode_full(raw)
        elif response_code == 2:
            if declared_length != 16:
                raise DhanPacketError("DHAN_TICKER_PACKET_LENGTH_INVALID")
            values = {
                "ltp": float(struct.unpack_from("<f", raw, 8)[0]),
                "ltt": struct.unpack_from("<I", raw, 12)[0],
            }
        elif response_code == 4:
            if declared_length != 50:
                raise DhanPacketError("DHAN_QUOTE_PACKET_LENGTH_INVALID")
            values = {
                "ltp": float(struct.unpack_from("<f", raw, 8)[0]),
                "ltq": struct.unpack_from("<H", raw, 12)[0],
                "ltt": struct.unpack_from("<I", raw, 14)[0],
                "atp": float(struct.unpack_from("<f", raw, 18)[0]),
                "cumulative_volume": struct.unpack_from("<I", raw, 22)[0],
                "total_sell_quantity": struct.unpack_from("<I", raw, 26)[0],
                "total_buy_quantity": struct.unpack_from("<I", raw, 30)[0],
                "open": float(struct.unpack_from("<f", raw, 34)[0]),
                "close": float(struct.unpack_from("<f", raw, 38)[0]),
                "high": float(struct.unpack_from("<f", raw, 42)[0]),
                "low": float(struct.unpack_from("<f", raw, 46)[0]),
            }
        elif response_code == 5:
            if declared_length != 12:
                raise DhanPacketError("DHAN_OI_PACKET_LENGTH_INVALID")
            values = {"open_interest": struct.unpack_from("<I", raw, 8)[0]}
        elif response_code == 6:
            if declared_length != 16:
                raise DhanPacketError("DHAN_PREVIOUS_CLOSE_PACKET_LENGTH_INVALID")
            values = {
                "previous_close": float(struct.unpack_from("<f", raw, 8)[0]),
                "previous_open_interest": struct.unpack_from("<I", raw, 12)[0],
            }
        elif response_code == 1:
            if declared_length < 12:
                raise DhanPacketError("DHAN_INDEX_PACKET_LENGTH_INVALID")
            values = {"ltp": float(struct.unpack_from("<f", raw, 8)[0])}
        elif response_code == DISCONNECT_RESPONSE_CODE:
            if declared_length != DISCONNECT_PACKET_LENGTH:
                raise DhanPacketError("DHAN_DISCONNECT_PACKET_LENGTH_INVALID")
            values = {"disconnect_reason_code": struct.unpack_from("<I", raw, 8)[0]}
        else:
            values = {"control_or_response_code": response_code}
        return DecodedPacket(
            response_code=response_code,
            message_length=declared_length,
            exchange_segment=segment,
            security_id=str(security_id),
            values=values,
            packet_fingerprint=fingerprint,
        )

    @classmethod
    def decode_stream(cls, buffer: bytes) -> tuple[list[DecodedPacket], bytes]:
        remaining = bytes(buffer)
        decoded: list[DecodedPacket] = []
        while len(remaining) >= 8:
            declared = struct.unpack_from("<H", remaining, 1)[0]
            if declared < 8:
                raise DhanPacketError("DHAN_PACKET_LENGTH_INVALID")
            if len(remaining) < declared:
                break
            decoded.append(cls.decode_packet(remaining[:declared]))
            remaining = remaining[declared:]
        return decoded, remaining

    @staticmethod
    def _decode_full(raw: bytes) -> dict[str, Any]:
        # Official one-based byte table translated to zero-based offsets.
        ltp = struct.unpack_from("<f", raw, 8)[0]
        ltq = struct.unpack_from("<H", raw, 12)[0]
        ltt = struct.unpack_from("<I", raw, 14)[0]
        atp = struct.unpack_from("<f", raw, 18)[0]
        volume = struct.unpack_from("<I", raw, 22)[0]
        total_sell = struct.unpack_from("<I", raw, 26)[0]
        total_buy = struct.unpack_from("<I", raw, 30)[0]
        oi = struct.unpack_from("<I", raw, 34)[0]
        high_oi = struct.unpack_from("<I", raw, 38)[0]
        low_oi = struct.unpack_from("<I", raw, 42)[0]
        open_price = struct.unpack_from("<f", raw, 46)[0]
        close_price = struct.unpack_from("<f", raw, 50)[0]
        high_price = struct.unpack_from("<f", raw, 54)[0]
        low_price = struct.unpack_from("<f", raw, 58)[0]
        prices = (ltp, atp, open_price, close_price, high_price, low_price)
        if not all(math.isfinite(value) for value in prices):
            raise DhanPacketError("DHAN_FULL_PACKET_NON_FINITE_PRICE")
        depth: list[dict[str, Any]] = []
        offset = 62
        for index in range(5):
            bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = struct.unpack_from(
                "<IIHHff", raw, offset
            )
            if not math.isfinite(bid_price) or not math.isfinite(ask_price):
                raise DhanPacketError("DHAN_FULL_PACKET_NON_FINITE_DEPTH")
            depth.append(
                {
                    "level": index + 1,
                    "bid_quantity": bid_qty,
                    "ask_quantity": ask_qty,
                    "bid_orders": bid_orders,
                    "ask_orders": ask_orders,
                    "bid_price": float(bid_price),
                    "ask_price": float(ask_price),
                }
            )
            offset += 20
        return {
            "ltp": float(ltp),
            "ltq": ltq,
            "ltt": ltt,
            "atp": float(atp),
            "cumulative_volume": volume,
            "total_sell_quantity": total_sell,
            "total_buy_quantity": total_buy,
            "open_interest": oi,
            "high_open_interest": high_oi,
            "low_open_interest": low_oi,
            "open": float(open_price),
            "close": float(close_price),
            "high": float(high_price),
            "low": float(low_price),
            "depth_5": depth,
        }
