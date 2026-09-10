from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pytest

from app.main import app, v2_integration
from src.strategy_lab import (
    DeploymentRequest,
    StrategyInputType,
    StrategyLabService,
    StrategyMetadata,
    deployment_capabilities,
)
from src.strategy_lab.storage import StrategyWorkspace


class WaitStrategy:
    def __init__(self, evaluation_id: str = "wait-1"):
        self.evaluation_id = evaluation_id

    def evaluate(self, context):
        return {
            "evaluation_id": self.evaluation_id,
            "signal": "WAIT",
            "reason": "RULE_NOT_SATISFIED",
            "why_trade": None,
            "why_not_trade": "RULE_NOT_SATISFIED",
            "technical_snapshot": context,
            "module_votes": {},
            "weights": {},
            "confidence": None,
            "coverage": None,
            "position_state": {},  # Bypass compact_wait optimization in tests
        }


class CrashingStrategy:
    def evaluate(self, context):
        raise RuntimeError("isolated failure")


def metadata(strategy_id: str, name: Optional[str] = None) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id,
        name=name or strategy_id,
        version="1.0.0",
        author="Test",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NIFTY"],
        supported_timeframes=["5m"],
        rr=2.0,
        risk_model="ISOLATED_TEST_RISK",
        parameters={"period": 21},
    )


def request(strategy_id: str, adapter=None) -> DeploymentRequest:
    return DeploymentRequest(
        metadata=metadata(strategy_id),
        adapter=adapter or WaitStrategy(strategy_id),
        context_provider=lambda: {"symbol": "NIFTY", "closed": True},
        scheduler_interval_seconds=60,
    )


@pytest.mark.unit
def test_deployment_interfaces_are_truthful_and_pine_is_not_implemented():
    capabilities = deployment_capabilities()
    assert len(capabilities["adapters"]) == 7
    assert {row["input_type"] for row in capabilities["adapters"]} == {
        item.value for item in StrategyInputType
    }
    assert capabilities["pine_parser_implemented"] is False
    assert capabilities["broker_execution_supported"] is False
    assert capabilities["paper_only"] is True


@pytest.mark.integration
def test_each_strategy_has_independent_state_and_immutable_streams(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    first = service.deploy(request("alpha"))
    second = service.deploy(request("beta"))

    assert first.workspace.root != second.workspace.root
    assert set(first.workspace.paths) == set(second.workspace.paths)
    assert all(first.workspace.paths[key] != second.workspace.paths[key] for key in first.workspace.paths)

    assert first.tick_once()["status"] == "EVALUATED"
    assert second.tick_once()["status"] == "EVALUATED"
    assert len(first.workspace.journal.read()) == 1
    assert len(second.workspace.journal.read()) == 1
    assert len(first.workspace.replay.read()) == 1
    assert len(second.workspace.replay.read()) == 1


@pytest.mark.safety
def test_runtime_failure_is_contained_during_tournament(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    service.deploy(request("healthy", WaitStrategy("healthy-1")))
    service.deploy(request("broken", CrashingStrategy()))

    result = service.evaluate_tournament({"symbol": "NIFTY", "closed": True})

    assert result["outcomes"]["healthy"]["status"] == "EVALUATED"
    assert result["outcomes"]["broken"]["status"] == "ERROR"
    assert service.strategy_detail("healthy")["strategy"]["health"] == "HEALTHY"
    assert service.strategy_detail("broken")["strategy"]["health"] == "DEGRADED"


@pytest.mark.safety
def test_evidence_is_secret_safe_and_hash_chained(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("safe"))
    runtime.tick_once(
        context_override={
            "symbol": "NIFTY",
            "closed": True,
            "api_key": "must-not-persist",
            "nested": {"access_token": "must-not-persist"},
        }
    )
    serialized = str(runtime.workspace.evidence.read())
    assert "must-not-persist" not in serialized
    assert runtime.workspace.evidence.verify() == {
        "valid": True,
        "records": 1,
        "failure_index": None,
    }


@pytest.mark.unit
def test_leaderboard_uses_completed_paper_trades_only(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    winner = service.deploy(request("winner"))
    unranked = service.deploy(request("unranked"))
    winner.workspace.record_completed_trade(
        {"trade_id": "trade-1", "realized_pnl": 100.0, "realized_r": 2.0, "mfe": 2.5, "mae": -0.5}
    )
    winner.workspace.record_completed_trade(
        {"trade_id": "trade-2", "realized_pnl": -25.0, "realized_r": -0.5, "mfe": 0.2, "mae": -0.6}
    )

    board = service.leaderboard()
    assert [row["strategy_id"] for row in board["entries"]] == ["winner"]
    assert board["basis"] == "COMPLETED_PAPER_TRADES_ONLY"
    assert board["entries"][0]["completed_trades"] == 2
    assert unranked.status()["statistics"]["ranking_eligible"] is False


@pytest.mark.unit
def test_strategy_detail_exposes_required_research_views(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("detail"))
    runtime.tick_once()
    detail = service.strategy_detail("detail")
    assert {
        "overview",
        "statistics",
        "journal",
        "replay",
        "evidence",
        "trades",
        "equity_curve",
        "parameters",
        "logs",
        "order_ledger",
        "fill_ledger",
    }.issubset(detail)


@pytest.mark.safety
def test_service_is_paper_only_and_has_no_broker_mutation_surface(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    status = service.status()
    assert status["paper_only"] is True
    assert status["live_trading_enabled"] is False
    assert status["broker_submission"] is False
    assert status["production_state_mutated"] is False
    assert status["development_state_mutated"] is False
    assert all(status[key] is False for key in (
        "shared_paper_state",
        "shared_ledger",
        "shared_scheduler_state",
        "shared_strategy_state",
        "shared_journal",
        "shared_execution_state",
    ))
    assert not hasattr(service, "place_order")
    assert not hasattr(service, "submit_order")


@pytest.mark.integration
def test_schedulers_start_and_stop_independently(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    first = service.deploy(request("first"))
    second = service.deploy(request("second"))
    service.start()
    try:
        assert first.status()["scheduler"]["thread_alive"] is True
        assert second.status()["scheduler"]["thread_alive"] is True
        assert first.status()["scheduler"]["state"] == "RUNNING"
        assert second.status()["scheduler"]["state"] == "RUNNING"
    finally:
        service.stop()
    assert first.status()["scheduler"]["thread_alive"] is False
    assert second.status()["scheduler"]["thread_alive"] is False


@pytest.mark.unit
def test_empty_dashboard_does_not_fabricate_strategies_or_results(tmp_path):
    dashboard = StrategyLabService(str(tmp_path / "lab")).dashboard()
    assert dashboard["empty_state"] == "NO_STRATEGIES_DEPLOYED"
    assert dashboard["strategies"] == []
    assert dashboard["leaderboard"]["entries"] == []
    assert dashboard["summary"]["completed_paper_trades"] == 0


@pytest.mark.unit
def test_live_publication_uses_prepared_options_and_skips_nifty_rebuild(tmp_path):
    service = StrategyLabService(str(tmp_path / "live-publication"))
    prepared_options = {
        "status": "LIVE",
        "revision": 17,
        "contracts": {"CE": {"security_id": "101"}},
    }

    dashboard = service.dashboard(
        live_publication=True,
        prepared_options_structure=prepared_options,
    )

    execution = dashboard["execution"]
    assert execution["options_structure"] == prepared_options
    assert execution["nifty_vob"]["status"] == "UNAVAILABLE"
    assert execution["nifty_vob"]["reason"] == "PREPARED_NIFTY_VOB_NOT_PUBLISHED"
    assert execution["paper_only"] is True
    assert execution["broker_submission"] is False


def test_dashboard_builds_one_request_scoped_strategy_and_paper_snapshot(tmp_path, monkeypatch):
    service = StrategyLabService(str(tmp_path / "lab"))
    service.deploy(request("single-snapshot"))
    calls = {"strategy_rows": 0, "paper_states": 0}
    original_rows = service._strategy_rows
    original_states = service._paper_states

    def rows(deployments):
        calls["strategy_rows"] += 1
        return original_rows(deployments)

    def states(*args, **kwargs):
        calls["paper_states"] += 1
        return original_states(*args, **kwargs)

    monkeypatch.setattr(service, "_strategy_rows", rows)
    monkeypatch.setattr(service, "_paper_states", states)

    dashboard = service.dashboard()

    assert dashboard["strategies"]
    assert calls == {"strategy_rows": 1, "paper_states": 1}


def test_workspace_projection_fields_invalidate_atomically_and_support_concurrent_reads(tmp_path):
    workspace = StrategyWorkspace(tmp_path / "runtimes", "cached")
    workspace.write(
        "strategy_state",
        {
            "current_decision": {"signal": "WAIT", "reason": "INITIAL"},
            "processed_candles": {"large-history": {"ignored": True}},
        },
    )

    assert workspace.read_fields("strategy_state", ("current_decision",)) == {
        "current_decision": {"signal": "WAIT", "reason": "INITIAL"}
    }

    workspace.write(
        "strategy_state",
        {
            "current_decision": {"signal": "BUY", "reason": "MUTATED"},
            "processed_candles": {"large-history": {"ignored": True}},
        },
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(
            lambda _: workspace.read_fields("strategy_state", ("current_decision",)),
            range(32),
        ))

    assert all(row["current_decision"]["signal"] == "BUY" for row in rows)
    assert all(row["current_decision"]["reason"] == "MUTATED" for row in rows)


def test_dashboard_uses_loaded_execution_snapshots_without_ledger_or_paper_state_rescans(tmp_path, monkeypatch):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("in-memory-execution"))
    calls = {"projection": 0, "paper_engine_state_reads": 0}
    original_projection = runtime.execution.projection
    original_read = StrategyWorkspace.read

    def projection():
        calls["projection"] += 1
        return original_projection()

    def read(workspace, name):
        if name == "paper_engine_state":
            calls["paper_engine_state_reads"] += 1
        return original_read(workspace, name)

    monkeypatch.setattr(runtime.execution, "projection", projection)
    monkeypatch.setattr(StrategyWorkspace, "read", read)

    dashboard = service.dashboard()

    assert dashboard["snapshot_version"] == 1
    assert dashboard["generated_at"]
    assert calls == {"projection": 1, "paper_engine_state_reads": 0}
    assert dashboard["portfolio"]["strategy_ids"] == ["in-memory-execution"]


def test_concurrent_dashboard_snapshots_are_versioned_and_scope_isolated(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    service.deploy(request("scope-a"))
    service.deploy(request("scope-b"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        snapshots = list(executor.map(lambda _: service.dashboard(), range(8)))

    versions = [snapshot["snapshot_version"] for snapshot in snapshots]
    assert sorted(versions) == list(range(1, 9))
    assert all(snapshot["generated_at"] for snapshot in snapshots)
    assert all(
        {row["strategy_id"] for row in snapshot["strategies"]} == {"scope-a", "scope-b"}
        for snapshot in snapshots
    )
    assert all(
        set(snapshot["portfolio"]["strategy_ids"]) == {"scope-a", "scope-b"}
        for snapshot in snapshots
    )


def test_journal_tail_cache_invalidates_after_append(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    workspace = StrategyWorkspace(tmp_path / "lab" / "runtimes", "journal-cache")
    workspace.journal.append("FIRST", {"signal": "BUY"}, idempotency_key="first")
    first = service._read_recent_jsonl(workspace.journal.path, limit=10)
    cached = service._read_recent_jsonl(workspace.journal.path, limit=10)

    workspace.journal.append("SECOND", {"signal": "SELL"}, idempotency_key="second")
    updated = service._read_recent_jsonl(workspace.journal.path, limit=10)

    assert cached is first
    assert [row["event_type"] for row in updated] == ["FIRST", "SECOND"]


def test_dashboard_review_cache_ignores_wait_only_journal_churn(tmp_path, monkeypatch):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("review-cache"))
    calls = {"review": 0}
    original_review = service.review_projection

    def review(deployments=None):
        calls["review"] += 1
        return original_review(deployments)

    monkeypatch.setattr(service, "review_projection", review)

    first = service.dashboard()
    runtime.workspace.journal.append(
        "STRATEGY_DECISION",
        {"signal": "WAIT", "reason": "RULE_NOT_SATISFIED"},
        idempotency_key="wait-only-churn",
    )
    second = service.dashboard()

    assert calls["review"] == 1
    assert first["performance"]["review_cache_hit"] is False
    assert second["performance"]["review_cache_hit"] is True


def test_review_cache_signature_changes_for_execution_lifecycle():
    empty = [{"strategy_id": "alpha", "orders": [], "fills": [], "positions": [], "closed_trades": []}]
    executed = [{
        "strategy_id": "alpha",
        "orders": [{"order_id": "order-1", "status": "FILLED", "updated_at": "now"}],
        "fills": [{"fill_id": "fill-1", "order_id": "order-1", "time": "now"}],
        "positions": [{"position_id": "position-1", "status": "OPEN"}],
        "closed_trades": [],
    }]

    service_signature = StrategyLabService._review_execution_signature(empty)
    assert service_signature
    assert service_signature != StrategyLabService._review_execution_signature(executed)


@pytest.mark.integration
def test_strategy_lab_routes_are_get_only_and_v2_contains_projection():
    paths = {
        "/v1/strategy-lab/status",
        "/v1/strategy-lab/dashboard",
        "/v1/strategy-lab/strategies",
        "/v1/strategy-lab/leaderboard",
        "/v1/strategy-lab/strategies/{strategy_id}",
    }
    strategy_routes = [route for route in app.routes if getattr(route, "path", None) in paths]
    assert {route.path for route in strategy_routes} == paths
    assert all(route.methods == {"GET"} for route in strategy_routes)
    assert "strategy_lab" in v2_integration.providers
    assert v2_integration.providers["strategy_lab"]()["status"]["paper_only"] is True
