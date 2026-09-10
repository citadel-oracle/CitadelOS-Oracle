"""Deterministic completion coverage for source-resolved personal strategies."""

from __future__ import annotations

from src.eye.personal_strategies.contracts import StrategyLifecycleState
from src.eye.personal_strategies.strategies.s02_nifty_volatile import S02Evaluator
from src.eye.personal_strategies.strategies.s03_trend_catcher import S03Evaluator
from src.eye.personal_strategies.strategies.s04_bull_pulse import S04Evaluator
from src.eye.personal_strategies.strategies.s06_opening_momentum_recovery import S06Evaluator


def _s02_context(**overrides):
    value = {
        "timestamp": "2026-08-07T10:00:00+05:30", "fresh": True, "completed": True,
        "decision_candle_id": "fut-5m-1",
        "nearest_200_contracts": {"CE": {"security_id": "CE200"}, "PE": {"security_id": "PE200"}},
        "futures": {"close": 99.0, "bb_middle_5m": 100.0, "supertrend_15m_10_2": 101.0, "daily_cpr_s1": 100.0},
    }
    value.update(overrides)
    return value


def test_s02_stage4_is_the_only_stage2_alternative_and_is_latched():
    s02 = S02Evaluator()
    stage1 = s02.evaluate(context=_s02_context())
    assert stage1.state == StrategyLifecycleState.DETECTED
    assert stage1.direction == "BUY_PE"
    assert stage1.informational_targets["lots"] == 1
    stage2 = s02.evaluate(context=_s02_context(stage1_outcome={"result": "LOSS", "decision_candle_id": "fut-5m-1"}))
    assert stage2.direction == "BUY_CE"
    assert stage2.informational_targets == {"target_points": 25.0, "lots": 2, "trailing_trigger": 10.0, "trailing_step": 10.0}
    # A later cross cannot switch an already-latched Stage-2 branch into Stage 4.
    later = s02.evaluate(context=_s02_context(timestamp="2026-08-07T10:05:00+05:30", decision_candle_id="fut-5m-2", futures={**_s02_context()["futures"], "fresh_cross_below_daily_cpr_s1": True}, stage1_outcome={"result": "LOSS", "decision_candle_id": "fut-5m-2"}))
    assert later.direction == "BUY_CE"
    assert s02.state.branch == "STAGE2"

    alternate = S02Evaluator()
    alternate.evaluate(context=_s02_context())
    stage4 = alternate.evaluate(context=_s02_context(futures={**_s02_context()["futures"], "fresh_cross_below_daily_cpr_s1": True}, stage1_outcome={"result": "LOSS", "decision_candle_id": "fut-5m-1"}))
    assert stage4.direction == "BUY_PE"
    assert stage4.informational_targets == {"target_points": 25.0, "lots": 2, "trailing_trigger": 15.0, "trailing_step": 15.0}
    assert alternate.state.branch == "STAGE4"


def test_s02_stage3_requires_stage2_loss_and_fresh_3m_cross():
    evaluator = S02Evaluator()
    evaluator.evaluate(context=_s02_context())
    evaluator.evaluate(context=_s02_context(stage1_outcome={"result": "LOSS", "decision_candle_id": "fut-5m-1", "fresh_cross_below_daily_cpr_s1": False}))
    no_cross = evaluator.evaluate(context=_s02_context(stage2_outcome={"result": "LOSS"}))
    assert no_cross.state == StrategyLifecycleState.PARTIAL
    stage3 = evaluator.evaluate(context=_s02_context(futures={**_s02_context()["futures"], "fresh_cross_above_3m_supertrend_10_2": True}, stage2_outcome={"result": "LOSS"}))
    assert stage3.direction == "BUY_CE"
    assert stage3.informational_targets["exit"] == "FUTURES_3M_ST_10_2_CROSS_BELOW"


def _native_context(expiry: str, side: str, timestamp: str, index: int, ltp: float):
    strikes = [24400.0, 24450.0, 24500.0] if side == "PE" else [24500.0, 24550.0, 24600.0]
    strike = strikes[0] if side == "PE" else strikes[-1]
    option = {"security_id": f"SEC-{side}", "trading_symbol": f"NIFTY-{side}", "ltp": ltp}
    return {
        "bar": {"timestamp": timestamp, "index": index}, "lot_size": 50,
        "argus": {"data": {"underlying": {"expiry": expiry, "atm_strike": 24500.0}, "atm_window": [{"strike": value, side.lower(): option if value == strike else {"security_id": f"ATM-{side}-{value}", "trading_symbol": f"ATM-{side}-{value}", "ltp": ltp}} for value in strikes]}},
    }


def test_s03_and_s04_delegate_to_native_momentum_engines():
    s03 = S03Evaluator()
    first_s03 = s03.evaluate(context=_native_context("2026-08-11", "PE", "2026-08-10T09:45:00+05:30", 1, 100.0))
    second_s03 = s03.evaluate(context=_native_context("2026-08-11", "PE", "2026-08-10T09:46:00+05:30", 2, 140.0))
    assert first_s03.state == StrategyLifecycleState.SCANNING
    assert second_s03.state == StrategyLifecycleState.DETECTED
    assert second_s03.direction == "BUY_PE"

    s04 = S04Evaluator()
    first_s04 = s04.evaluate(context=_native_context("2026-08-07", "CE", "2026-08-03T10:30:00+05:30", 1, 100.0))
    second_s04 = s04.evaluate(context=_native_context("2026-08-07", "CE", "2026-08-03T10:31:00+05:30", 2, 110.0))
    assert first_s04.state == StrategyLifecycleState.SCANNING
    assert second_s04.state == StrategyLifecycleState.DETECTED
    assert second_s04.direction == "BUY_CE"


def test_s06_uses_canonical_probable_flow_without_a_200_fallback():
    bars = [{"open": 100.0, "high": 100 + index * 2.0, "low": 99.0, "close": 100 + index * 2.0} for index in range(15)]
    context = {
        "timestamp": "2026-08-07T10:00:00+05:30", "fresh": True, "completed": True,
        "flow_rows": [{"option_type": "CE", "fresh": True, "probable_flow": "CALL_BUYING"} for _ in range(2)],
        "contract_candidates": {"CE": [{"eligible": True, "security_id": "CE-OTM1"}], "PE": []},
        "bars_1m": {"CE": bars, "PE": bars}, "previous_close": {"CE": 110.0, "PE": 110.0},
        "session_open": {"CE": 100.0, "PE": 100.0},
        "guardian_risk_approved": True,
    }
    signal = S06Evaluator().evaluate(context=context)
    assert signal.state == StrategyLifecycleState.DETECTED
    assert signal.preferred_contract == "CE-OTM1"
    assert signal.structural_sl is not None
    assert signal.entry_band["low"] != 180.0


def test_s06_requires_the_authoritative_session_open_for_mode_a():
    bars = [{"open": 100.0, "high": 102.0, "low": 99.0, "close": 102.0} for _ in range(15)]
    context = {
        "timestamp": "2026-08-07T10:00:00+05:30", "fresh": True, "completed": True,
        "flow_rows": [{"option_type": "CE", "fresh": True, "probable_flow": "CALL_BUYING"} for _ in range(2)],
        "contract_candidates": {"CE": [{"eligible": True, "security_id": "CE-OTM1"}]},
        "bars_1m": {"CE": bars}, "previous_close": {"CE": 110.0},
    }
    signal = S06Evaluator().evaluate(context=context)
    assert signal.state == StrategyLifecycleState.MISSING_DATA
    assert signal.blocker == "S06_CANONICAL_CONTEXT_INCOMPLETE"
