from __future__ import annotations

from pathlib import Path

from src.strategy_command.edge_lab import ArgusEdgeLab, DEFINITIONS
from src.strategy_command.service import StrategyCommandService


def _snapshot(snapshot_id: str = "snapshot-live-001") -> dict:
    return {
        "data": {
            "atm_window": [{
                "strike": 24300,
                "ce": {
                    "security_id": "99901",
                    "ltp": 100,
                    "top_ask_price": 100,
                    "top_bid_price": 99.5,
                },
                "pe": {
                    "security_id": "99902",
                    "ltp": 100,
                    "top_ask_price": 100,
                    "top_bid_price": 99.5,
                },
            }],
            "tactical_edge": {
                "expiry": "2026-08-04",
                "chain_snapshot_id": snapshot_id,
                "argus_prime": {
                    "snapshot_id": snapshot_id,
                    "direction": "CALL",
                    "data_truth": {
                        "state": "LIVE",
                        "source_timestamp": "2026-07-29T10:00:00+05:30",
                        "expiry": "2026-08-04",
                    },
                    "outcome_engines": {
                        "call_edge": {"display_score": 82},
                        "put_edge": {"display_score": 41},
                        "decay_risk": {"display_score": 20},
                        "reversal": {"display_score": 18},
                        "big_move": {"display_score": 78},
                        "hold_edge": {"display_score": 20},
                    },
                    "full_evidence": {
                        "persistence": {"consecutive_confirmations": 4},
                    },
                    "best_strike_stack": {
                        "score": 88,
                        "structural_strength": {"score": 88},
                        "trade_readiness": {"score": 84},
                        "wall": {"condition": "WEAKENING"},
                        "authorized_contract": True,
                        "authorized_contract_detail": {
                            "security_id": "99901",
                            "trading_symbol": "NIFTY-20260804-24300-CE",
                            "option_type": "CE",
                            "expiry": "2026-08-04",
                            "strike": 24300,
                            "ltp": 100,
                            "ask": 100,
                            "bid": 99.5,
                            "lot_size": 75,
                            "contract_quality": 90,
                        },
                    },
                    "selected_contract_technicals": {
                        "pullback_state": "PULLBACK_CONFIRMED",
                        "invalidation": 90,
                        "targets": [120, 130],
                    },
                },
            },
        },
    }


def _put_snapshot(snapshot_id: str = "snapshot-put-001") -> dict:
    value = _snapshot(snapshot_id)
    prime = value["data"]["tactical_edge"]["argus_prime"]
    prime["direction"] = "PUT"
    prime["outcome_engines"]["call_edge"]["display_score"] = 35
    prime["outcome_engines"]["put_edge"]["display_score"] = 84
    contract = prime["best_strike_stack"]["authorized_contract_detail"]
    contract.update({
        "security_id": "99902",
        "trading_symbol": "NIFTY-20260804-24200-PE",
        "option_type": "PE",
        "strike": 24200,
    })
    value["data"]["atm_window"][0]["strike"] = 24200
    prime["best_strike_stack"]["direction"] = "PUT"
    return value


def test_registers_ten_immutable_definitions_and_evaluates_one_snapshot_once(tmp_path: Path):
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(
        tmp_path / "edge",
        registry=registry,
        snapshot_provider=_snapshot,
        clock=lambda: __import__("datetime").datetime.fromisoformat("2026-07-29T04:30:00+00:00"),
    )

    first = lab.evaluate_once()
    second = lab.evaluate_once()

    assert len(DEFINITIONS) == 10
    registry_projection = registry.projection()
    assert len([row for row in registry_projection["definitions"] if row["family"] == "ARGUS APEX OPTION BUYER"]) == 10
    assert len([row for row in registry_projection["deployments"] if row["strategy_id"].startswith("ARGUS_APEX_")]) == 10
    assert first == second
    assert first["snapshot_id"] == "snapshot-live-001"
    assert first["summary"]["strategies"] == 10
    assert first["summary"]["total_experiment_capital"] == 1_000_000
    assert len(first["lanes"]["CALL"]) == 5
    assert len(first["lanes"]["PUT"]) == 5
    assert first["lanes"]["CALL"][0]["runtime_state"] == "IN_POSITION"
    assert first["lanes"]["CALL"][0]["portfolio"]["open_position"] is not None
    assert first["lanes"]["PUT"][0]["portfolio"]["open_position"] is None
    assert all(row["portfolio"]["initial_capital"] == 100_000 for row in first["lanes"]["CALL"] + first["lanes"]["PUT"])
    assert all(row["portfolio"]["maximum_lots"] == 1 for row in first["lanes"]["CALL"] + first["lanes"]["PUT"])
    assert lab.market_stream.verify()["valid"] is True
    assert lab.evaluation_stream.verify()["valid"] is True
    assert len(lab.market_stream.read()) == 1
    assert len(lab.evaluation_stream.read()) == 10
    assert len(lab.trigger_stream.read()) == 10
    assert first["safety"] == {
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
        "execution_influence": "ZERO",
    }


def test_stale_snapshot_never_creates_paper_order(tmp_path: Path):
    stale = _snapshot("snapshot-stale")
    stale["data"]["tactical_edge"]["argus_prime"]["data_truth"]["state"] = "STALE"
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=lambda: stale)

    projection = lab.evaluate_once()

    assert projection["status"] == "DATA_STALE"
    assert all(row["runtime_state"] == "DATA_STALE" for row in projection["lanes"]["CALL"] + projection["lanes"]["PUT"])
    assert all(row["analytics"]["completed_trades"] == 0 for row in projection["lanes"]["CALL"] + projection["lanes"]["PUT"])
    assert all(row["portfolio"]["open_position"] is None for row in projection["lanes"]["CALL"] + projection["lanes"]["PUT"])


def test_thresholds_and_configuration_hashes_are_side_symmetric():
    call = {row.variant: row for row in DEFINITIONS if row.side == "CALL"}
    put = {row.variant: row for row in DEFINITIONS if row.side == "PUT"}
    assert set(call) == set(put)
    for variant in call:
        left = call[variant]
        right = put[variant]
        assert (
            left.edge_min,
            left.separation_min,
            left.structure_min,
            left.readiness_min,
            left.persistence_min,
            left.reversal_max,
            left.decay_max,
            left.big_move_min,
            left.wall_reversal,
        ) == (
            right.edge_min,
            right.separation_min,
            right.structure_min,
            right.readiness_min,
            right.persistence_min,
            right.reversal_max,
            right.decay_max,
            right.big_move_min,
            right.wall_reversal,
        )
        assert left.configuration_hash != right.configuration_hash
    assert (call["SIMPLE"].edge_min, call["SIMPLE"].structure_min, call["SIMPLE"].separation_min, call["SIMPLE"].decay_max, call["SIMPLE"].reversal_max, call["SIMPLE"].contract_quality_min) == (48, 60, 8, 65, 55, 60)
    assert (call["BALANCED"].edge_min, call["BALANCED"].structure_min, call["BALANCED"].separation_min, call["BALANCED"].readiness_min, call["BALANCED"].hold_max, call["BALANCED"].decay_max, call["BALANCED"].reversal_max, call["BALANCED"].big_move_min) == (55, 70, 12, 35, 60, 55, 45, 35)
    assert (call["STRICT"].edge_min, call["STRICT"].structure_min, call["STRICT"].separation_min, call["STRICT"].readiness_min, call["STRICT"].hold_max, call["STRICT"].decay_max, call["STRICT"].reversal_max, call["STRICT"].big_move_min) == (62, 78, 18, 50, 48, 45, 35, 45)
    assert (call["BIG_MOVE_ESCAPE"].edge_min, call["BIG_MOVE_ESCAPE"].structure_min, call["BIG_MOVE_ESCAPE"].separation_min, call["BIG_MOVE_ESCAPE"].big_move_min, call["BIG_MOVE_ESCAPE"].decay_max, call["BIG_MOVE_ESCAPE"].reversal_max) == (58, 72, 14, 60, 55, 40)
    assert (call["WALL_REVERSAL"].edge_min, call["WALL_REVERSAL"].structure_min, call["WALL_REVERSAL"].decay_max, call["WALL_REVERSAL"].wall_reversal) == (50, 65, 55, True)


def test_put_lane_is_independent_and_restart_restores_without_duplicate_fill(tmp_path: Path):
    registry = StrategyCommandService(tmp_path / "registry")
    first = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=_put_snapshot)
    projection = first.evaluate_once()
    put_simple = projection["lanes"]["PUT"][0]
    call_simple = projection["lanes"]["CALL"][0]
    assert put_simple["runtime_state"] == "IN_POSITION"
    assert call_simple["portfolio"]["open_position"] is None
    fills_before = first._engines["ARGUS_APEX_P1_SIMPLE"].projection()["fills"]

    restored = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=_put_snapshot)
    repeated = restored.evaluate_once()
    fills_after = restored._engines["ARGUS_APEX_P1_SIMPLE"].projection()["fills"]

    assert repeated["snapshot_id"] == projection["snapshot_id"]
    assert fills_after == fills_before
    assert len(fills_after) == 1


def test_one_lot_risk_cap_rejects_without_order(tmp_path: Path):
    value = _snapshot("snapshot-risk")
    value["data"]["tactical_edge"]["argus_prime"]["selected_contract_technicals"]["invalidation"] = 50
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=lambda: value)

    projection = lab.evaluate_once()
    simple = projection["lanes"]["CALL"][0]

    assert simple["runtime_state"] == "RISK_BLOCKED"
    assert simple["execution"]["reason"] == "ONE_LOT_STRUCTURAL_RISK_EXCEEDS_1000"
    assert lab._engines["ARGUS_APEX_C1_SIMPLE"].projection()["orders"] == []


def test_big_move_requires_canonical_breadth_acceleration_and_breakout(tmp_path: Path):
    value = _snapshot("snapshot-escape")
    prime = value["data"]["tactical_edge"]["argus_prime"]
    prime["selected_contract_technicals"]["pullback_state"] = "BREAKOUT_CONFIRMED"
    prime["best_strike_stack"]["primary_flow"] = {"arrow": "↑↑"}
    prime["best_strike_stack"]["wall"] = {"condition": "ESCAPE"}
    prime["pressure_price_state"] = "EXPANDING"
    prime["full_evidence"]["breadth"] = {"direction": "CALL"}
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=lambda: value)

    projection = lab.evaluate_once()
    escape = next(row for row in projection["lanes"]["CALL"] if row["variant"] == "BIG_MOVE_ESCAPE")

    assert escape["runtime_state"] == "IN_POSITION"
    assert "OI_ACCELERATION_NOT_STRONG" not in escape["rejection_reasons"]
    assert "FLOW_BREADTH_NOT_ALIGNED" not in escape["rejection_reasons"]


def test_daily_report_remains_insufficient_and_definitions_are_non_causal(tmp_path: Path):
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=_snapshot)
    projection = lab.evaluate_once()

    assert projection["report"]["status"] == "INSUFFICIENT_SAMPLE"
    assert projection["report"]["winner_policy"] == "INSUFFICIENT_SAMPLE_UNTIL_20_SESSIONS_AND_30_TRADES"
    assert projection["report"]["score_is_probability"] is False
    assert projection["report"]["metric_definitions"]["false_trigger"] == "INVALIDATION_BEFORE_PLUS_0_5R"
    assert projection["report"]["metric_definitions"]["missed_move"] == "REJECTED_EXECUTABLE_REACHES_PLUS_1_5R_FIRST"
    assert projection["persistence"]["market_snapshots"].endswith("market_snapshots.jsonl")
    assert projection["persistence"]["forward_outcomes"].endswith("forward_outcomes.jsonl")


def test_common_guardian_data_safety_exit_uses_authoritative_bid(tmp_path: Path):
    snapshots = [_snapshot("snapshot-entry"), _snapshot("snapshot-exit")]
    snapshots[1]["data"]["tactical_edge"]["argus_prime"]["data_truth"].update({
        "state": "STALE",
        "source_timestamp": "2026-07-29T10:03:00+05:30",
    })
    snapshots[1]["data"]["atm_window"][0]["ce"].update({
        "ltp": 96,
        "top_ask_price": 96.5,
        "top_bid_price": 95.5,
    })
    registry = StrategyCommandService(tmp_path / "registry")
    lab = ArgusEdgeLab(tmp_path / "edge", registry=registry, snapshot_provider=lambda: snapshots[0])

    lab.evaluate_once(snapshots[0])
    exited = lab.evaluate_once(snapshots[1])
    engine = lab._engines["ARGUS_APEX_C1_SIMPLE"].projection()

    assert exited["lanes"]["CALL"][0]["portfolio"]["open_position"] is None
    assert len(engine["closed_trades"]) == 1
    assert engine["closed_trades"][0]["exit_reason"] == "DATA_SAFETY_EXIT"
    assert engine["closed_trades"][0]["exit"] <= 95.5
