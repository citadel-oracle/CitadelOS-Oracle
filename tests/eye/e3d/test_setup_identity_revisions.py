"""E3-D Setup Identity & Revision Model Test Suite."""

import pytest
from src.eye.composer.deduplication import generate_setup_key


def test_generate_setup_key_is_content_addressable_and_deterministic():
    key1 = generate_setup_key("SETUP_1", "NSE:NIFTY:5m", "BEARISH", ["KEY_A", "KEY_B"])
    key2 = generate_setup_key("SETUP_1", "NSE:NIFTY:5m", "BEARISH", ["KEY_A", "KEY_B"])
    key3 = generate_setup_key("SETUP_1", "NSE:NIFTY:5m", "BEARISH", ["KEY_A", "KEY_C"])

    assert key1 == key2
    assert key1 != key3
    assert key1.startswith("SETUP:SETUP_1:")
