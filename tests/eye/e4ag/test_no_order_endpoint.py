"""E4A-G Test for Zero Order Endpoint Invocations."""

import pytest
from pathlib import Path


def test_no_order_endpoints_in_capture_module():
    capture_dir = Path(__file__).parent.parent.parent / "src" / "eye" / "option_capture"
    for f in capture_dir.rglob("*.py"):
        text = f.read_text()
        assert "place_order" not in text
        assert "modify_order" not in text
        assert "cancel_order" not in text
        assert "convert_position" not in text
