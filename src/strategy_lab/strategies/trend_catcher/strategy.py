"""Nifty Trend Catcher pure native deterministic engine."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, date
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo


KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class TrendCatcherConfig:
    trading_mode: str = "Intraday"
    entry_start_time: str = "09:35"
    exit_time: str = "15:15"
    leg_stop_loss_value: float = 30.0  # Points
    leg_trailing_sl_trigger: float = 10.0
    leg_trailing_sl_step: float = 10.0
    overall_stop_loss_value: float = 1000.0  # Rs
    overall_trailing_lock_trigger: float = 1000.0
    overall_trailing_lock_value: float = 500.0
    momentum_percent: float = 40.0


@dataclass
class TrendCatcherState:
    session_date: Optional[str] = None
    selected_expiry: Optional[str] = None
    selected_contract: Optional[dict] = None
    reference_timestamp: Optional[str] = None
    reference_premium: Optional[float] = None
    entry_trigger_status: bool = False
    entry_count: int = 0
    theoretical_entry_price: Optional[float] = None
    highest_favourable_premium: Optional[float] = None
    active_position_state: Optional[dict] = None
    active_leg_stop: Optional[float] = None
    active_overall_locked_profit_floor: Optional[float] = None
    exit_reason: Optional[str] = None
    terminal_session_state: bool = False
    last_bar_index: Optional[int] = None
    counterfactual_active_signal_id: Optional[str] = None



class TrendCatcherStrategyEngine:
    """Pure native options buying engine for Nifty Trend Catcher."""

    def __init__(
        self,
        config: Optional[TrendCatcherConfig] = None,
        state: Optional[TrendCatcherState] = None,
    ) -> None:
        self.config = config or TrendCatcherConfig()
        self.state = state or TrendCatcherState()

    def serialize(self) -> str:
        return json.dumps({
            "config": asdict(self.config),
            "state": asdict(self.state),
        }, sort_keys=True)

    @classmethod
    def deserialize(cls, payload: str) -> TrendCatcherStrategyEngine:
        data = json.loads(payload)
        config = TrendCatcherConfig(**data.get("config", {}))
        state = TrendCatcherState(**data.get("state", {}))
        return cls(config=config, state=state)

    def evaluate(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        """Evaluates a completed candle context and returns the native directive."""
        raw_bar = context.get("bar")
        if not isinstance(raw_bar, Mapping):
            return self._wait("MARKET_CONTEXT_REQUIRED", status="UNAVAILABLE")

        # 1. Parse candle time and verify timezone
        try:
            bar_timestamp = self._parse_time(raw_bar.get("timestamp", raw_bar.get("time")))
            bar_date_str = bar_timestamp.date().isoformat()
            bar_index = int(raw_bar.get("index", raw_bar.get("bar_index", 0)))
        except (TypeError, ValueError):
            return self._wait("BAR_TIMESTAMP_INVALID", status="UNAVAILABLE")

        # Handle duplicate bars (idempotency)
        if self.state.last_bar_index is not None and bar_index <= self.state.last_bar_index:
            return self._wait("BAR_ALREADY_EVALUATED", status="WAIT")

        # 2. Reset state if it's a new day
        if self.state.session_date != bar_date_str:
            self.state = TrendCatcherState(session_date=bar_date_str)

        self.state.last_bar_index = bar_index

        if self.state.terminal_session_state:
            return self._wait(f"SESSION_TERMINATED: {self.state.exit_reason}", status="SESSION_COMPLETE")

        # 3. Resolve actual weekly expiry and verify DTE
        argus = context.get("argus")
        if not isinstance(argus, Mapping) or not isinstance(argus.get("data"), Mapping):
            return self._wait("ARGUS_DATA_REQUIRED", status="UNAVAILABLE")

        data_payload = argus["data"]
        underlying = data_payload.get("underlying")
        if not isinstance(underlying, Mapping):
            return self._wait("ARGUS_UNDERLYING_REQUIRED", status="UNAVAILABLE")

        expiry_str = underlying.get("expiry")
        if not expiry_str:
            return self._wait("EXPIRY_CALENDAR_UNAVAILABLE", status="UNAVAILABLE")

        try:
            expiry_date = date.fromisoformat(expiry_str)
            dte = (expiry_date - bar_timestamp.date()).days
        except (TypeError, ValueError):
            return self._wait("EXPIRY_CALENDAR_UNAVAILABLE", status="UNAVAILABLE")

        self.state.selected_expiry = expiry_str
        self.state.dte = dte

        # Check DTE eligibility
        if dte != 1:
            return self._wait("STRATEGY_INELIGIBLE_DTE", status="UNAVAILABLE")

        # 4. Resolve Strike (OTM2 PE) or retrieve locked contract
        if self.state.selected_contract is not None:
            security_id = self.state.selected_contract.get("security_id")
            trading_symbol = self.state.selected_contract.get("trading_symbol")
            otm2_strike = self.state.selected_contract.get("strike")
            
            # Find the locked contract in the current window to get its current premium (LTP)
            window = data_payload.get("atm_window") or []
            found_contract = None
            for row in window:
                pe = row.get("pe")
                if isinstance(pe, Mapping) and str(pe.get("security_id")) == str(security_id):
                    found_contract = pe
                    break
            
            if found_contract is None or found_contract.get("ltp") is None:
                return self._wait("CONTRACT_DATA_UNAVAILABLE", status="UNAVAILABLE")
            
            current_premium = float(found_contract["ltp"])
        else:
            if not self._time_gte(bar_timestamp, self.config.entry_start_time):
                return self._wait("BEFORE_ENTRY_WINDOW", status="WAIT")

            atm_strike = underlying.get("atm_strike")
            if atm_strike is None:
                return self._wait("ATM_STRIKE_UNAVAILABLE", status="UNAVAILABLE")

            atm_strike = float(atm_strike)
            window = data_payload.get("atm_window")
            if not isinstance(window, list) or len(window) < 2:
                return self._wait("ATM_WINDOW_UNAVAILABLE", status="UNAVAILABLE")

            strike_interval = self._resolve_strike_interval(window)
            otm2_strike = atm_strike - (2 * strike_interval)

            # Find OTM2 PE contract in option chain
            otm2_row = self._find_strike_row(window, otm2_strike)
            if otm2_row is None:
                return self._wait("OTM2_STRIKE_NOT_IN_WINDOW", status="UNAVAILABLE")

            pe_contract = otm2_row.get("pe")
            if not isinstance(pe_contract, Mapping):
                return self._wait("PE_CONTRACT_UNAVAILABLE", status="UNAVAILABLE")

            security_id = pe_contract.get("security_id")
            trading_symbol = pe_contract.get("trading_symbol")
            current_premium = pe_contract.get("ltp")

            if not security_id or not trading_symbol or current_premium is None:
                return self._wait("PE_CONTRACT_DATA_INCOMPLETE", status="UNAVAILABLE")

            current_premium = float(current_premium)

            # Lock the contract details
            self.state.selected_contract = {
                "security_id": security_id,
                "trading_symbol": trading_symbol,
                "strike": otm2_strike,
                "expiry": expiry_str,
                "option_type": "PE",
                "strike_offset": -2,
                "underlying": "NIFTY",
            }

        lot_size = int(context.get("lot_size", 50))

        # 5. Position Management
        if self.state.entry_trigger_status:
            # Active Position Evaluation
            pnl = (current_premium - self.state.theoretical_entry_price) * lot_size
            self.state.highest_favourable_premium = max(self.state.highest_favourable_premium, current_premium)

            # Trailing stop logic (10-for-10 step calculation)
            favourable_diff = self.state.highest_favourable_premium - self.state.theoretical_entry_price
            steps = int(max(0.0, favourable_diff) // self.config.leg_trailing_sl_trigger)
            active_stop = (self.state.theoretical_entry_price - self.config.leg_stop_loss_value) + (steps * self.config.leg_trailing_sl_step)
            self.state.active_leg_stop = active_stop

            # Lock Profit logic (if P&L reaches 1000, lock 500)
            if pnl >= self.config.overall_trailing_lock_trigger:
                self.state.active_overall_locked_profit_floor = self.config.overall_trailing_lock_value

            # Check Stop Loss
            if current_premium <= active_stop:
                return self._exit("LEG_STOP_LOSS_HIT", current_premium, lot_size)

            # Check Lock Profit Floor
            if self.state.active_overall_locked_profit_floor is not None:
                if pnl <= self.state.active_overall_locked_profit_floor:
                    return self._exit("OVERALL_LOCKED_PROFIT_TRIGGERED", current_premium, lot_size)

            # Check Strategy Overall Stop Loss (Max Loss Rs 1,000)
            if pnl <= -self.config.overall_stop_loss_value:
                return self._exit("OVERALL_STOP_LOSS_TRIGGERED", current_premium, lot_size)

            # Check Square-off session time (15:15 IST)
            if self._time_gte(bar_timestamp, self.config.exit_time):
                return self._exit("FORCED_SQUARE_OFF", current_premium, lot_size)

            # Return HOLD directive
            return self._hold(current_premium, pnl)

        # 6. Entry Logic
        # Prevent second daily entry after restart
        if self.state.entry_count >= 1:
            self.state.terminal_session_state = True
            self.state.exit_reason = "MAX_DAILY_ENTRY_REACHED"
            return self._wait("SESSION_COMPLETE_NO_ENTRY", status="SESSION_COMPLETE")

        # Check Entry Window (starts at 09:35 AM IST)
        if not self._time_gte(bar_timestamp, self.config.entry_start_time):
            return self._wait("BEFORE_ENTRY_WINDOW", status="WAIT")

        # Capture reference premium at exactly 09:35:00 AM IST
        if self.state.reference_premium is None:
            # Check if this candle is at or after 09:35:00
            # Since the entry check is active, the first candle we process >= 09:35 will establish reference
            self.state.reference_premium = current_premium
            self.state.reference_timestamp = bar_timestamp.isoformat()

        # Check square-off time for entry (cannot enter after exit_time)
        if self._time_gte(bar_timestamp, self.config.exit_time):
            self.state.terminal_session_state = True
            self.state.exit_reason = "EXPIRED_OUTSIDE_ENTRY_WINDOW"
            return self._wait("SESSION_COMPLETE_NO_ENTRY", status="SESSION_COMPLETE")

        # Check entry trigger boundary (premium >= reference_premium * 1.40)
        trigger_price = self.state.reference_premium * (1.0 + (self.config.momentum_percent / 100.0))
        if current_premium >= trigger_price - 1e-9:
            # Trigger Entry
            self.state.entry_trigger_status = True
            self.state.entry_count = 1
            self.state.theoretical_entry_price = current_premium
            self.state.highest_favourable_premium = current_premium
            self.state.active_leg_stop = current_premium - self.config.leg_stop_loss_value
            self.state.active_position_state = {
                "entry_price": current_premium,
                "entry_time": bar_timestamp.isoformat(),
            }
            return {
                "status": "ENTRY_CANDIDATE",
                "signal": "BUY",
                "reason": "MOMENTUM_TRIGGERED",
                "entry": current_premium,
                "sl": self.state.active_leg_stop,
                "target": None,
                "option_contract": self.state.selected_contract,
                "lot_size": lot_size,
                "state": asdict(self.state),
            }

        return self._wait("MOMENTUM_NOT_ALIGNED", status="WAIT")

    def _wait(self, reason: str, status: str = "WAIT") -> Dict[str, Any]:
        return {
            "status": status,
            "signal": "WAIT",
            "reason": reason,
            "entry": None,
            "sl": None,
            "target": None,
            "option_contract": self.state.selected_contract,
            "state": asdict(self.state),
        }

    def _hold(self, price: float, pnl: float) -> Dict[str, Any]:
        return {
            "status": "HOLD",
            "signal": "WAIT",
            "reason": "POSITION_ACTIVE",
            "entry": self.state.theoretical_entry_price,
            "sl": self.state.active_leg_stop,
            "target": None,
            "option_contract": self.state.selected_contract,
            "state": asdict(self.state),
        }

    def _exit(self, reason: str, price: float, lot_size: int) -> Dict[str, Any]:
        pnl = (price - self.state.theoretical_entry_price) * lot_size
        self.state.entry_trigger_status = False
        self.state.terminal_session_state = True
        self.state.exit_reason = reason
        self.state.active_position_state = None
        return {
            "status": "EXIT_CANDIDATE",
            "signal": "SELL",
            "reason": reason,
            "entry": self.state.theoretical_entry_price,
            "sl": self.state.active_leg_stop,
            "target": None,
            "option_contract": self.state.selected_contract,
            "exit_price": price,
            "pnl": pnl,
            "state": asdict(self.state),
        }

    @staticmethod
    def _parse_time(value: Any) -> datetime:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=KOLKATA_TZ) if dt.tzinfo is None else dt.astimezone(KOLKATA_TZ)

    @staticmethod
    def _time_gte(dt: datetime, time_str: str) -> bool:
        hours, minutes = map(int, time_str.split(":"))
        return dt.time() >= datetime.combine(dt.date(), datetime.min.time(), KOLKATA_TZ).replace(hour=hours, minute=minutes).time()

    @staticmethod
    def _resolve_strike_interval(window: list[Mapping[str, Any]]) -> float:
        strikes = sorted([float(row["strike"]) for row in window if "strike" in row])
        if len(strikes) >= 2:
            return strikes[1] - strikes[0]
        return 50.0

    @staticmethod
    def _find_strike_row(window: list[Mapping[str, Any]], strike: float) -> Optional[Mapping[str, Any]]:
        for row in window:
            if abs(float(row.get("strike", 0.0)) - strike) < 0.001:
                return row
        return None
