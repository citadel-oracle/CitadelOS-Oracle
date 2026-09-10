"""E4A-F Test for Message Length Validation & Stream Parsing."""

import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_declared_message_length_mismatch():
    payload = bytearray(162)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 100) # Declares 100 bytes for Code 8 (expected 162)
    assert DhanPacketDecoder.decode_packet(bytes(payload)) is None


def test_sequential_stream_decoding():
    # Construct buffer with Code 2 (16B) followed by Code 8 (162B)
    p1 = bytearray(16)
    p1[0] = 2
    struct.pack_into("<H", p1, 1, 16)
    struct.pack_into("<i", p1, 4, 1001)
    struct.pack_into("<f", p1, 8, 24500.0)

    p2 = bytearray(162)
    p2[0] = 8
    struct.pack_into("<H", p2, 1, 162)
    struct.pack_into("<i", p2, 4, 1002)
    struct.pack_into("<f", p2, 8, 150.0)
    struct.pack_into("<f", p2, 74, 149.5)
    struct.pack_into("<f", p2, 78, 150.5)

    buffer = bytes(p1) + bytes(p2)
    packets, remaining = DhanPacketDecoder.decode_stream(buffer)

    assert len(packets) == 2
    assert packets[0]["security_id"] == "1001"
    assert packets[1]["security_id"] == "1002"
    assert len(remaining) == 0
