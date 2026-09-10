import pytest
from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from src.strategy_lab.strategies.trend_catcher import (
    TrendCatcherConfig,
    TrendCatcherState,
    TrendCatcherStrategyEngine,
)

KOLKATA = ZoneInfo("Asia/Kolkata")


def make_context(
    dt_str: str,
    index: int,
    spot: float,
    expiry_str: str,
    atm_strike: float,
    pe_ltp: float,
    lot_size: int = 50,
) -> dict:
    """Helper to construct context matching Strategy Lab completed candle format."""
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=KOLKATA)
    return {
        "timestamp": dt.isoformat(),
        "lot_size": lot_size,
        "bar": {
            "index": index,
            "timestamp": dt.isoformat(),
            "open": spot,
            "high": spot,
            "low": spot,
            "close": spot,
            "volume": 1000.0,
            "confirmed": True,
        },
        "argus": {
            "status": "available",
            "data": {
                "underlying": {
                    "symbol": "NIFTY",
                    "expiry": expiry_str,
                    "atm_strike": atm_strike,
                    "ltp": spot,
                    "fetched_at": dt.isoformat(),
                },
                "atm_window": [
                    {
                        "strike": atm_strike - 100,
                        "pe": {
                            "security_id": 10001,
                            "trading_symbol": f"NIFTY{expiry_str}{int(atm_strike-100)}PE",
                            "ltp": pe_ltp,
                        },
                    },
                    {
                        "strike": atm_strike - 50,
                        "pe": {"security_id": 10002, "ltp": pe_ltp + 25},
                    },
                    {
                        "strike": atm_strike,
                        "pe": {"security_id": 10003, "ltp": pe_ltp + 50},
                    },
                ],
            },
        },
    }


def test_trend_catcher_dte_eligibility():
    engine = TrendCatcherStrategyEngine()
    
    # Thursday expiry, Wednesday trading day (DTE == 1) -> eligible
    ctx_eligible = make_context("2026-07-22T09:35:00", 1, 24000.0, "2026-07-23", 24000.0, 100.0)
    res = engine.evaluate(ctx_eligible)
    assert res["status"] == "WAIT"
    assert res["reason"] == "MOMENTUM_NOT_ALIGNED"
    
    # Thursday expiry, Tuesday trading day (DTE == 2) -> ineligible
    ctx_ineligible = make_context("2026-07-21T09:35:00", 2, 24000.0, "2026-07-23", 24000.0, 100.0)
    res2 = engine.evaluate(ctx_ineligible)
    assert res2["status"] == "UNAVAILABLE"
    assert res2["reason"] == "STRATEGY_INELIGIBLE_DTE"


def test_trend_catcher_holiday_shifted_expiry():
    # If Wednesday is the holiday, Thursday expiry shifts to Wednesday.
    # On Tuesday (Wednesday - 1 day), DTE == 1, so it is eligible!
    engine = TrendCatcherStrategyEngine()
    ctx = make_context("2026-07-21T09:35:00", 1, 24000.0, "2026-07-22", 24000.0, 100.0)
    res = engine.evaluate(ctx)
    assert res["status"] == "WAIT"
    assert res["reason"] == "MOMENTUM_NOT_ALIGNED"
    assert engine.state.dte == 1


def test_trend_catcher_strike_resolution():
    engine = TrendCatcherStrategyEngine()
    ctx = make_context("2026-07-22T09:35:00", 1, 24000.0, "2026-07-23", 24000.0, 120.0)
    res = engine.evaluate(ctx)
    assert res["option_contract"]["strike"] == 23900.0  # ATM (24000) - 2 * interval (50)
    assert res["option_contract"]["security_id"] == 10001


def test_trend_catcher_momentum_boundaries():
    engine = TrendCatcherStrategyEngine()
    
    # Initial bar sets reference premium to 100.0
    ctx_ref = make_context("2026-07-22T09:35:00", 1, 24000.0, "2026-07-23", 24000.0, 100.0)
    engine.evaluate(ctx_ref)
    assert engine.state.reference_premium == 100.0
    assert engine.state.entry_trigger_status is False

    # Next bar premium goes to 139.0 (Below 40% trigger)
    ctx_below = make_context("2026-07-22T09:36:00", 2, 24000.0, "2026-07-23", 24000.0, 139.0)
    res_below = engine.evaluate(ctx_below)
    assert res_below["status"] == "WAIT"
    assert engine.state.entry_trigger_status is False

    # Next bar premium goes to 140.0 (Exactly 40% trigger)
    ctx_trigger = make_context("2026-07-22T09:37:00", 3, 24000.0, "2026-07-23", 24000.0, 140.0)
    res_trigger = engine.evaluate(ctx_trigger)
    assert res_trigger["status"] == "ENTRY_CANDIDATE"
    assert res_trigger["signal"] == "BUY"
    assert engine.state.entry_trigger_status is True
    assert engine.state.theoretical_entry_price == 140.0
    assert engine.state.active_leg_stop == 110.0  # 140 - 30 SL


def test_trend_catcher_fixed_sl_exit():
    engine = TrendCatcherStrategyEngine()
    
    # Onboard position at 100.0 entry (reference 71.4)
    engine.state.session_date = "2026-07-22"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_premium = 100.0
    engine.state.active_leg_stop = 70.0  # 100 - 30 SL
    engine.state.selected_contract = {"security_id": 10001, "strike": 23900.0, "expiry": "2026-07-23"}

    # Premium falls to 71.0 (above stop)
    ctx_above = make_context("2026-07-22T09:36:00", 2, 24000.0, "2026-07-23", 24000.0, 71.0, lot_size=20)
    res_above = engine.evaluate(ctx_above)
    assert res_above["status"] == "HOLD"

    # Premium hits 70.0
    ctx_stop = make_context("2026-07-22T09:37:00", 3, 24000.0, "2026-07-23", 24000.0, 70.0, lot_size=20)
    res_stop = engine.evaluate(ctx_stop)
    assert res_stop["status"] == "EXIT_CANDIDATE"
    assert res_stop["signal"] == "SELL"
    assert res_stop["reason"] == "LEG_STOP_LOSS_HIT"
    assert engine.state.entry_trigger_status is False
    assert engine.state.terminal_session_state is True


def test_trend_catcher_trailing_stop():
    engine = TrendCatcherStrategyEngine()
    
    # Entry at 100.0, stop at 70.0
    engine.state.session_date = "2026-07-22"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_premium = 100.0
    engine.state.active_leg_stop = 70.0
    engine.state.selected_contract = {"security_id": 10001, "strike": 23900.0, "expiry": "2026-07-23"}

    # Premium rises to 109.0 (No step completed yet)
    ctx1 = make_context("2026-07-22T09:36:00", 2, 24000.0, "2026-07-23", 24000.0, 109.0)
    engine.evaluate(ctx1)
    assert engine.state.active_leg_stop == 70.0

    # Premium rises to 110.0 (1 step completed, SL moves to 80)
    ctx2 = make_context("2026-07-22T09:37:00", 3, 24000.0, "2026-07-23", 24000.0, 110.0)
    engine.evaluate(ctx2)
    assert engine.state.active_leg_stop == 80.0

    # Premium drops to 105.0 (SL remains at 80)
    ctx3 = make_context("2026-07-22T09:38:00", 4, 24000.0, "2026-07-23", 24000.0, 105.0)
    engine.evaluate(ctx3)
    assert engine.state.active_leg_stop == 80.0

    # Premium rises to 121.0 (2 steps completed, SL moves to 90)
    ctx4 = make_context("2026-07-22T09:39:00", 5, 24000.0, "2026-07-23", 24000.0, 121.0)
    engine.evaluate(ctx4)
    assert engine.state.active_leg_stop == 90.0


def test_trend_catcher_lock_profit():
    engine = TrendCatcherStrategyEngine()
    
    # Entry at 100.0, lot size 50. 
    # SL is at 70.0. Lock profit triggers when P&L >= 1000 (premium >= 120.0).
    engine.state.session_date = "2026-07-22"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_premium = 100.0
    engine.state.active_leg_stop = 70.0
    engine.state.selected_contract = {"security_id": 10001, "strike": 23900.0, "expiry": "2026-07-23"}

    # Premium hits 120.0 (PnL = (120-100)*50 = 1000). Lock floor of 500 profit (premium 110.0) is set.
    ctx_lock = make_context("2026-07-22T09:36:00", 2, 24000.0, "2026-07-23", 24000.0, 120.0)
    engine.evaluate(ctx_lock)
    assert engine.state.active_overall_locked_profit_floor == 500.0

    # Premium falls to 110.1 (PnL = 505.0) -> HOLD
    ctx_hold = make_context("2026-07-22T09:37:00", 3, 24000.0, "2026-07-23", 24000.0, 110.1)
    res_hold = engine.evaluate(ctx_hold)
    assert res_hold["status"] == "HOLD"

    # Premium hits 110.0 (PnL = 500.0) -> Exits under lock profit trigger
    ctx_exit = make_context("2026-07-22T09:38:00", 4, 24000.0, "2026-07-23", 24000.0, 110.0)
    res_exit = engine.evaluate(ctx_exit)
    assert res_exit["status"] == "EXIT_CANDIDATE"
    assert res_exit["reason"] == "OVERALL_LOCKED_PROFIT_TRIGGERED"
    assert res_exit["pnl"] == 500.0


def test_trend_catcher_forced_exit():
    engine = TrendCatcherStrategyEngine()
    engine.state.session_date = "2026-07-22"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_premium = 100.0
    engine.state.active_leg_stop = 70.0
    engine.state.selected_contract = {"security_id": 10001, "strike": 23900.0, "expiry": "2026-07-23"}

    # Time reaches 15:15:00
    ctx_exit = make_context("2026-07-22T15:15:00", 200, 24000.0, "2026-07-23", 24000.0, 95.0)
    res_exit = engine.evaluate(ctx_exit)
    assert res_exit["status"] == "EXIT_CANDIDATE"
    assert res_exit["reason"] == "FORCED_SQUARE_OFF"
    assert res_exit["pnl"] == -250.0  # (95-100)*50


def test_trend_catcher_single_entry_idempotency():
    engine = TrendCatcherStrategyEngine()
    
    # 09:35 Bar sets reference
    ctx1 = make_context("2026-07-22T09:35:00", 1, 24000.0, "2026-07-23", 24000.0, 100.0)
    engine.evaluate(ctx1)
    
    # 09:36 Bar triggers trade
    ctx2 = make_context("2026-07-22T09:36:00", 2, 24000.0, "2026-07-23", 24000.0, 140.0)
    res2 = engine.evaluate(ctx2)
    assert res2["status"] == "ENTRY_CANDIDATE"
    
    # Re-sending 09:36 Bar must be ignored (idempotent)
    res_dup = engine.evaluate(ctx2)
    assert res_dup["status"] == "WAIT"
    assert res_dup["reason"] == "BAR_ALREADY_EVALUATED"


def test_trend_catcher_serialization():
    engine = TrendCatcherStrategyEngine()
    ctx1 = make_context("2026-07-22T09:35:00", 1, 24000.0, "2026-07-23", 24000.0, 100.0)
    engine.evaluate(ctx1)
    
    # Serialize state
    serialized = engine.serialize()
    
    # Restore state on a new engine
    restored_engine = TrendCatcherStrategyEngine.deserialize(serialized)
    assert restored_engine.state.reference_premium == 100.0
    assert restored_engine.state.session_date == "2026-07-22"
