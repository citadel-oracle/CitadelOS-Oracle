"""E4A-F Test for Rejection of Truncated & Legacy Full Packets."""

import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_legacy_82_byte_full_packet_rejected():
    payload = bytearray(82)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 82) # Claims 82 bytes
    decoded = DhanPacketDecoder.decode_packet(bytes(payload))
    assert decoded is None # Rejection required!


def test_truncated_161_byte_packet_rejected():
    payload = bytearray(161)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 162) # Declares 162 bytes, but only 161 provided
    decoded = DhanPacketDecoder.decode_packet(bytes(payload))
    assert decoded is None # Rejection required!
