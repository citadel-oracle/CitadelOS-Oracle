"""E4A-F Test for Valid 162-Byte Full Market Depth Packet Decoding."""

import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_dhan_162_byte_full_packet():
    payload = bytearray(162)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 162)
    payload[3] = 1
    struct.pack_into("<i", payload, 4, 43210)
    struct.pack_into("<f", payload, 8, 24500.50) # LTP
    struct.pack_into("<I", payload, 12, 75)       # LTQ
    struct.pack_into("<I", payload, 16, 1723010400)# LTT
    struct.pack_into("<f", payload, 20, 24490.20) # ATP
    struct.pack_into("<I", payload, 24, 100000)   # Vol
    struct.pack_into("<I", payload, 28, 40000)    # Total Sell Qty
    struct.pack_into("<I", payload, 32, 50000)    # Total Buy Qty
    struct.pack_into("<I", payload, 36, 500000)   # OI
    struct.pack_into("<I", payload, 40, 520000)   # High OI
    struct.pack_into("<I", payload, 44, 480000)   # Low OI
    struct.pack_into("<f", payload, 48, 24400.0)  # Open
    struct.pack_into("<f", payload, 52, 24450.0)  # Close
    struct.pack_into("<f", payload, 56, 24550.0)  # High
    struct.pack_into("<f", payload, 60, 24380.0)  # Low

    # Depth level 1
    struct.pack_into("<I", payload, 62, 1500)
    struct.pack_into("<I", payload, 66, 1200)
    struct.pack_into("<H", payload, 70, 10)
    struct.pack_into("<H", payload, 72, 8)
    struct.pack_into("<f", payload, 74, 24500.0)
    struct.pack_into("<f", payload, 78, 24501.0)

    decoded = DhanPacketDecoder.decode_packet(bytes(payload))
    assert decoded is not None
    assert decoded["response_code"] == 8
    assert decoded["message_length"] == 162
    assert decoded["security_id"] == "43210"
    assert decoded["open_interest"] == 500000
    assert decoded["best_bid"] == 24500.0
    assert decoded["best_ask"] == 24501.0
