"""E4A-C Test for Zero Order Endpoint Invocation Safety."""

import pytest
from pathlib import Path


def test_no_order_endpoint_calls_in_eye():
    src_dir = Path(__file__).parent.parent.parent / "src" / "eye"
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text()
        assert "place_order" not in text
        assert "modify_order" not in text
        assert "cancel_order" not in text
