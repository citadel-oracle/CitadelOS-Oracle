"""Durable operator-driven six-trade demo tour using the Oracle paper stack."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from src.execution.paper_state import PaperStateService, PaperStateUnavailable
from src.strategy_lab.storage import _atomic_write


TOUR = (("CE", 4), ("PE", 4), ("CE", 5), ("PE", 5), ("CE", 4), ("PE", 4))


class DemoTourError(RuntimeError):
    pass


class DemoTourSession:
    """Coordinates existing Mission/Planner/Autopilot instances; never executes itself."""

    def __init__(
        self,
        root: Path,
        *,
        missions,
        autopilot,
        paper_state: PaperStateService,
        snapshot_provider: Callable[[], Mapping[str, Any]],
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.root = Path(root)
        self.path = self.root / "tour_state.json"
        self.missions = missions
        self.autopilot = autopilot
        self.paper_state = paper_state
        self.snapshot_provider = snapshot_provider
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._state = self._load()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state.get("status") == "ACTIVE":
                return self.status()
            if self.missions.active() is not None:
                raise DemoTourError("DEMO_MISSION_ALREADY_ACTIVE")
            try:
                self.paper_state.load()
            except PaperStateUnavailable:
                self.paper_state.initialize()
            if self.paper_state.load().open_positions:
                raise DemoTourError("DEMO_POSITION_ALREADY_OPEN")
            now = self._now()
            self._state = {
                "schema_version": 1,
                "tour_id": f"demo_tour_{now.strftime('%Y%m%dT%H%M%S')}",
                "status": "ACTIVE",
                "current_trade": 0,
                "current_mission_id": None,
                "trades": [],
                "cooldown_until": None,
                "started_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "completed_at": None,
                "execution_origin": "DEMO_PAPER",
                "directional_edge": "NOT_CLAIMED",
                "exclude_from_strategy_stats": True,
                "exclude_from_backtests": True,
                "exclude_from_performance_metrics": True,
                "paper_only": True,
                "live_trading_enabled": False,
                "broker_submission": False,
            }
            self._persist()
            return self.status()

    def plan_next(self) -> dict[str, Any]:
        with self._lock:
            self._require_active()
            if self._state["current_mission_id"]:
                raise DemoTourError("PREVIOUS_DEMO_TRADE_NOT_CLOSED")
            index = int(self._state["current_trade"])
            if index >= len(TOUR):
                raise DemoTourError("DEMO_TOUR_LIMIT_REACHED")
            cooldown = self._state.get("cooldown_until")
            if cooldown and self._now() < datetime.fromisoformat(cooldown):
                raise DemoTourError("DEMO_COOLDOWN_ACTIVE")
            side, lots = TOUR[index]
            mission = self.missions.start(
                idempotency_key=f"{self._state['tour_id']}:trade:{index + 1}",
                instrument_scope="NIFTY",
                mode="DEMO_PAPER",
                max_trades=1,
                timeout_seconds=600,
            )
            plan = self.missions.plan_demo(
                mission["mission_id"],
                self.snapshot_provider(),
                option_type=side,
                lots=lots,
            )
            row = {
                "trade_number": index + 1,
                "side": side,
                "lots": lots,
                "mission_id": mission["mission_id"],
                "contract": plan["contract"],
                "security_id": plan["security_id"],
                "lot_size": plan["lot_size"],
                "quantity": plan["approved_quantity"],
                "simulated_risk": plan["simulated_risk"],
                "entry": None,
                "exit": None,
                "pnl": None,
                "guardian_state": "PLANNED",
                "guardian_action": None,
                "planned_at": self._now().isoformat(),
                "closed_at": None,
            }
            self._state["trades"].append(row)
            self._state["current_mission_id"] = mission["mission_id"]
            self._touch()
            return {"mission": mission, "plan": plan, "tour": self.status()}

    def execute(self) -> dict[str, Any]:
        with self._lock:
            mission_id = self._current_mission()
            guardian = self.autopilot.execute(mission_id)
            return self._observe(guardian)

    def guardian(self) -> dict[str, Any]:
        with self._lock:
            mission_id = self._current_mission()
            return self._observe(self.autopilot.guardian(mission_id))

    def exit(self, reason: str = "DEMO_OPERATOR_EXIT") -> dict[str, Any]:
        with self._lock:
            mission_id = self._current_mission()
            return self._observe(self.autopilot.exit(mission_id, reason))

    def status(self) -> dict[str, Any]:
        with self._lock:
            value = deepcopy(self._state)
            value["trade_total"] = len(TOUR)
            value["remaining_hold_seconds"] = None
            value["guardian"] = None
            current = value.get("current_mission_id")
            if current:
                guardian = self.autopilot._state.get("guardians", {}).get(current)
                if guardian:
                    value["guardian"] = self.autopilot._public(guardian)
                if guardian and guardian.get("opened_at"):
                    elapsed = (
                        self._now()
                        - datetime.fromisoformat(guardian["opened_at"]).astimezone(timezone.utc)
                    ).total_seconds()
                    value["remaining_hold_seconds"] = max(0, 90 - int(elapsed))
            return value

    def _observe(self, guardian: Mapping[str, Any]) -> dict[str, Any]:
        row = self._state["trades"][-1]
        row["guardian_state"] = guardian.get("state")
        row["guardian_action"] = guardian.get("reason")
        row["entry"] = guardian.get("entry_fill_price")
        if guardian.get("state") == "CLOSED":
            closed = self.paper_state.load().closed_trades[-1]
            row["exit"] = closed.exit_price
            row["pnl"] = closed.realized_pnl
            row["closed_at"] = closed.closed_at
            self.missions.complete_demo(row["mission_id"])
            self._state["current_trade"] += 1
            self._state["current_mission_id"] = None
            self._state["cooldown_until"] = (
                self._now().timestamp() + 10
            )
            self._state["cooldown_until"] = datetime.fromtimestamp(
                self._state["cooldown_until"], timezone.utc
            ).isoformat()
            if self._state["current_trade"] == len(TOUR):
                self._state["status"] = "COMPLETED"
                self._state["completed_at"] = self._now().isoformat()
        self._touch()
        return {"guardian": dict(guardian), "tour": self.status()}

    def _current_mission(self) -> str:
        self._require_active()
        value = self._state.get("current_mission_id")
        if not value:
            raise DemoTourError("DEMO_TRADE_NOT_PLANNED")
        return str(value)

    def _require_active(self) -> None:
        if self._state.get("status") != "ACTIVE":
            raise DemoTourError("DEMO_TOUR_NOT_ACTIVE")

    def _touch(self) -> None:
        self._state["updated_at"] = self._now().isoformat()
        self._persist()

    def _persist(self) -> None:
        _atomic_write(self.path, self._state)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "status": "NOT_STARTED", "trades": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise DemoTourError("DEMO_TOUR_STATE_CORRUPT") from error
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise DemoTourError("DEMO_TOUR_STATE_CORRUPT")
        return value

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None:
            raise DemoTourError("DEMO_CLOCK_INVALID")
        return value.astimezone(timezone.utc)
