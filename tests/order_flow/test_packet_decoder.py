import struct

import pytest

from src.broker.dhan_full_packet import (
    DhanFullPacketDecoder,
    DhanPacketError,
)

from .helpers import full_packet


def test_official_162_byte_golden_packet_all_fields():
    decoded = DhanFullPacketDecoder.decode_packet(full_packet()).to_dict()
    assert decoded["response_code"] == 8
    assert decoded["message_length"] == 162
    assert decoded["exchange_segment"] == 2
    assert decoded["security_id"] == "43210"
    assert decoded["ltp"] == 100.0
    assert decoded["ltq"] == 10
    assert decoded["ltt"] == 1786083900
    assert decoded["atp"] == 99.75
    assert decoded["cumulative_volume"] == 1000
    assert decoded["total_sell_quantity"] == 40000
    assert decoded["total_buy_quantity"] == 50000
    assert decoded["open_interest"] == 50000
    assert decoded["high_open_interest"] == 51000
    assert decoded["low_open_interest"] == 49000
    assert decoded["open"] == 98.0
    assert decoded["close"] == 99.0
    assert decoded["high"] == 102.0
    assert decoded["low"] == 97.0
    assert len(decoded["depth_5"]) == 5
    assert decoded["depth_5"][0] == {
        "level": 1, "bid_quantity": 500, "ask_quantity": 400,
        "bid_orders": 10, "ask_orders": 8, "bid_price": pytest.approx(99.95),
        "ask_price": 100.0,
    }
    assert len(decoded["packet_fingerprint"]) == 64


def test_unsigned_ltq_and_order_counts():
    packet = bytearray(full_packet())
    struct.pack_into("<H", packet, 12, 65535)
    struct.pack_into("<H", packet, 70, 65535)
    decoded = DhanFullPacketDecoder.decode_packet(bytes(packet)).to_dict()
    assert decoded["ltq"] == 65535
    assert decoded["depth_5"][0]["bid_orders"] == 65535


@pytest.mark.parametrize("length", [0, 1, 7, 80, 161])
def test_truncated_packet_rejected(length):
    with pytest.raises(DhanPacketError):
        DhanFullPacketDecoder.decode_packet(full_packet()[:length])


def test_declared_length_mismatch_rejected():
    packet = bytearray(full_packet())
    struct.pack_into("<H", packet, 1, 161)
    with pytest.raises(DhanPacketError, match="LENGTH_MISMATCH"):
        DhanFullPacketDecoder.decode_packet(bytes(packet))


def test_concatenated_packets_and_partial_tail():
    first = full_packet(security_id=1)
    second = full_packet(security_id=2)
    rows, remaining = DhanFullPacketDecoder.decode_stream(first + second + b"abc")
    assert [row.security_id for row in rows] == ["1", "2"]
    assert remaining == b"abc"


def test_disconnect_packet():
    packet = bytearray(12)
    struct.pack_into("<BHBiI", packet, 0, 50, 12, 2, 43210, 805)
    decoded = DhanFullPacketDecoder.decode_packet(bytes(packet)).to_dict()
    assert decoded["response_code"] == 50
    assert decoded["disconnect_reason_code"] == 805


def test_ticker_legacy_compatibility():
    packet = bytearray(16)
    struct.pack_into("<BHBi", packet, 0, 2, 16, 2, 13)
    struct.pack_into("<fI", packet, 8, 24500.5, 1786083900)
    decoded = DhanFullPacketDecoder.decode_packet(bytes(packet)).to_dict()
    assert decoded["ltp"] == 24500.5
    assert decoded["ltt"] == 1786083900
