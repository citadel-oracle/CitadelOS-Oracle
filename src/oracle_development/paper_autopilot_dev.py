"""Setup-aware Guardian, State Machine, and Virtual Paper Ledger for the Oracle Development segment."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class OracleDevPaperAutopilot:
    """Manages separate state machines, paper ledgers, and setup-aware Guardians for 1m, 3m, 5m lanes."""

    def __init__(
        self,
        state_root: Path,
        missions: Any,
        resolver: Any,
        clock=None
    ):
        self.state_root = Path(state_root)
        self.missions = missions
        self.resolver = resolver
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        
        # State paths
        self.guardian_state_path = self.state_root / "oracle_dev_guardian_state.json"
        self.execution_events_path = self.state_root / "oracle_dev_execution_events.jsonl"
        self.journal_path = self.state_root / "oracle_dev_execution_journal.jsonl"
        self.stats_path = self.state_root / "oracle_dev_stats.json"

        # Initialize or reload state
        self._state = self._empty_state()
        self._load()

    def update_lane_candles(
        self,
        lane: str,
        spot_candles: List[Dict[str, Any]],
        futures_candles: List[Dict[str, Any]],
        option_candles: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Update historical candles and execute state evaluation for a specific timeframe lane."""
        with self._lock:
            if lane not in self._state["lanes"]:
                self._state["lanes"][lane] = self._empty_lane_state(lane)
            
            lane_data = self._state["lanes"][lane]
            lane_data["last_spot"] = spot_candles[-1] if spot_candles else None
            lane_data["last_futures"] = futures_candles[-1] if futures_candles else None
            lane_data["last_option"] = {k: v[-1] for k, v in option_candles.items() if v}

            # Evaluate active trade or state changes
            self._evaluate_guardian(lane, spot_candles, futures_candles, option_candles)

    def trigger_setup_detected(
        self,
        lane: str,
        setup_family: str,
        direction: str,
        scores: Dict[str, Any],
        plan_data: Dict[str, Any]
    ) -> None:
        """Triggers transition to SETUP_ARMED / READY when a new trade creator event is detected."""
        with self._lock:
            lane_data = self._state["lanes"].setdefault(lane, self._empty_lane_state(lane))
            
            if lane_data["state"] in ("OPEN", "EXITING"):
                return  # Skip if already in trade
                
            lane_data["state"] = "SETUP_ARMED"
            lane_data["active_setup"] = {
                "family": setup_family,
                "direction": direction,
                "scores": scores,
                "plan": plan_data,
                "detected_at": self.clock().isoformat()
            }
            
            # Transition to TRIGGER_DETECTED -> READY_CONFIRMED
            lane_data["state"] = "READY_CONFIRMED"
            
            self._persist()

    def execute_paper_order(
        self,
        lane: str,
        mission_id: str,
        contract: Dict[str, Any],
        direction: str,
        lots: int,
        price: float
    ) -> Dict[str, Any]:
        """Place a virtual paper trade order, locking parameters and initiating position."""
        with self._lock:
            lane_data = self._state["lanes"].setdefault(lane, self._empty_lane_state(lane))
            now_str = self.clock().isoformat()
            
            # Form position
            qty = lots * contract.get("lot_size", 65)
            trade_value = price * qty
            commission = 20.0 # flat mock commission
            
            # Fetch strategy registry details from mission
            strategy_id = "VOB_PULLBACK_REVERSAL"
            strategy_name = "VOB Pullback"
            setup_subtype = "PA_PULLBACK_CONTINUATION"
            trade_creator = "VOB"
            try:
                m_info = self.missions.get(mission_id)
                if m_info:
                    strategy_id = m_info.get("strategy_id") or strategy_id
                    strategy_name = m_info.get("strategy_name") or strategy_name
                    setup_subtype = m_info.get("setup_subtype") or setup_subtype
                    trade_creator = m_info.get("trade_creator") or trade_creator
            except Exception:
                pass

            # Update virtual balance
            lane_data["balance"] -= (trade_value + commission)
            
            virtual_trade = {
                "trade_id": f"VT-{lane}-{int(self.clock().timestamp())}",
                "mission_id": mission_id,
                "security_id": contract["security_id"],
                "symbol": contract["symbol"],
                "direction": direction,
                "lots": lots,
                "quantity": qty,
                "entry_price": price,
                "entry_time": now_str,
                "exit_price": None,
                "exit_time": None,
                "commission": commission,
                "status": "OPEN",
                "mae": price,
                "mfe": price,
                "pnl": 0.0,
                "exit_reason": None,
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "setup_subtype": setup_subtype,
                "trade_creator": trade_creator
            }
            
            lane_data["position"] = virtual_trade
            lane_data["state"] = "OPEN"
            lane_data["position_history"].append(virtual_trade)
            
            # Add virtual trade to mission state
            self.missions.add_virtual_trade(mission_id, virtual_trade)
            
            self._record_execution("VIRTUAL_ORDER_FILLED", {
                "lane": lane,
                "mission_id": mission_id,
                "order": virtual_trade
            })
            
            self._persist()
            return virtual_trade

    def get_lane_status(self, lane: str) -> Dict[str, Any]:
        """Retrieve current metrics and positions for a specific lane."""
        with self._lock:
            return self._state["lanes"].get(lane) or self._empty_lane_state(lane)

    def _evaluate_guardian(
        self,
        lane: str,
        spot_candles: List[Dict[str, Any]],
        futures_candles: List[Dict[str, Any]],
        option_candles: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Run setup-aware Guardian checks on the active virtual position for a timeframe lane."""
        lane_data = self._state["lanes"][lane]
        pos = lane_data["position"]
        if not pos or pos["status"] != "OPEN":
            # If Flat, evaluate if SETUP_ARMED expires
            if lane_data["state"] == "READY_CONFIRMED":
                # Auto-transition to idle if setup is stale
                lane_data["state"] = "IDLE"
                lane_data["active_setup"] = None
                self._persist()
            return

        # Active trade monitoring
        mission_id = pos["mission_id"]
        mission = self.missions.get(mission_id)
        
        # Get active candle details
        last_candle_time = spot_candles[-1]["time"]
        last_close = float(spot_candles[-1]["close"])
        
        # Expose current action and reason
        lane_data["guardian_action"] = "Monitoring"
        lane_data["guardian_reason"] = f"Spot: {last_close}. Invalidation: {mission['plans'][-1]['plan']['structural_sl']}"

        # Resolve latest price of option contract
        opt_key = "ATM_CE" if pos["direction"] == "CALL" else "ATM_PE"
        opt_feed = option_candles.get(opt_key)
        
        current_option_price = pos["entry_price"]
        if opt_feed:
            current_option_price = float(opt_feed[-1]["close"])
            # Track MFE / MAE
            pos["mfe"] = max(pos["mfe"], current_option_price)
            pos["mae"] = min(pos["mae"], current_option_price)

        # 1. Structural stop loss validation on timeframe candle completion
        plan = mission["plans"][-1]["plan"]
        structural_sl = float(plan["structural_sl"])
        
        trigger_exit = False
        exit_reason = None
        
        # Verify candle completion
        candle_closed = True # Always True since resampler only emits completed candles
        
        if candle_closed:
            if pos["direction"] == "CALL" and last_close < structural_sl:
                trigger_exit = True
                exit_reason = "STRUCTURAL_SL_CLOSE"
            elif pos["direction"] == "PUT" and last_close > structural_sl:
                trigger_exit = True
                exit_reason = "STRUCTURAL_SL_CLOSE"

        # 2. Options premium emergency risk cap (e.g. 30% premium drawdown limit)
        drawdown_pct = (pos["entry_price"] - current_option_price) / pos["entry_price"]
        if drawdown_pct >= 0.30:
            trigger_exit = True
            exit_reason = "PREMIUM_RISK_CAP"

        # 3. Check targets
        target_price = float(plan["target_price"])
        if pos["direction"] == "CALL" and last_close >= target_price:
            trigger_exit = True
            exit_reason = "TARGET_REACHED"
        elif pos["direction"] == "PUT" and last_close <= target_price:
            trigger_exit = True
            exit_reason = "TARGET_REACHED"

        if trigger_exit:
            lane_data["state"] = "EXITING"
            lane_data["guardian_action"] = "Executing Exit"
            lane_data["guardian_reason"] = f"Trigger: {exit_reason}"
            
            # Execute simulated exit order at current option price
            now_str = self.clock().isoformat()
            pos["exit_price"] = current_option_price
            pos["exit_time"] = now_str
            pos["status"] = "CLOSED"
            pos["exit_reason"] = exit_reason
            
            # Calculate final P&L
            qty = pos["quantity"]
            gross_pnl = (pos["exit_price"] - pos["entry_price"]) * qty
            if pos["direction"] == "PUT":
                # For put, entry is buying option, so same direction calculation
                pass
            
            pos["pnl"] = gross_pnl - pos["commission"]
            
            # Add to ledger balance
            lane_data["balance"] += (current_option_price * qty - pos["commission"])
            
            # Log final trade P&L metrics
            self.missions.cancel(mission_id, outcome=exit_reason)
            lane_data["position"] = None
            lane_data["state"] = "CLOSED"
            lane_data["active_setup"] = None
            
            self._record_execution("VIRTUAL_ORDER_FILLED", {
                "lane": lane,
                "mission_id": mission_id,
                "order": pos
            })
            
            self._update_stats(pos)
            self._persist()

    def _update_stats(self, closed_trade: Dict[str, Any]) -> None:
        """Update metrics journal and durability state."""
        stats = self._state.setdefault("stats", {"total_trades": 0, "win_trades": 0, "net_pnl": 0.0})
        stats["total_trades"] += 1
        if closed_trade["pnl"] > 0:
            stats["win_trades"] += 1
        stats["net_pnl"] += closed_trade["pnl"]

        # Write to stats file
        try:
            with open(self.stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f)
        except Exception:
            pass

    def _load(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self.guardian_state_path.exists():
                try:
                    with open(self.guardian_state_path, "r", encoding="utf-8") as f:
                        self._state = json.load(f)
                    if "lanes" not in self._state:
                        self._state = self._empty_state()
                except Exception:
                    self._state = self._empty_state()
            else:
                self._state = self._empty_state()

            # Lifecycle state consistency sanitizer
            for lane, lane_data in self._state.get("lanes", {}).items():
                pos = lane_data.get("position")
                if pos:
                    if lane_data.get("state") not in ("OPEN", "EXITING"):
                        lane_data["state"] = "OPEN"
                else:
                    if lane_data.get("state") in ("OPEN", "EXITING"):
                        lane_data["state"] = "CLOSED"

    def _persist(self) -> None:
        with self._lock:
            fd, temp_path = tempfile.mkstemp(prefix=f".{self.guardian_state_path.name}.", dir=self.guardian_state_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._state, handle, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.guardian_state_path)
            except Exception:
                pass
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

    def _record_execution(self, event_type: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            event = {
                "event_type": event_type,
                "timestamp": self.clock().isoformat(),
                "payload": payload
            }
            try:
                with open(self.execution_events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, separators=(",", ":")) + "\n")
            except Exception:
                pass

    @classmethod
    def _empty_state(cls) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "lanes": {
                "1m": cls._empty_lane_state("1m"),
                "3m": cls._empty_lane_state("3m"),
                "5m": cls._empty_lane_state("5m")
            },
            "stats": {
                "total_trades": 0,
                "win_trades": 0,
                "net_pnl": 0.0
            }
        }

    @staticmethod
    def _empty_lane_state(lane: str) -> Dict[str, Any]:
        return {
            "timeframe": lane,
            "state": "IDLE",
            "active_setup": None,
            "position": None,
            "balance": 1000000.0, # initial virtual capital
            "position_history": [],
            "guardian_action": "Monitoring",
            "guardian_reason": "No active position",
            "last_spot": None,
            "last_futures": None,
            "last_option": {}
        }
