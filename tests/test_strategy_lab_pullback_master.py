from pathlib import Path

import pytest

from app.main import strategy_lab_service
from src.strategy_lab import StrategyLabService
from src.strategy_lab.strategies.pullback_master import (
    CLASSIFICATION,
    PARITY_STATUS,
    PullbackMasterPineEventAdapter,
    SOURCE_SHA256,
    STRATEGY_ID,
    build_deployment_request,
)
from src.strategy_lab.strategies.pullback_master.audit import inspect_pine_source
from src.strategy_lab.strategies.pullback_master.deployment import SOURCE_REFERENCE


@pytest.mark.unit
def test_authoritative_pine_source_identity_and_complete_input_audit():
    audit = inspect_pine_source(SOURCE_REFERENCE)
    assert audit["source_sha256"] == SOURCE_SHA256
    assert audit["pine_version"] == 5
    assert audit["line_count"] == 2617
    assert audit["input_count"] == 157
    assert len({row["name"] for row in audit["inputs"]}) == 157
    assert audit["request_security_count"] == 5
    assert all(row["lookahead_off"] and row["gaps_off"] for row in audit["request_security"])
    assert audit["has_process_orders_on_close"] is True
    assert audit["has_calc_on_every_tick"] is True
    assert audit["has_barstate_confirmed_gate"] is True
    assert audit["session_literals"] == ["0915-1200", "1200-1400", "1400-1515"]
    assert audit["contains_strategy_long"] is True
    assert audit["contains_strategy_short"] is False


@pytest.mark.safety
def test_adapter_fails_closed_without_authoritative_event():
    result = PullbackMasterPineEventAdapter().evaluate({"closed": True})
    assert result["signal"] == "WAIT"
    assert result["reason"] == "AUTHORITATIVE_PINE_EVENT_REQUIRED"
    assert result["entry"] is None
    assert result["parity_status"] == PARITY_STATUS


@pytest.mark.safety
def test_adapter_rejects_wrong_source_and_incomplete_candle():
    adapter = PullbackMasterPineEventAdapter()
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        adapter.evaluate({"pine_event": {"source_sha256": "0" * 64, "event_id": "x", "candle_closed": True}})
    result = adapter.evaluate(
        {
            "pine_event": {
                "source_sha256": SOURCE_SHA256,
                "event_id": "bar-100",
                "candle_closed": False,
                "action": "BUY",
            }
        }
    )
    assert result["signal"] == "WAIT"
    assert result["reason"] == "INCOMPLETE_CANDLE_REJECTED"


@pytest.mark.unit
def test_adapter_preserves_authoritative_event_fields_without_calculation():
    event = {
        "source_sha256": SOURCE_SHA256,
        "event_id": "bar-101-buy",
        "candle_closed": True,
        "bar_index": 101,
        "candle_time": "2026-07-14T09:20:00+05:30",
        "action": "BUY",
        "reason": "PINE_BUY",
        "why_trade": ["SOURCE_EVENT"],
        "entry": 25000.0,
        "stop": 24980.0,
        "target": 25080.0,
    }
    result = PullbackMasterPineEventAdapter().evaluate({"pine_event": event})
    assert result["signal"] == "BUY"
    assert result["pine_action"] == "BUY"
    assert result["entry"] == event["entry"]
    assert result["stop"] == event["stop"]
    assert result["target"] == event["target"]
    assert result["authoritative_pine_event"] == event


@pytest.mark.unit
def test_exit_actions_preserve_pine_action_while_mapping_to_lab_sell():
    adapter = PullbackMasterPineEventAdapter()
    for action in ("SELL", "TARGET", "SL"):
        result = adapter.evaluate(
            {
                "pine_event": {
                    "source_sha256": SOURCE_SHA256,
                    "event_id": f"bar-102-{action}",
                    "candle_closed": True,
                    "action": action,
                    "exit": 25050.0,
                }
            }
        )
        assert result["signal"] == "SELL"
        assert result["pine_action"] == action


@pytest.mark.integration
def test_deployment_is_running_paper_only_and_strategy_lab_only(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(
        build_deployment_request(
            context_provider=lambda: {
                "data_readiness": {"DATA_READY": True, "not_ready_reason": None}
            }
        ),
        start=True,
    )
    service.start()
    try:
        status = runtime.status()
        assert status["state"] == "RUNNING"
        assert status["readiness"] == "READY"
        assert status["scheduler"]["thread_alive"] is True
        assert status["scheduler"]["activation_enabled"] is True
        assert status["paper_only"] is True
        assert status["production_state_mutated"] is False
        assert status["development_state_mutated"] is False
        assert status["metadata"]["parameters"]["classification"] == CLASSIFICATION
    finally:
        service.stop()
    assert runtime.status()["state"] == "STOPPED"
    assert runtime.status()["live_trading_enabled"] is False


@pytest.mark.integration
def test_application_registers_pullback_master_for_paper_activation():
    rows = strategy_lab_service.strategies()["strategies"]
    deployment = next(row for row in rows if row["strategy_id"] == STRATEGY_ID)
    assert deployment["metadata"]["status"] == "PAPER_ACTIVE"
    assert deployment["scheduler"]["activation_enabled"] is True
    assert deployment["paper_only"] is True
    assert deployment["live_trading_enabled"] is False
    assert deployment["broker_submission"] is False


@pytest.mark.unit
def test_onboarding_artifacts_exist():
    root = Path("src/strategy_lab/strategies/pullback_master")
    assert all(
        (root / name).is_file()
        for name in (
            "metadata.json",
            "deployment_manifest.json",
            "replay_mapping.json",
            "journal_mapping.json",
            "evidence_mapping.json",
        )
    )
