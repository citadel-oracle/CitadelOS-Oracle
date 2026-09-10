"""E4A-F Test for 5-Level Market Depth Decoding."""

import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_five_level_depth_decode():
    payload = bytearray(162)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 162)
    struct.pack_into("<i", payload, 4, 43210)

    # Populate 5 depth levels
    offset = 62
    for lvl in range(1, 6):
        struct.pack_into("<I", payload, offset, lvl * 100)      # Bid Qty
        struct.pack_into("<I", payload, offset + 4, lvl * 80)   # Ask Qty
        struct.pack_into("<H", payload, offset + 8, lvl * 2)    # Bid Orders
        struct.pack_into("<H", payload, offset + 10, lvl)      # Ask Orders
        struct.pack_into("<f", payload, offset + 12, 100.0 - lvl) # Bid Price
        struct.pack_into("<f", payload, offset + 16, 100.0 + lvl) # Ask Price
        offset += 20

    decoded = DhanPacketDecoder.decode_packet(bytes(payload))
    assert decoded is not None
    assert "depth" in decoded
    assert len(decoded["depth"]) == 5

    lvl3 = decoded["depth"][2]
    assert lvl3["level"] == 3
    assert lvl3["bid_quantity"] == 300
    assert lvl3["ask_quantity"] == 240
    assert lvl3["bid_orders"] == 6
    assert lvl3["ask_orders"] == 3
    assert lvl3["bid_price"] == 97.0
    assert lvl3["ask_price"] == 103.0
