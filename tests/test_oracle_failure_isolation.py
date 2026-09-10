"""Phase 24 & Phase 25 Failure Isolation and Zero Live Authority Verification."""

import pytest
from src.external_context.core import ExternalContextCore
from src.oracle_sol.local_model_adapter import OllamaQwenAdapter
from src.oracle_sol.resource_governor import ResourceGovernor


def test_ollama_down_does_not_crash_adapter():
    """Verify that if Ollama service is unreachable, adapter returns structured error telemetry without crashing."""
    adapter = OllamaQwenAdapter(ollama_host="http://127.0.0.1:59999")  # Non-existent port
    output, telemetry = adapter.invoke_reasoning(
        request_id="req_test_down",
        system_prompt="test",
        user_prompt="test",
        timeout_seconds=0.5,
    )
    assert output is None
    assert telemetry["schema_status"] == "TRANSPORT_ERROR"
    assert telemetry["error"] is not None


def test_external_context_continues_if_provider_fails():
    """Verify that failure or missing keys in news/market providers does not break other feeds."""
    core = ExternalContextCore()
    # Marketaux key missing
    assert core.news_adapter.is_configured is False
    assert core.news_adapter.last_status == "MARKETAUX_KEY_REQUIRED"

    # TwelveData key missing
    assert core.market_adapter.is_configured is False
    assert core.market_adapter.last_status == "TWELVEDATA_KEY_REQUIRED"

    # Polling still completes gracefully without unhandled exceptions
    poll_results = core.poll_all_now()
    assert isinstance(poll_results, dict)
    assert "new_events" in poll_results
    assert "total_events" in poll_results


def test_zero_live_authority_configuration():
    """Verify strictly enforced shadow-only isolation flags."""
    from src.oracle_sol.local_brain_service import LocalBrainService
    service = LocalBrainService.get_instance()
    state = service.get_shadow_state()
    assert state["mode"] == "SHADOW"
    # Ensure no broker execution methods exist on LocalBrainService
    assert not hasattr(service, "place_order")
    assert not hasattr(service, "submit_order")
    assert not hasattr(service, "execute_trade")
    assert not hasattr(service, "cancel_order")


def test_vob_firewall_untouchable():
    """Verify that VOB engine does not import or depend on LocalBrain or ExternalContext."""
    import src.vob.engine as vob_engine
    vob_source = open(vob_engine.__file__).read()
    assert "qwen" not in vob_source.lower()
    assert "external_context" not in vob_source.lower()
    assert "local_brain" not in vob_source.lower()
