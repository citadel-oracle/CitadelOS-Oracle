from pathlib import Path

import pytest

from app.main import strategy_lab_service
from src.strategy_lab import StrategyLabService
from src.strategy_lab.strategies.breakout_main import STRATEGY_ID, build_deployment_request
from src.strategy_lab.strategies.breakout_main.adapters import (
    BreakoutMainEvidenceAdapter,
    BreakoutMainJournalAdapter,
    BreakoutMainReplayAdapter,
    BreakoutMainRiskAdapter,
    BreakoutMainSignalEngine,
)
from src.strategy_lab.strategies.breakout_main.runtime import BreakoutMainRuntimeInterface


@pytest.mark.safety
def test_breakout_main_registration_starts_isolated_paper_engine(tmp_path):
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
    status = runtime.status()
    assert status["state"] == "RUNNING"
    assert status["readiness"] == "READY"
    assert status["scheduler"]["thread_alive"] is True
    assert status["scheduler"]["activation_enabled"] is True
    assert runtime.workspace.read("paper_engine_state")["paper_only"] is True
    assert runtime.workspace.order_ledger.read() == []
    assert runtime.workspace.fill_ledger.read() == []


@pytest.mark.unit
def test_breakout_main_placeholders_fail_closed():
    assert BreakoutMainSignalEngine().evaluate({})["status"] == "NOT_IMPLEMENTED"
    assert BreakoutMainSignalEngine().evaluate({})["signal"] == "WAIT"
    for adapter in (
        BreakoutMainRiskAdapter(),
        BreakoutMainJournalAdapter(),
        BreakoutMainReplayAdapter(),
        BreakoutMainEvidenceAdapter(),
    ):
        method = getattr(adapter, "evaluate", None) or adapter.record
        assert method({})["status"] == "NOT_IMPLEMENTED"
    runtime = BreakoutMainRuntimeInterface()
    assert all(
        result["status"] == "NOT_IMPLEMENTED"
        for result in (runtime.status(), runtime.start(), runtime.stop(), runtime.tick({}))
    )


@pytest.mark.integration
def test_application_registers_breakout_main_for_paper_activation():
    row = next(item for item in strategy_lab_service.strategies()["strategies"] if item["strategy_id"] == STRATEGY_ID)
    assert row["metadata"]["status"] == "PAPER_ACTIVE"
    assert row["scheduler"]["activation_enabled"] is True
    assert row["paper_only"] is True
    assert row["live_trading_enabled"] is False


@pytest.mark.unit
def test_phase_two_repository_artifacts_exist():
    root = Path("src/strategy_lab/strategies/breakout_main")
    assert all(
        (root / name).is_file()
        for name in (
            "strategy_manifest.json",
            "deployment_config.json",
            "configuration_schema.json",
            "parameter_schema.json",
            "README.md",
        )
    )
