"""E4A-F Test for Official 162-Byte Full Market Depth WebSocket Packet Decoding."""

import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_dhan_162_byte_full_packet_decoder():
    # Build 162-byte binary payload (Response code 8)
    payload = bytearray(162)
    payload[0] = 8                             # Code 8
    struct.pack_into("<H", payload, 1, 162)    # Length
    payload[3] = 1                             # NSE
    struct.pack_into("<i", payload, 4, 43210)  # Security ID
    struct.pack_into("<f", payload, 8, 150.25) # LTP
    struct.pack_into("<I", payload, 12, 100)   # LTQ
    struct.pack_into("<I", payload, 16, 1723010400) # LTT
    struct.pack_into("<f", payload, 20, 149.80) # ATP
    struct.pack_into("<I", payload, 24, 5000)  # Volume
    struct.pack_into("<I", payload, 28, 2000)  # Sell Qty
    struct.pack_into("<I", payload, 32, 2500)  # Buy Qty
    struct.pack_into("<I", payload, 36, 150000)# OI
    struct.pack_into("<I", payload, 40, 160000)# High OI
    struct.pack_into("<I", payload, 44, 140000)# Low OI
    struct.pack_into("<f", payload, 48, 145.00)# Open
    struct.pack_into("<f", payload, 52, 148.00)# Close
    struct.pack_into("<f", payload, 56, 152.00)# High
    struct.pack_into("<f", payload, 60, 144.00)# Low

    # Level 1 Depth (bytes 62..81)
    struct.pack_into("<I", payload, 62, 500)    # Bid Qty L1
    struct.pack_into("<I", payload, 66, 400)    # Ask Qty L1
    struct.pack_into("<H", payload, 70, 5)      # Bid Orders L1
    struct.pack_into("<H", payload, 72, 4)      # Ask Orders L1
    struct.pack_into("<f", payload, 74, 150.00) # Best Bid L1
    struct.pack_into("<f", payload, 78, 150.50) # Best Ask L1

    decoded = DhanPacketDecoder.decode_packet(bytes(payload))
    assert decoded is not None
    assert decoded["response_code"] == 8
    assert decoded["message_length"] == 162
    assert decoded["security_id"] == "43210"
    assert round(decoded["last_price"], 2) == 150.25
    assert round(decoded["best_bid"], 2) == 150.00
    assert round(decoded["best_ask"], 2) == 150.50
    assert len(decoded["depth"]) == 5
    assert decoded["depth"][0]["bid_orders"] == 5
