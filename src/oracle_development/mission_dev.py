"""Isolated development mission service for the Oracle Development segment."""

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


class MissionValidationError(ValueError):
    """Raised when mission transition inputs fail validation."""


class MissionNotFoundError(KeyError):
    """Raised when a requested mission is not found."""


class MissionConflictError(RuntimeError):
    """Raised when starting a mission conflicts with another active mission."""


class OracleDevMissionService:
    """Manages active and completed dev missions, persisting state to logs/oracle_dev/."""

    def __init__(self, state_root: Path):
        self.state_root = Path(state_root)
        self.state_path = self.state_root / "oracle_dev_mission_state.json"
        self.events_path = self.state_root / "oracle_dev_mission_events.jsonl"
        self._lock = threading.RLock()
        self._state = self._empty_state()
        self._load()

    def start(
        self,
        symbol: str,
        timeframe: str,
        parent_setup_family: str,
        trade_creator: str,
        direction: str,
        reference_time: str,
        operator: str = "SYSTEM",
        strategy_id: str = None,
        strategy_name: str = None,
        setup_subtype: str = None
    ) -> Dict[str, Any]:
        """Start a new isolated development mission."""
        with self._lock:
            active = self.active(timeframe)
            if active:
                raise MissionConflictError(f"Cannot start mission: mission {active['mission_id']} is already active on timeframe {timeframe}")
            
            mission_id = str(uuid.uuid4())
            now_str = datetime.now(timezone.utc).isoformat()
            
            if not strategy_id:
                if trade_creator == "VOB":
                    strategy_id = "VOB_PULLBACK_REVERSAL"
                    strategy_name = "VOB Pullback"
                    setup_subtype = "PA_PULLBACK_CONTINUATION"
                else:
                    strategy_id = "PA_FAILED_BREAKOUT_TRAP"
                    strategy_name = "Liquidity Trap"
                    setup_subtype = "SECOND_ENTRY_CONTINUATION"

            mission = {
                "mission_id": mission_id,
                "status": "PLANNED",
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "parent_setup_family": parent_setup_family,
                "trade_creator": trade_creator,
                "direction": direction,
                "reference_time": reference_time,
                "operator": operator,
                "created_at": now_str,
                "updated_at": now_str,
                "evaluations": [],
                "plans": [],
                "virtual_trades": [],
                "outcome": None,
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "setup_subtype": setup_subtype
            }
            
            self._state.setdefault("active_ids", {})
            self._state["active_ids"][timeframe] = mission_id
            self._state["active_id"] = mission_id
            self._state["missions"][mission_id] = mission
            
            self._record_and_persist("MISSION_STARTED", {"mission_id": mission_id, "mission": mission})
            return mission

    def active(self, timeframe: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns the currently active mission for a given timeframe, or any active mission if None."""
        with self._lock:
            active_ids = self._state.setdefault("active_ids", {})
            if timeframe:
                active_id = active_ids.get(timeframe)
                if active_id and active_id in self._state["missions"]:
                    return self._state["missions"][active_id]
            else:
                for t, active_id in list(active_ids.items()):
                    if active_id and active_id in self._state["missions"]:
                        m = self._state["missions"][active_id]
                        if m["status"] not in ("CLOSED", "FAILED", "CANCELLED", "TARGET_REACHED", "STRUCTURAL_SL_CLOSE", "PREMIUM_RISK_CAP"):
                            return m
                active_id = self._state.get("active_id")
                if active_id and active_id in self._state["missions"]:
                    return self._state["missions"][active_id]
            return None

    def get(self, mission_id: str) -> Dict[str, Any]:
        """Retrieve a specific mission by ID."""
        with self._lock:
            if mission_id not in self._state["missions"]:
                raise MissionNotFoundError(f"Mission {mission_id} not found")
            return self._state["missions"][mission_id]

    def cancel(self, mission_id: str, outcome: str = "CANCELLED") -> Dict[str, Any]:
        """Cancel/close an active mission."""
        with self._lock:
            mission = self._mission(mission_id)
            if mission["status"] in ("CLOSED", "FAILED", "CANCELLED", "TARGET_REACHED", "STRUCTURAL_SL_CLOSE", "PREMIUM_RISK_CAP"):
                return mission
            
            now_str = datetime.now(timezone.utc).isoformat()
            mission["status"] = outcome
            mission["outcome"] = outcome
            mission["updated_at"] = now_str
            
            # Clear from active_ids
            timeframe = mission.get("timeframe")
            active_ids = self._state.setdefault("active_ids", {})
            if timeframe and active_ids.get(timeframe) == mission_id:
                active_ids[timeframe] = None
            if self._state.get("active_id") == mission_id:
                self._state["active_id"] = None
                
            self._record_and_persist("MISSION_CLOSED", {"mission_id": mission_id, "outcome": outcome})
            return mission

    def evaluate(self, mission_id: str, scores: Dict[str, Any]) -> Dict[str, Any]:
        """Record a snapshot evaluation for a mission."""
        with self._lock:
            mission = self._mission(mission_id)
            if mission["status"] != "PLANNED":
                raise MissionValidationError(f"Cannot evaluate: mission {mission_id} is in status {mission['status']}")
            
            now_str = datetime.now(timezone.utc).isoformat()
            evaluation = {
                "timestamp": now_str,
                "scores": scores
            }
            mission["evaluations"].append(evaluation)
            mission["updated_at"] = now_str
            
            self._record_and_persist("MISSION_EVALUATED", {"mission_id": mission_id, "evaluation": evaluation})
            return mission

    def plan(self, mission_id: str, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record trade plan details (entry, SL, target, quantity)."""
        with self._lock:
            mission = self._mission(mission_id)
            now_str = datetime.now(timezone.utc).isoformat()
            
            plan_record = {
                "timestamp": now_str,
                "plan": plan_data
            }
            mission["plans"].append(plan_record)
            mission["updated_at"] = now_str
            
            self._record_and_persist("MISSION_PLANNED", {"mission_id": mission_id, "plan": plan_record})
            return mission

    def add_virtual_trade(self, mission_id: str, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Logs a virtual paper execution event within the mission context."""
        with self._lock:
            mission = self._mission(mission_id)
            now_str = datetime.now(timezone.utc).isoformat()
            
            trade_data["logged_at"] = now_str
            mission["virtual_trades"].append(trade_data)
            mission["updated_at"] = now_str
            
            self._record_and_persist("VIRTUAL_TRADE_LOGGED", {"mission_id": mission_id, "trade": trade_data})
            return mission

    def recent(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Return the most recently updated missions."""
        with self._lock:
            sorted_missions = sorted(
                self._state["missions"].values(),
                key=lambda m: m["updated_at"],
                reverse=True
            )
            return sorted_missions[:limit]

    def _mission(self, mission_id: str) -> Dict[str, Any]:
        if mission_id not in self._state["missions"]:
            raise MissionNotFoundError(f"Mission {mission_id} not found")
        return self._state["missions"][mission_id]

    def _load(self) -> None:
        """Load state and replay events from disk."""
        self.state_root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self.state_path.exists():
                try:
                    with open(self.state_path, "r", encoding="utf-8") as f:
                        self._state = json.load(f)
                    # Verify structure
                    if "missions" not in self._state or "active_id" not in self._state:
                        self._state = self._empty_state()
                except Exception:
                    self._state = self._empty_state()
            else:
                self._state = self._empty_state()

    def _record_and_persist(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Write event log entry and atomic state update to disk."""
        with self._lock:
            now_str = datetime.now(timezone.utc).isoformat()
            event = {
                "event_type": event_type,
                "timestamp": now_str,
                "payload": payload
            }
            
            # 1. Append to events list
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
                
            # 2. Write state file atomically
            fd, temp_path = tempfile.mkstemp(prefix=f".{self.state_path.name}.", dir=self.state_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._state, handle, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.state_path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

    @classmethod
    def _empty_state(cls) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "active_id": None,
            "missions": {}
        }
