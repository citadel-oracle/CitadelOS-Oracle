"""Persistent scanner owns one canonical event path and never evaluates on UI reads."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.eye.kernel.runtime import EyeRuntime, PersistentEyeScanner


def _trend_context(candle_id: str):
    return {
        "candle_id": candle_id, "closed": True, "timestamp": "2026-08-10T09:45:00+05:30", "symbol": "NIFTY", "timeframe": "5m",
        "bar": {"index": 1, "timestamp": "2026-08-10T09:45:00+05:30", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
    }


def test_scanner_deduplicates_candle_and_persists_state(tmp_path):
    runtime = EyeRuntime(state_path=tmp_path / "scanner.json")
    current = _trend_context("NIFTY:5m:1")
    scanner = PersistentEyeScanner(runtime, context_provider=lambda: current)
    first = scanner.run_once()
    assert first["last_candle_id"] == "NIFTY:5m:1"
    duplicate = scanner.run_once()
    assert duplicate["duplicate_candles"] == 1
    assert (tmp_path / "scanner.json").exists()
    assert duplicate["execution_influence"] == "ZERO"
    runtime_snapshot = runtime.dependency_router.state_store
    assert runtime_snapshot.get_state("S02")["authority_state"] == "MISSING_DATA"
    assert runtime_snapshot.get_state("S06")["authority_state"] == "MISSING_DATA"


def test_scanner_forwards_only_a_prepublished_canonical_strategy_envelope(tmp_path):
    runtime = EyeRuntime(state_path=tmp_path / "scanner.json")
    current = _trend_context("NIFTY:5m:2")
    current["strategy_contexts"] = {
        "S02": {
            "timestamp": current["timestamp"],
            "fresh": True,
            "completed": True,
            "decision_candle_id": "futures:5m:2",
            "nearest_200_contracts": {"CE": {"security_id": "CE200"}, "PE": {"security_id": "PE200"}},
            "futures": {"close": 99.0, "bb_middle_5m": 100.0, "supertrend_15m_10_2": 101.0, "daily_cpr_s1": 100.0},
        },
    }
    scanner = PersistentEyeScanner(runtime, context_provider=lambda: current)

    scanner.run_once()

    assert runtime.dependency_router.state_store.get_state("S02")["authority_state"] == "DETECTED"
    # No source was published for S06: it remains explicit rather than being
    # inferred from S02's futures context.
    assert runtime.dependency_router.state_store.get_state("S06")["authority_state"] == "MISSING_DATA"


def _option_candle(index: int, *, side: str, security_id: str, bootstrap: bool = False):
    opened = datetime(2026, 8, 10, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(minutes=index)
    return {
        "timestamp": opened.isoformat(),
        "candle_closed_at": (opened + timedelta(minutes=1)).isoformat(),
        "received_at": (opened + timedelta(minutes=1)).isoformat(),
        "open": 100.0 + index * 0.1,
        "high": 101.0 + index * 0.1,
        "low": 99.0 + index * 0.1,
        "close": 100.2 + index * 0.1,
        "volume": 100.0,
        "closed": True,
        "is_closed": True,
        "contract": security_id,
        "chart_contract": {"security_id": security_id, "option_type": side},
        "bootstrap": bootstrap,
    }


def test_all_six_strategies_share_one_kernel_without_duplicate_evaluations(tmp_path):
    runtime = EyeRuntime(state_path=tmp_path / "all-six.json")
    scanner_context = _trend_context("NIFTY:5m:all-six")
    scanner_context["strategy_contexts"] = {
        "S02": {
            "timestamp": scanner_context["timestamp"], "fresh": True, "completed": True,
            "decision_candle_id": "futures:all-six",
            "nearest_200_contracts": {"CE": {"security_id": "CE200"}, "PE": {"security_id": "PE200"}},
            "futures": {"close": 99.0, "bb_middle_5m": 100.0, "supertrend_15m_10_2": 101.0, "daily_cpr_s1": 100.0},
        },
        "S03": dict(scanner_context),
        "S04": dict(scanner_context),
    }
    scanner = PersistentEyeScanner(runtime, context_provider=lambda: scanner_context)

    ce_history = [_option_candle(index, side="CE", security_id="CE-EXACT") for index in range(120)]
    pe_history = [_option_candle(index, side="PE", security_id="PE-EXACT") for index in range(120)]
    runtime.hydrate_option_history(ce_history)
    runtime.hydrate_option_history(pe_history)
    # The historical cache is canonical input; these values model genuine
    # prior-session H/L/C already supplied by that cache, not strategy defaults.
    runtime.feature_store.set_prev_day_stats("CE-EXACT", 130.0, 90.0, 110.0)
    runtime.feature_store.set_prev_day_stats("PE-EXACT", 130.0, 90.0, 110.0)

    scanner.run_once()  # S02/S03/S04/S06 route once from the completed context.
    for index in range(120, 125):
        assert runtime.ingest_option_candle(_option_candle(index, side="CE", security_id="CE-EXACT"))
        runtime.kernel.process_cycle()
        assert runtime.ingest_option_candle(_option_candle(index, side="PE", security_id="PE-EXACT"))
        runtime.kernel.process_cycle()

    # Every strategy received the shared kernel's completed-candle path.  Some
    # legitimate option bars close both a 3m and 5m aggregation, so the count
    # is deliberately captured after canonical work rather than hard-coding a
    # number that would confuse valid multi-timeframe evaluations with dupes.
    evaluations_after_canonical_events = runtime.dependency_router.evaluation_count
    assert evaluations_after_canonical_events >= 6
    scanner.run_once()
    assert runtime.dependency_router.evaluation_count == evaluations_after_canonical_events
    assert scanner.status()["duplicate_candles"] == 1
    assert not runtime.ingest_option_candle(_option_candle(124, side="CE", security_id="CE-EXACT"))
    runtime.kernel.process_cycle()
    assert runtime.dependency_router.evaluation_count == evaluations_after_canonical_events
    assert runtime.kernel.bus.telemetry()["duplicate_event_rejects"] >= 0
    states = runtime.dependency_router.state_store._states
    assert states["S01"]["locked_contract"] == "CE-EXACT"
    assert states["S05_CE"]["locked_contract"] == "CE-EXACT"
    assert states["S05_PE"]["locked_contract"] == "PE-EXACT"
    for state_id in ("S02", "S03", "S04", "S06"):
        assert "evaluator_state" in states[state_id]


def test_scanner_restart_restores_s02_cycle_without_rearming_or_duplicate_branch(tmp_path):
    state_path = tmp_path / "restart.json"
    first_context = _trend_context("NIFTY:5m:restart-1")
    s02_context = {
        "timestamp": first_context["timestamp"], "fresh": True, "completed": True,
        "decision_candle_id": "futures:restart-1",
        "nearest_200_contracts": {"CE": {"security_id": "CE200"}, "PE": {"security_id": "PE200"}},
        "futures": {"close": 99.0, "bb_middle_5m": 100.0, "supertrend_15m_10_2": 101.0, "daily_cpr_s1": 100.0},
    }
    first_context["strategy_contexts"] = {"S02": s02_context}
    first_runtime = EyeRuntime(state_path=state_path)
    PersistentEyeScanner(first_runtime, context_provider=lambda: first_context).run_once()
    assert first_runtime.dependency_router.state_store.get_state("S02")["evaluator_state"]["stage"] == "STAGE1_ACTIVE"

    second_context = _trend_context("NIFTY:5m:restart-2")
    second_context["strategy_contexts"] = {
        "S02": {
            **s02_context,
            "timestamp": "2026-08-10T09:50:00+05:30",
            "stage1_outcome": {"result": "LOSS", "decision_candle_id": "futures:restart-1"},
        }
    }
    restarted_runtime = EyeRuntime(state_path=state_path)
    restarted_scanner = PersistentEyeScanner(restarted_runtime, context_provider=lambda: second_context)
    restarted_scanner.run_once()
    state = restarted_runtime.dependency_router.state_store.get_state("S02")
    assert state["evaluator_state"]["stage"] == "STAGE2_ACTIVE"
    assert state["evaluator_state"]["branch"] == "STAGE2"
    evaluations = restarted_runtime.dependency_router.evaluation_count
    restarted_scanner.run_once()
    assert restarted_runtime.dependency_router.evaluation_count == evaluations
