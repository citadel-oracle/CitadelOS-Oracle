from __future__ import annotations

import importlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.development.strategy import SimplePullbackDevelopment
from src.strategy_command import (
    AggregationMode,
    StrategyCommandService,
    canonical_configuration_hash,
    evaluate_price_action,
)
from src.strategy_command.models import (
    ConflictPolicy,
    StrategyContract,
    default_configuration,
    validate_configuration,
)


class Context:
    def __init__(self, *, bias="BULLISH", close=110, ema21=105, ema38=100):
        self.indicators = {"close": close, "ema_21": ema21, "ema_38": ema38}
        self.kronos = {"bias": bias}
        self.confidence = 82


def service(tmp_path: Path, runtime=None, failure_injector=None) -> StrategyCommandService:
    return StrategyCommandService(
        tmp_path,
        runtime_provider=lambda: runtime or {"strategies": []},
        failure_injector=failure_injector,
    )


def first_version(subject: StrategyCommandService):
    projection = subject.projection()
    version = projection["versions"][0]
    return version["strategy_id"], version["version"]


def test_registry_discovers_valid_strategy_contracts_as_disabled_drafts(tmp_path):
    projection = service(tmp_path).projection()
    assert {row["strategy_id"] for row in projection["definitions"]} == {
        "breakout-main-pine-v5",
        "pullback-master-pine-v5",
        "TC_NIFTY_PE_1M",
        "BP_NIFTY_CE_1M",
    }
    assert projection["registration_errors"] == []
    assert all(row["registration_state"] == "DRAFT" for row in projection["definitions"])
    assert all(row["enabled"] is False for row in projection["definitions"])
    assert all(row["signal_logic"].endswith(".evaluate") for row in projection["versions"])


def test_invalid_and_duplicate_contracts_are_rejected_truthfully(tmp_path, monkeypatch):
    subject = service(tmp_path)
    existing = subject._contract_from_module(
        "src.strategy_lab.strategies.breakout_main.deployment"
    )
    invalid = deepcopy(existing.to_dict())
    invalid["signal_logic"] = ""
    with pytest.raises(ValueError, match="STRATEGY_CONTRACT_MISSING"):
        StrategyContract(**{
            key: tuple(value) if key in {
                "supported_instruments", "supported_timeframes", "required_inputs",
                "optional_inputs", "execution_compatibility",
            } else value
            for key, value in invalid.items()
            if key in StrategyContract.__dataclass_fields__
        })


def test_temporary_valid_and_invalid_discovery_fixtures_are_truthful(tmp_path, monkeypatch):
    package = tmp_path / "fixture_strategies"
    valid = package / "valid_fixture"
    invalid = package / "invalid_fixture"
    valid.mkdir(parents=True)
    invalid.mkdir(parents=True)
    for path in (package / "__init__.py", valid / "__init__.py", invalid / "__init__.py"):
        path.write_text("", encoding="utf-8")
    valid.joinpath("deployment.py").write_text(
        "\n".join((
            "from src.strategy_lab.strategies.breakout_main.deployment import build_deployment_request as _build",
            "STRATEGY_ID = 'temporary-valid-strategy'",
            "def build_deployment_request(provider):",
            "    return _build(provider, deployment_id=STRATEGY_ID, deployment_name='TEMP VALID')",
        )),
        encoding="utf-8",
    )
    invalid.joinpath("deployment.py").write_text(
        "STRATEGY_ID = 'temporary-invalid-strategy'\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    monkeypatch.setattr("src.strategy_command.service.DISCOVERY_PACKAGE", "fixture_strategies")
    subject = StrategyCommandService(tmp_path / "state")
    projection = subject.projection()
    assert [row["strategy_id"] for row in projection["definitions"]] == [
        "temporary-valid-strategy"
    ]
    definition = projection["definitions"][0]
    assert definition["registration_state"] == "DRAFT"
    assert definition["enabled"] is False
    assert projection["registration_errors"] == [{
        "module": "fixture_strategies.invalid_fixture.deployment",
        "reason": "ValueError:STRATEGY_CONTRACT_BUILDER_MISSING",
    }]


def test_duplicate_discovery_is_rejected_with_exact_modules(tmp_path, monkeypatch):
    subject = service(tmp_path)
    contract = subject._contract_from_module(
        "src.strategy_lab.strategies.breakout_main.deployment"
    )
    monkeypatch.setattr(subject, "_contract_from_module", lambda _: contract)
    result = subject.discover()
    assert len(result["errors"]) == 3
    assert all(
        row["reason"].startswith(
            f"DUPLICATE_STRATEGY_ID:{contract.strategy_id}:"
        )
        for row in result["errors"]
    )


def test_new_version_preserves_prior_immutable_version(tmp_path, monkeypatch):
    subject = service(tmp_path)
    module_name = "src.strategy_lab.strategies.breakout_main.deployment"
    original = subject._contract_from_module
    current = original(module_name)

    def upgraded(name):
        contract = original(name)
        return replace(contract, version="PINE_V5_NEXT") if name == module_name else contract

    monkeypatch.setattr(subject, "_contract_from_module", upgraded)
    subject.discover()
    definition = next(
        row for row in subject.projection()["definitions"]
        if row["strategy_id"] == current.strategy_id
    )
    assert definition["latest_version"] == "PINE_V5_NEXT"
    assert definition["versions"] == sorted([current.version, "PINE_V5_NEXT"])


def test_schema_fails_closed_for_live_or_invalid_decision_weights(tmp_path):
    subject = service(tmp_path)
    version = subject.projection()["versions"][0]
    contract = StrategyContract(**{
        key: tuple(value) if key in {
            "supported_instruments", "supported_timeframes", "required_inputs",
            "optional_inputs", "execution_compatibility",
        } else value
        for key, value in version.items()
        if key in StrategyContract.__dataclass_fields__
    })
    config = default_configuration(contract)
    with pytest.raises(ValueError, match="LIVE_TRADING_MUST_REMAIN_DISABLED"):
        validate_configuration(_deep_test_merge(
            config, {"execution": {"live_trading_enabled": True}}
        ))
    with pytest.raises(ValueError, match="DECISION_WEIGHTS_MUST_TOTAL_100"):
        validate_configuration(_deep_test_merge(
            config, {"decision": {"weights": {
                "price_action": 50,
                "vob": 25,
                "strategy_trigger": 24,
            }}}
        ))


def test_conflict_policy_is_versioned_inside_configuration_hash(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    base = subject.save_draft(strategy_id=strategy_id, strategy_version=version)
    changed = subject.duplicate(base["deployment_instance_id"], overrides={
        "conflict": {"policy": ConflictPolicy.HIGHEST_SCORE_WINS.value},
    })
    assert changed["configuration"]["conflict"]["policy"] == "HIGHEST_SCORE_WINS"
    assert changed["configuration_hash"] != base["configuration_hash"]


def test_three_instances_are_isolated_and_hashes_change_only_with_configuration(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    first = subject.save_draft(strategy_id=strategy_id, strategy_version=version)
    second = subject.duplicate(first["deployment_instance_id"], overrides={
        "timeframes": {"roles": {"entry": ["3m"]}},
    })
    third = subject.duplicate(first["deployment_instance_id"], overrides={
        "execution": {"path": "ORACLE_SHADOW"},
    })
    assert len({row["deployment_instance_id"] for row in (first, second, third)}) == 3
    assert len({row["configuration_hash"] for row in (first, second, third)}) == 3
    current = subject.projection()["deployments"]
    stored_first = next(row for row in current if row["deployment_instance_id"] == first["deployment_instance_id"])
    assert stored_first["configuration"] == first["configuration"]
    assert second["configuration"]["timeframes"]["roles"]["entry"] == ["3m"]
    assert third["configuration"]["execution"]["path"] == "ORACLE_SHADOW"


def test_edit_pause_deploy_and_rollback_one_instance_leave_peers_unchanged(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    roles = lambda timeframe: {
        role: [timeframe]
        for role in ("signal", "entry", "confirmation", "exit", "guardian")
    }
    specifications = (
        ("nifty-3m-paper", {"market": {"instrument": "NIFTY"}, "timeframes": {"roles": roles("3m")}, "position": {"fixed_lots": 1, "maximum_lots": 1}, "execution": {"enabled": True, "path": "ORACLE_PAPER"}}),
        ("nifty-5m-shadow", {"market": {"instrument": "NIFTY"}, "timeframes": {"roles": roles("5m")}, "position": {"fixed_lots": 2, "maximum_lots": 2}, "execution": {"enabled": True, "path": "ORACLE_SHADOW"}}),
        ("banknifty-15m-observe", {"market": {"instrument": "BANKNIFTY"}, "timeframes": {"roles": roles("15m")}, "execution": {"enabled": True, "path": "WORKSPACE_OBSERVE"}}),
    )
    drafts = [
        subject.save_draft(
            strategy_id=strategy_id,
            strategy_version=version,
            deployment_instance_id=instance_id,
            configuration=config,
        )
        for instance_id, config in specifications
    ]
    for draft in drafts:
        subject.deploy(draft["deployment_instance_id"], expected_configuration_hash=draft["configuration_hash"])
    peers_before = {
        row["deployment_instance_id"]: deepcopy(row)
        for row in subject.projection()["deployments"][1:]
    }
    edited = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        deployment_instance_id=drafts[0]["deployment_instance_id"],
        configuration={"session": {"maximum_trades_per_day": 2}},
    )
    subject.deploy(edited["deployment_instance_id"], expected_configuration_hash=edited["configuration_hash"])
    subject.pause(edited["deployment_instance_id"])
    rolled_back = subject.rollback(edited["deployment_instance_id"])
    assert rolled_back["configuration_hash"] == drafts[0]["configuration_hash"]
    peers_after = {
        row["deployment_instance_id"]: row
        for row in subject.projection()["deployments"][1:]
    }
    for instance_id, before in peers_before.items():
        assert peers_after[instance_id]["configuration"] == before["configuration"]
        assert peers_after[instance_id]["configuration_hash"] == before["configuration_hash"]
        assert peers_after[instance_id]["state"] == before["state"]


def test_simple_and_advanced_modes_share_one_canonical_configuration(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    draft = subject.save_draft(strategy_id=strategy_id, strategy_version=version)
    assert canonical_configuration_hash(draft["configuration"]) == draft["configuration_hash"]
    assert set(draft["configuration"]) >= {
        "market", "timeframes", "position", "session", "entry", "exit",
        "guardian", "decision", "conflict", "execution",
    }
    schema = subject.projection()["configuration_schema"]
    assert schema["modes"] == ["SIMPLE", "ADVANCED"]
    assert set(schema["sections"]) == {
        "market", "timeframes", "position", "session", "entry", "exit", "guardian",
    }
    edited = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        deployment_instance_id=draft["deployment_instance_id"],
        configuration={"position": {"fixed_lots": 1, "maximum_lots": 2}},
    )
    assert edited["configuration"]["market"] == draft["configuration"]["market"]
    assert edited["configuration"]["entry"] == draft["configuration"]["entry"]
    assert edited["configuration"]["position"]["maximum_lots"] == 2


def test_multi_timeframe_consensus_is_explicit_and_deterministic(tmp_path):
    subject = service(tmp_path)
    votes = {"3m": "BULLISH", "5m": "BULLISH", "15m": "BEARISH"}
    assert subject.consensus(votes, AggregationMode.MAJORITY.value) == {
        "mode": "MAJORITY",
        "votes": votes,
        "consensus": "BULLISH",
    }
    primary = subject.consensus(
        votes,
        AggregationMode.PRIMARY_PLUS_CONFIRMATION.value,
        primary="3m",
    )
    assert primary["consensus"] == "BULLISH"


def test_all_multi_timeframe_modes_are_deterministic_and_fail_closed(tmp_path):
    subject = service(tmp_path)
    votes = {"3m": "BULLISH", "5m": "BULLISH", "15m": "BEARISH"}
    expected = {
        "ANY": "CONFLICT",
        "ALL": "CONFLICT",
        "MAJORITY": "BULLISH",
        "WEIGHTED": "BULLISH",
        "PRIMARY_PLUS_CONFIRMATION": "BULLISH",
        "HIGHEST_TIMEFRAME_PRIORITY": "BEARISH",
    }
    for mode, consensus in expected.items():
        options = {}
        if mode == "WEIGHTED":
            options["weights"] = {"3m": 50, "5m": 30, "15m": 20}
        if mode == "PRIMARY_PLUS_CONFIRMATION":
            options["primary"] = "3m"
        first = subject.consensus(votes, mode, **options)
        second = subject.consensus(dict(reversed(list(votes.items()))), mode, **options)
        assert first == second
        assert first["consensus"] == consensus
    assert subject.consensus(
        {"3m": "BULLISH"},
        "MAJORITY",
        required_timeframes=["3m", "5m"],
    )["reason"] == "TIMEFRAME_DATA_MISSING"
    assert subject.consensus(
        votes,
        "MAJORITY",
        stale_timeframes=["5m"],
    )["reason"] == "TIMEFRAME_DATA_STALE"
    with pytest.raises(ValueError, match="TIMEFRAME_WEIGHTS_INCOMPLETE"):
        subject.consensus(votes, "WEIGHTED", weights={"3m": 1})


def test_atomic_deployment_verifies_runtime_hash_and_emits_receipt_notification(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    draft = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        configuration={"execution": {"enabled": True, "path": "ORACLE_SHADOW"}},
    )
    receipt = subject.deploy(
        draft["deployment_instance_id"],
        expected_configuration_hash=draft["configuration_hash"],
    )
    assert receipt["status"] == "STRATEGY_DEPLOYED_SUCCESSFULLY"
    assert receipt["hash_verified"] is True
    assert receipt["configuration_hash"] == receipt["runtime_configuration_hash"]
    assert receipt["deployment_stages"] == [
        "VALIDATING",
        "SAVING_CONFIGURATION",
        "SYNCHRONIZING_RUNTIME",
        "ACTIVATING",
        "ACTIVE",
    ]
    assert receipt["deployment_receipt_id"].startswith("lab_")
    assert receipt["paper_only"] is True
    assert receipt["live_trading_enabled"] is False
    assert receipt["broker_submission"] is False
    projection = subject.projection()
    assert len(projection["active_deployments"]) == 1
    assert projection["notifications"][-1]["severity"] == "SUCCESS"
    notification_id = projection["notifications"][-1]["notification_id"]
    assert subject.acknowledge_notification(notification_id)["acknowledged"] is True
    assert subject.projection()["notifications"][-1]["acknowledged"] is True


def test_failed_runtime_sync_rolls_back_previous_active_version(tmp_path, monkeypatch):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    first = subject.save_draft(strategy_id=strategy_id, strategy_version=version)
    subject.deploy(first["deployment_instance_id"], expected_configuration_hash=first["configuration_hash"])
    edited = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        deployment_instance_id=first["deployment_instance_id"],
        configuration={"position": {"fixed_lots": 1, "maximum_lots": 2}},
    )
    monkeypatch.setattr(subject, "_load_runtime", lambda deployment: {
        "configuration_hash": "wrong",
        "loaded_at": "2026-07-28T00:00:00+00:00",
        "state": "ERROR",
        "reason": "TEST_HASH_MISMATCH",
    })
    with pytest.raises(RuntimeError, match="RUNTIME_HASH_MISMATCH"):
        subject.deploy(edited["deployment_instance_id"], expected_configuration_hash=edited["configuration_hash"])
    restored = next(row for row in subject.projection()["deployments"] if row["deployment_instance_id"] == edited["deployment_instance_id"])
    assert restored["state"] == "PAUSED"
    assert restored["configuration_hash"] == first["configuration_hash"]
    assert subject.projection()["notifications"][-1]["severity"] == "CRITICAL"


def test_oracle_projection_and_analytics_remain_instance_attributed(tmp_path):
    runtime = {
        "strategies": [{
            "strategy_id": "breakout-main-pine-v5",
            "state": "RUNNING",
            "health": "HEALTHY",
            "readiness": "READY",
            "reason": "WAITING_FOR_TRIGGER",
            "statistics": {"completed_trades": 3, "net_pnl": 125.5},
        }]
    }
    subject = service(tmp_path, runtime)
    version = next(row for row in subject.projection()["versions"] if row["strategy_id"] == "breakout-main-pine-v5")
    draft = subject.save_draft(strategy_id=version["strategy_id"], strategy_version=version["version"], configuration={"execution": {"enabled": True}})
    subject.deploy(draft["deployment_instance_id"], expected_configuration_hash=draft["configuration_hash"])
    projected = subject.projection()
    instance = projected["oracle_instances"][0]
    assert instance["runtime"]["source"] == "STRATEGY_LAB_RUNTIME"
    assert instance["analytics"]["completed_trades"] == 3
    assert instance["analytics"]["net_pnl"] == 125.5
    assert instance["analytics"]["attribution"]["deployment_instance_id"] == draft["deployment_instance_id"]
    assert instance["deployment_instance_id"] == draft["deployment_instance_id"]
    assert instance["configuration_hash"] == draft["configuration_hash"]


def test_multiple_instances_do_not_share_unattributed_runtime_or_analytics(tmp_path):
    runtime = {
        "strategies": [{
            "strategy_id": "breakout-main-pine-v5",
            "state": "RUNNING",
            "statistics": {"completed_trades": 9, "net_pnl": 999},
        }]
    }
    subject = service(tmp_path, runtime)
    version = next(
        row for row in subject.projection()["versions"]
        if row["strategy_id"] == "breakout-main-pine-v5"
    )
    instances = [
        subject.save_draft(
            strategy_id=version["strategy_id"],
            strategy_version=version["version"],
            deployment_instance_id=f"isolated_{index}",
            configuration=configuration,
        )
        for index, configuration in enumerate((
            {
                "market": {"instrument": "NIFTY"},
                "timeframes": {"roles": {role: ["3m"] for role in ("signal", "entry", "confirmation", "exit", "guardian")}},
                "position": {"fixed_lots": 1, "maximum_lots": 1},
                "execution": {"path": "ORACLE_PAPER"},
            },
            {
                "market": {"instrument": "NIFTY"},
                "timeframes": {"roles": {role: ["5m"] for role in ("signal", "entry", "confirmation", "exit", "guardian")}},
                "position": {"fixed_lots": 2, "maximum_lots": 2},
                "execution": {"path": "ORACLE_SHADOW"},
            },
            {
                "market": {"instrument": "BANKNIFTY"},
                "timeframes": {"roles": {role: ["15m"] for role in ("signal", "entry", "confirmation", "exit", "guardian")}},
                "execution": {"path": "WORKSPACE_OBSERVE"},
            },
        ))
    ]
    projected = subject.projection()["deployments"]
    assert {row["deployment_instance_id"] for row in projected} == {
        row["deployment_instance_id"] for row in instances
    }
    assert all(row["runtime"]["source"] == "STRATEGY_COMMAND_RUNTIME" for row in projected)
    assert all(row["analytics"]["status"] == "UNAVAILABLE" for row in projected)
    assert all(row["analytics"]["sample_size"] == 0 for row in projected)
    assert len({
        row["analytics"]["attribution"]["configuration_hash"]
        for row in projected
    }) == 3


@pytest.mark.parametrize(
    "failed_stage",
    ["VALIDATING", "SAVING_CONFIGURATION", "SYNCHRONIZING_RUNTIME", "HASH_VERIFICATION", "ACTIVATING"],
)
def test_every_atomic_deployment_stage_fails_without_partial_activation(tmp_path, failed_stage):
    target = {"stage": None}

    def fail(stage, _deployment):
        if stage == target["stage"]:
            raise RuntimeError(f"FORCED_{stage}")

    subject = service(tmp_path, failure_injector=fail)
    strategy_id, version = first_version(subject)
    active = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        configuration={"execution": {"enabled": True, "path": "ORACLE_SHADOW"}},
    )
    subject.deploy(active["deployment_instance_id"], expected_configuration_hash=active["configuration_hash"])
    previous_hash = active["configuration_hash"]
    edited = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        deployment_instance_id=active["deployment_instance_id"],
        configuration={"position": {"fixed_lots": 1, "maximum_lots": 2}},
    )
    target["stage"] = failed_stage
    with pytest.raises(RuntimeError, match=f"FORCED_{failed_stage}"):
        subject.deploy(edited["deployment_instance_id"], expected_configuration_hash=edited["configuration_hash"])
    restored = subject.projection()["deployments"][0]
    assert restored["configuration_hash"] == previous_hash
    assert restored["runtime_configuration_hash"] == previous_hash
    failure = next(
        row for row in reversed(subject.audit.read())
        if row["event_type"] == "DEPLOYMENT_FAILED_ROLLED_BACK"
    )
    assert failure["payload"]["failed_stage"] == failed_stage
    assert failure["payload"]["retry_available"] is True
    assert subject.projection()["notifications"][-1]["severity"] == "CRITICAL"


def test_pause_resume_receipt_notifications_and_restart_persist(tmp_path):
    subject = service(tmp_path)
    strategy_id, version = first_version(subject)
    draft = subject.save_draft(
        strategy_id=strategy_id,
        strategy_version=version,
        configuration={"execution": {"enabled": True, "path": "ORACLE_SHADOW"}},
    )
    receipt = subject.deploy(draft["deployment_instance_id"], expected_configuration_hash=draft["configuration_hash"])
    subject.pause(draft["deployment_instance_id"])
    subject.resume(draft["deployment_instance_id"])
    subject.record_runtime_event(
        draft["deployment_instance_id"],
        "STALE_DATA",
        details={"reason": "SOURCE_TIMESTAMP_STALE"},
        event_id="stale-1",
    )
    subject.record_runtime_event(
        draft["deployment_instance_id"],
        "SIGNAL_GENERATED",
        details={"signal_id": "signal-1"},
        event_id="signal-1",
    )
    subject.record_runtime_event(
        draft["deployment_instance_id"],
        "DAILY_RISK_LIMIT_REACHED",
        details={"remaining": 0},
        event_id="risk-1",
    )
    restarted = service(tmp_path)
    projection = restarted.projection()
    assert projection["deployments"][0]["configuration_hash"] == draft["configuration_hash"]
    assert projection["receipts"][0]["deployment_receipt_id"] == receipt["deployment_receipt_id"]
    messages = [row["message"] for row in projection["notifications"]]
    assert "Strategy runtime activated" in messages
    assert "Strategy paused by operator" in messages
    assert "Strategy resumed by operator" in messages
    assert "Stale Data" in messages
    assert "Signal Generated" in messages
    assert "Daily Risk Limit Reached" in messages


@pytest.mark.parametrize("context", [
    Context(),
    Context(bias="BEARISH", close=90, ema21=95, ema38=100),
    Context(bias="NEUTRAL"),
    Context(close=None),
])
def test_price_action_port_has_deterministic_oracle_development_parity(context):
    protected = SimplePullbackDevelopment().generate(context)
    ported = evaluate_price_action({
        "indicators": context.indicators,
        "kronos": context.kronos,
        "confidence": context.confidence,
    })
    assert ported == protected


def test_safety_and_oracle_development_boundary_are_explicit(tmp_path):
    projection = service(tmp_path).projection()
    assert projection["safety"] == {
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
        "new_strategies_auto_deployed": False,
        "oracle_development_mutated": False,
    }
    assert projection["price_action_reuse"]["runtime_dependency_on_oracle_development"] is False


def _deep_test_merge(left, right):
    result = deepcopy(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_test_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
