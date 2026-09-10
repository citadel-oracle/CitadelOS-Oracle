import pytest
from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from src.strategy_lab.strategies.bull_pulse import (
    BullPulseConfig,
    BullPulseState,
    BullPulseStrategyEngine,
)

KOLKATA = ZoneInfo("Asia/Kolkata")


def make_context(
    dt_str: str,
    index: int,
    spot: float,
    expiry_str: str,
    atm_strike: float,
    ce_ltp: float,
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
                        "strike": atm_strike,
                        "ce": {"security_id": 20000, "ltp": ce_ltp - 50},
                    },
                    {
                        "strike": atm_strike + 50,
                        "ce": {"security_id": 20002, "ltp": ce_ltp - 25},
                    },
                    {
                        "strike": atm_strike + 100,
                        "ce": {
                            "security_id": 20001,
                            "trading_symbol": f"NIFTY{expiry_str}{int(atm_strike+100)}CE",
                            "ltp": ce_ltp,
                        },
                    },
                ],
            },
        },
    }


def test_bull_pulse_dte_eligibility():
    engine = BullPulseStrategyEngine()
    
    # Expiry next Thursday, trading day Friday (DTE == 4) -> eligible
    ctx_eligible = make_context("2026-07-24T10:30:00", 1, 24000.0, "2026-07-28", 24000.0, 100.0)
    res = engine.evaluate(ctx_eligible)
    assert res["status"] == "WAIT"
    assert res["reason"] == "MOMENTUM_NOT_ALIGNED"
    
    # Expiry next Thursday, trading day Monday (DTE == 1) -> ineligible
    ctx_ineligible = make_context("2026-07-27T10:30:00", 2, 24000.0, "2026-07-28", 24000.0, 100.0)
    res2 = engine.evaluate(ctx_ineligible)
    assert res2["status"] == "UNAVAILABLE"
    assert res2["reason"] == "STRATEGY_INELIGIBLE_DTE"


def test_bull_pulse_strike_resolution():
    engine = BullPulseStrategyEngine()
    ctx = make_context("2026-07-24T10:30:00", 1, 24000.0, "2026-07-28", 24000.0, 100.0)
    res = engine.evaluate(ctx)
    assert res["option_contract"]["strike"] == 24100.0  # ATM (24000) + 2 * interval (50)
    assert res["option_contract"]["security_id"] == 20001


def test_bull_pulse_momentum_boundaries():
    engine = BullPulseStrategyEngine()
    
    # Initial bar sets reference premium to 100.0
    ctx_ref = make_context("2026-07-24T10:30:00", 1, 24000.0, "2026-07-28", 24000.0, 100.0)
    engine.evaluate(ctx_ref)
    assert engine.state.reference_premium == 100.0

    # Next bar premium goes to 109.0 (Below 10% trigger)
    ctx_below = make_context("2026-07-24T10:31:00", 2, 24000.0, "2026-07-28", 24000.0, 109.0)
    res_below = engine.evaluate(ctx_below)
    assert res_below["status"] == "WAIT"

    # Next bar premium goes to 110.0 (Exactly 10% trigger)
    ctx_trigger = make_context("2026-07-24T10:32:00", 3, 24000.0, "2026-07-28", 24000.0, 110.0)
    res_trigger = engine.evaluate(ctx_trigger)
    assert res_trigger["status"] == "ENTRY_CANDIDATE"
    assert res_trigger["signal"] == "BUY"
    assert engine.state.entry_trigger_status is True
    assert engine.state.theoretical_entry_price == 110.0
    assert engine.state.active_leg_stop == 88.0  # 20% below 110.0


def test_bull_pulse_stop_loss():
    engine = BullPulseStrategyEngine()
    
    # Position loaded at 100.0 entry. SL is 80.0.
    engine.state.session_date = "2026-07-24"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_pnl = 0.0
    engine.state.active_leg_stop = 80.0
    engine.state.selected_contract = {"security_id": 20001, "strike": 24100.0, "expiry": "2026-07-28"}

    # Premium falls to 80.5 (above stop)
    ctx_above = make_context("2026-07-24T10:31:00", 2, 24000.0, "2026-07-28", 24000.0, 80.5)
    res_above = engine.evaluate(ctx_above)
    assert res_above["status"] == "HOLD"

    # Premium falls to 80.0
    ctx_stop = make_context("2026-07-24T10:32:00", 3, 24000.0, "2026-07-28", 24000.0, 80.0)
    res_stop = engine.evaluate(ctx_stop)
    assert res_stop["status"] == "EXIT_CANDIDATE"
    assert res_stop["reason"] == "LEG_STOP_LOSS_HIT"
    assert engine.state.entry_trigger_status is False


def test_bull_pulse_overall_lock_and_trail():
    engine = BullPulseStrategyEngine()
    
    # Entry at 100.0, lot size 50. Stop is 80.0.
    engine.state.session_date = "2026-07-24"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_pnl = 0.0
    engine.state.active_leg_stop = 80.0
    engine.state.selected_contract = {"security_id": 20001, "strike": 24100.0, "expiry": "2026-07-28"}

    # Premium rises to 160.0 (PnL = (160-100)*50 = 3000). Lock floor of 2500 profit (premium 150.0) is set.
    ctx_lock = make_context("2026-07-24T10:31:00", 2, 24000.0, "2026-07-28", 24000.0, 160.0)
    engine.evaluate(ctx_lock)
    assert engine.state.active_overall_locked_profit_floor == 2500.0

    # Premium rises to 162.0 (PnL = 3100 -> +100 above trigger). Lock floor increases to 2600.
    ctx_step = make_context("2026-07-24T10:32:00", 3, 24000.0, "2026-07-28", 24000.0, 162.0)
    engine.evaluate(ctx_step)
    assert engine.state.active_overall_locked_profit_floor == 2600.0

    # Premium falls to 152.1 (PnL = 2605.0) -> HOLD
    ctx_hold = make_context("2026-07-24T10:33:00", 4, 24000.0, "2026-07-28", 24000.0, 152.1)
    res_hold = engine.evaluate(ctx_hold)
    assert res_hold["status"] == "HOLD"

    # Premium falls to 152.0 (PnL = 2600.0) -> Exits under lock profit trigger
    ctx_exit = make_context("2026-07-24T10:34:00", 5, 24000.0, "2026-07-28", 24000.0, 152.0)
    res_exit = engine.evaluate(ctx_exit)
    assert res_exit["status"] == "EXIT_CANDIDATE"
    assert res_exit["reason"] == "OVERALL_LOCKED_PROFIT_TRIGGERED"
    assert res_exit["pnl"] == 2600.0


def test_bull_pulse_forced_exit():
    engine = BullPulseStrategyEngine()
    engine.state.session_date = "2026-07-24"
    engine.state.entry_trigger_status = True
    engine.state.entry_count = 1
    engine.state.theoretical_entry_price = 100.0
    engine.state.highest_favourable_pnl = 0.0
    engine.state.active_leg_stop = 80.0
    engine.state.selected_contract = {"security_id": 20001, "strike": 24100.0, "expiry": "2026-07-28"}

    # Time reaches 15:00:00
    ctx_exit = make_context("2026-07-24T15:00:00", 150, 24000.0, "2026-07-28", 24000.0, 95.0)
    res_exit = engine.evaluate(ctx_exit)
    assert res_exit["status"] == "EXIT_CANDIDATE"
    assert res_exit["reason"] == "FORCED_SQUARE_OFF"


def test_bull_pulse_single_entry_idempotency():
    engine = BullPulseStrategyEngine()
    
    # Reference
    ctx1 = make_context("2026-07-24T10:30:00", 1, 24000.0, "2026-07-28", 24000.0, 100.0)
    engine.evaluate(ctx1)
    
    # Trigger
    ctx2 = make_context("2026-07-24T10:31:00", 2, 24000.0, "2026-07-28", 24000.0, 110.0)
    res2 = engine.evaluate(ctx2)
    assert res2["status"] == "ENTRY_CANDIDATE"
    
    # Duplicate
    res_dup = engine.evaluate(ctx2)
    assert res_dup["status"] == "WAIT"
    assert res_dup["reason"] == "BAR_ALREADY_EVALUATED"


def test_bull_pulse_serialization():
    engine = BullPulseStrategyEngine()
    ctx1 = make_context("2026-07-24T10:30:00", 1, 24000.0, "2026-07-28", 24000.0, 100.0)
    engine.evaluate(ctx1)
    
    serialized = engine.serialize()
    restored_engine = BullPulseStrategyEngine.deserialize(serialized)
    assert restored_engine.state.reference_premium == 100.0
    assert restored_engine.state.session_date == "2026-07-24"
