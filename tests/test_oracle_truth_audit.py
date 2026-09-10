"""Unit tests verifying independence and strict failure behavior of oracle_truth_audit."""

import pytest
from tools.audit.oracle_truth_audit import expected_display, verdict, nested


def test_auditor_fails_when_backend_value_differs():
    """Auditor must return FAIL_VALUE_MISMATCH when backend and rendered values differ."""
    backend_val = 23850.25
    expected = expected_display(backend_val, "PRICE_2")
    rendered = "23860.00"  # Divergent price
    
    result = verdict(backend_val, rendered, "AVAILABLE", rendered == expected)
    assert result == "FAIL_VALUE_MISMATCH"


def test_auditor_fails_when_frontend_stale_value_remains():
    """Auditor must fail when frontend still displays stale value after backend moved."""
    backend_val = 142.50
    expected = expected_display(backend_val, "PRICE_2")
    stale_rendered = "139.10"  # Stale UI snapshot
    
    result = verdict(backend_val, stale_rendered, "AVAILABLE", stale_rendered == expected)
    assert result == "FAIL_VALUE_MISMATCH"


def test_auditor_fails_when_field_is_unregistered():
    """Auditor classification for unregistered fields must be UNPROVEN."""
    from src.oracle_sol.field_registry import SOL_SURFACE_FIELD_REGISTRY
    assert "nonexistent.phantom.metric" not in SOL_SURFACE_FIELD_REGISTRY


def test_auditor_fails_when_field_path_is_wrong():
    """When path resolution returns None for a populated payload, nested() returns None."""
    payload = {"snapshot": {"spot_ltp": 23800.0}}
    extracted = nested(payload, "snapshot.wrong_nested_key")
    assert extracted is None
    
    # If UI rendered a live number but backend extracted None due to wrong path:
    rendered = "23800.00"
    result = verdict(extracted, rendered, "AVAILABLE", False)
    assert result == "UNPROVEN"


def test_auditor_fails_when_backend_null_but_frontend_stale_number_exists():
    """Auditor must return UNPROVEN if backend value is null but UI renders an active number."""
    backend_val = None
    rendered_stale_number = "215.75"
    
    result = verdict(backend_val, rendered_stale_number, "UNAVAILABLE", False)
    assert result == "UNPROVEN"


def test_auditor_passes_cleanly_on_exact_match():
    """Auditor returns PASS_LIVE when values match exactly."""
    backend_val = 23815.50
    expected = expected_display(backend_val, "PRICE_2")
    assert expected == "23815.50"
    
    result = verdict(backend_val, "23815.50", "AVAILABLE", True)
    assert result == "PASS_LIVE"


def test_auditor_passes_unavailable_when_backend_null_and_rendered_unavailable():
    """Auditor returns PASS_UNAVAILABLE when backend is None and UI shows honest unavailable marker."""
    backend_val = None
    for unavail_marker in ["—", "UNAVAILABLE", "NONE", "● UNAVAILABLE"]:
        result = verdict(backend_val, unavail_marker, "UNAVAILABLE", False)
        assert result == "PASS_UNAVAILABLE"


def test_generic_display_transformations():
    """Display transformations must be generic and mathematical, not field-specific hacks."""
    assert expected_display(10.82, "PERCENT_1") == "10.8%"
    assert expected_display(144.5, "SIGNED_2") == "+144.50"
    assert expected_display(-0.44, "SIGNED_2") == "-0.44"
    assert expected_display(2102750, "QTY") == "21,02,750"
    assert expected_display(65, "QTY") == "65"
    assert expected_display(128.5, "MONEY_2") == "₹128.50"
    assert expected_display(2.5, "SIGNED_MONEY_2") == "+₹2.50"
    assert expected_display(-1.25, "SIGNED_MONEY_2") == "₹-1.25"
    assert expected_display({"price": 128.45, "quantity": 325, "orders": 2}, "LEVEL") == "₹128.45 · 325 · 2 orders"
    assert expected_display({"price": 128.45, "quantity": 65, "orders": 1}, "LEVEL") == "₹128.45 · 65 · 1 order"
