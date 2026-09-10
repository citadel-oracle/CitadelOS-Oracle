"""E4A-F Test for Option Capture Performance & Throughput."""

import time
import struct
import pytest
from src.eye.option_capture.packet_decoder import DhanPacketDecoder


def test_packet_decoder_throughput():
    payload = bytearray(162)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 162)

    t0 = time.perf_counter_ns()
    for _ in range(1000):
        DhanPacketDecoder.decode_packet(bytes(payload))
    t1 = time.perf_counter_ns()

    elapsed_ms = (t1 - t0) / 1e6
    assert elapsed_ms < 500.0  # Must parse 1000 162-byte packets in < 500ms
