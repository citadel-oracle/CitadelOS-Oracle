"""E4A-D Test for Zero Order Endpoint Calls."""

import pytest
from pathlib import Path


def test_no_order_endpoint_invocations():
    src_dir = Path(__file__).parent.parent.parent / "src" / "eye"
    for f in src_dir.rglob("*.py"):
        text = f.read_text()
        assert "place_order" not in text
        assert "modify_order" not in text
        assert "cancel_order" not in text
