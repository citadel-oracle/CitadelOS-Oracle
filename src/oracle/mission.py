"""Durable, advisory-only Oracle mission contracts and state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.strategy_lab.storage import ImmutableStream, _atomic_write
from src.oracle.opportunity_adapter import (
    SnapshotAdapterError,
    evaluate_v2_snapshot,
)
from src.oracle.trade_planner import OracleTradePlanner, TradePlanError


class MissionMode(str, Enum):
    ADVISE = "ADVISE"
    CONFIRM = "CONFIRM"
    PAPER_AUTOPILOT = "PAPER_AUTOPILOT"
    DEMO_PAPER = "DEMO_PAPER"


class MissionStartRequest(BaseModel):
    idempotency_key: str
    instrument_scope: str
    mode: str = MissionMode.ADVISE.value
    max_trades: int = 1
    timeout_seconds: int = 900


class MissionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_quantity: Optional[int] = None


class OracleMissionError(RuntimeError):
    code = "ORACLE_MISSION_ERROR"


class MissionValidationError(OracleMissionError):
    code = "ORACLE_MISSION_INVALID"


class MissionConflictError(OracleMissionError):
    code = "ORACLE_MISSION_ACTIVE"


class MissionNotFoundError(OracleMissionError):
    code = "ORACLE_MISSION_NOT_FOUND"


class MissionStateUnavailableError(OracleMissionError):
    code = "ORACLE_MISSION_STATE_UNAVAILABLE"


class MissionEvaluationUnavailableError(OracleMissionError):
    code = "ORACLE_MISSION_EVALUATION_UNAVAILABLE"

    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        self.reasons = tuple(reasons)
        super().__init__(message)


class MissionPlanUnavailableError(OracleMissionError):
    code = "ORACLE_MISSION_PLAN_UNAVAILABLE"

    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        self.reasons = tuple(reasons)
        super().__init__(message)


class OracleMissionService:
    """Maintains one durable advisory mission without any execution authority."""

    SCHEMA_VERSION = 1
    MAX_TIMEOUT_SECONDS = 86_400
    SAFETY = {
        "execution_allowed": False,
        "execution_influence": "ZERO",
        "strategy_influence": "ZERO",
        "order_influence": "ZERO",
        "paper_only": True,
        "live_trading_enabled": False,
        "broker_submission": False,
        "forced_trade": False,
    }

    def __init__(
        self,
        root: Path,
        *,
        now_provider: Optional[Callable[[], datetime]] = None,
        id_provider: Optional[Callable[[], str]] = None,
    ):
        self.root = Path(root)
        self.state_path = self.root / "mission_state.json"
        self.events = ImmutableStream(self.root / "mission_events.jsonl")
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.id_provider = id_provider or (lambda: f"oracle_mission_{uuid4().hex}")
        self._lock = RLock()
        self._available = True
        self._unavailable_reason: Optional[str] = None
        self._state = self._empty_state()
        self._load()

    def start(
        self,
        *,
        idempotency_key: str,
        instrument_scope: str,
        mode: str = MissionMode.ADVISE.value,
        max_trades: int = 1,
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_available()
            now = self._now()
            self._expire_active(now)

            key = self._required_text(idempotency_key, "idempotency_key", 160)
            existing = next(
                (
                    mission
                    for mission in self._state["missions"]
                    if mission["idempotency_key"] == key
                ),
                None,
            )
            if existing is not None:
                return deepcopy(existing)

            if self._state["active_mission_id"] is not None:
                raise MissionConflictError("An Oracle mission is already active")

            normalized_mode = (
                mode.value if isinstance(mode, MissionMode) else str(mode)
            ).strip().upper()
            if normalized_mode == "LIVE":
                raise MissionValidationError("LIVE mode is forbidden")
            try:
                mission_mode = MissionMode(normalized_mode)
            except ValueError as error:
                raise MissionValidationError("Unsupported Oracle mission mode") from error
            if isinstance(max_trades, bool) or max_trades != 1:
                raise MissionValidationError("max_trades is locked to 1")
            if isinstance(timeout_seconds, bool) or not isinstance(
                timeout_seconds, int
            ):
                raise MissionValidationError("timeout_seconds is invalid")
            timeout = timeout_seconds
            if timeout < 1 or timeout > self.MAX_TIMEOUT_SECONDS:
                raise MissionValidationError(
                    f"timeout_seconds must be between 1 and {self.MAX_TIMEOUT_SECONDS}"
                )

            scope = self._required_text(instrument_scope, "instrument_scope", 160)
            mission_id = self._required_text(self.id_provider(), "mission_id", 200)
            if any(row["mission_id"] == mission_id for row in self._state["missions"]):
                raise MissionStateUnavailableError("Mission ID collision")

            created_at = now.isoformat()
            mission = {
                "schema_version": self.SCHEMA_VERSION,
                "mission_id": mission_id,
                "idempotency_key": key,
                "instrument_scope": scope.upper(),
                "mode": mission_mode.value,
                "status": "ACTIVE",
                "outcome": None,
                "decision": None,
                "contract": None,
                "max_trades": 1,
                "trades_used": 0,
                "execution_allowed": False,
                "forced_trade": False,
                "created_at": created_at,
                "updated_at": created_at,
                "expires_at": (now + timedelta(seconds=timeout)).isoformat(),
                "cancelled_at": None,
                "terminal_reason": None,
                "unavailable_reasons": [],
                "safety": deepcopy(self.SAFETY),
            }
            document = deepcopy(self._state)
            document["missions"].append(mission)
            document["active_mission_id"] = mission_id
            document["updated_at"] = created_at
            self._record_and_persist(
                "MISSION_STARTED",
                mission,
                document,
                idempotency_key=f"{mission_id}:started",
            )
            return deepcopy(mission)

    def active(self) -> Optional[dict[str, Any]]:
        with self._lock:
            self._require_available()
            self._expire_active(self._now())
            mission_id = self._state["active_mission_id"]
            if mission_id is None:
                return None
            return deepcopy(self._mission(mission_id))

    def get(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_available()
            self._expire_active(self._now())
            return deepcopy(self._mission(mission_id))

    def cancel(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_available()
            now = self._now()
            self._expire_active(now)
            mission = self._mission(mission_id)
            if mission["status"] != "ACTIVE":
                return deepcopy(mission)

            updated = deepcopy(mission)
            updated.update(
                {
                    "status": "CANCELLED",
                    "outcome": "NO_TRADE",
                    "updated_at": now.isoformat(),
                    "cancelled_at": now.isoformat(),
                    "terminal_reason": "OPERATOR_CANCELLED",
                }
            )
            document = self._replace_mission(updated)
            document["active_mission_id"] = None
            document["updated_at"] = now.isoformat()
            self._record_and_persist(
                "MISSION_CANCELLED",
                updated,
                document,
                idempotency_key=f"{mission_id}:cancelled",
            )
            return deepcopy(updated)

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            self._require_available()
            self._expire_active(self._now())
            bounded = max(1, min(int(limit), 100))
            return deepcopy(list(reversed(self._state["missions"][-bounded:])))

    def evaluate(
        self,
        mission_id: str,
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Evaluate one cached snapshot and persist its mission outcome."""

        with self._lock:
            self._require_available()
            now = self._now()
            self._expire_active(now)
            mission = self._mission(mission_id)
            if not isinstance(snapshot, Mapping):
                reasons = ("V2_SNAPSHOT_UNAVAILABLE",)
                self._terminalize_evaluation_failure(
                    mission,
                    now,
                    terminal_reason=reasons[0],
                    unavailable_reasons=reasons,
                    message="Cached V2 snapshot is unavailable",
                )
                raise MissionEvaluationUnavailableError(
                    "Cached V2 snapshot is unavailable", reasons
                )
            snapshot_symbol = snapshot.get("symbol")
            if (
                not isinstance(snapshot_symbol, str)
                or snapshot_symbol.strip().upper()
                != mission["instrument_scope"]
            ):
                raise MissionValidationError(
                    "Mission instrument scope does not match cached snapshot"
                )

            try:
                snapshot_hash = self._snapshot_hash(snapshot)
            except MissionEvaluationUnavailableError as error:
                reasons = error.reasons or ("V2_SNAPSHOT_MALFORMED",)
                self._terminalize_evaluation_failure(
                    mission,
                    now,
                    terminal_reason=reasons[0],
                    unavailable_reasons=reasons,
                    message=str(error),
                )
                raise
            idempotency_key = f"{mission_id}:evaluated:{snapshot_hash}"
            existing = next(
                (
                    row
                    for row in self.events.read()
                    if row.get("idempotency_key") == idempotency_key
                ),
                None,
            )
            if existing is not None:
                evaluation = (existing.get("payload") or {}).get("evaluation")
                if not isinstance(evaluation, Mapping):
                    raise MissionStateUnavailableError(
                        "Persisted mission evaluation is invalid"
                    )
                gate_result = evaluation.get("gate_result")
                if not isinstance(gate_result, Mapping):
                    raise MissionStateUnavailableError(
                        "Persisted Gate result is invalid"
                    )
                return deepcopy(dict(gate_result))
            if mission["status"] != "ACTIVE":
                raise MissionConflictError("Oracle mission is not active")

            try:
                result = json.loads(
                    json.dumps(
                        asdict(evaluate_v2_snapshot(snapshot)),
                        sort_keys=True,
                        allow_nan=False,
                    )
                )
            except (SnapshotAdapterError, TypeError, ValueError) as error:
                detail = str(error).strip() or type(error).__name__
                reasons = ("SNAPSHOT_EVALUATION_UNAVAILABLE", detail)
                self._terminalize_evaluation_failure(
                    mission,
                    now,
                    terminal_reason=reasons[0],
                    unavailable_reasons=reasons,
                    message=detail,
                )
                raise MissionEvaluationUnavailableError(
                    f"Cached V2 snapshot cannot be evaluated: {detail}",
                    reasons,
                ) from error
            decision = result.get("decision")
            unavailable_reasons = [
                str(reason)
                for reason in result.get("unavailable_reasons") or ()
                if str(reason).strip()
            ]
            updated = deepcopy(mission)
            updated.update(
                {
                    "decision": decision,
                    "outcome": (
                        "NO_TRADE" if decision == "NO_TRADE" else "QUALIFIED"
                    ),
                    "updated_at": now.isoformat(),
                    "unavailable_reasons": unavailable_reasons,
                }
            )
            if decision == "NO_TRADE":
                updated.update(
                    {
                        "status": "COMPLETED",
                        "terminal_reason": "GATE_NO_TRADE",
                    }
                )
            evaluation = {
                "mission_id": mission_id,
                "snapshot_hash": snapshot_hash,
                "evaluated_at": now.isoformat(),
                "gate_result": result,
            }
            document = self._replace_mission(updated)
            if updated["status"] != "ACTIVE":
                document["active_mission_id"] = None
            document["updated_at"] = now.isoformat()
            self._record_and_persist(
                "MISSION_EVALUATED",
                updated,
                document,
                idempotency_key=idempotency_key,
                event_payload={"evaluation": evaluation},
                recorded_at=now.isoformat(),
            )
            return deepcopy(result)

    def fail_evaluation(
        self,
        mission_id: str,
        *,
        terminal_reason: str,
        unavailable_reasons: tuple[str, ...],
        message: str,
    ) -> dict[str, Any]:
        """Persist a fail-closed terminal outcome for a pre-evaluation failure."""

        with self._lock:
            self._require_available()
            now = self._now()
            self._expire_active(now)
            mission = self._mission(mission_id)
            if mission["status"] != "ACTIVE":
                return deepcopy(mission)
            return self._terminalize_evaluation_failure(
                mission,
                now,
                terminal_reason=terminal_reason,
                unavailable_reasons=unavailable_reasons,
                message=message,
            )

    def plan(
        self,
        mission_id: str,
        snapshot: Mapping[str, Any],
        *,
        requested_quantity: Optional[int] = None,
    ) -> dict[str, Any]:
        """Create one reserved advisory plan from the latest evaluation."""

        with self._lock:
            self._require_available()
            now = self._now()
            self._expire_active(now)
            mission = self._mission(mission_id)
            if mission["status"] != "ACTIVE":
                if mission.get("outcome") == "NO_TRADE":
                    reason = (
                        "MISSION_EVALUATION_FAILED"
                        if mission["status"] == "FAILED"
                        else "GATE_NO_TRADE"
                    )
                    raise MissionPlanUnavailableError(
                        "Terminal NO_TRADE mission cannot create a plan",
                        (reason,),
                    )
                raise MissionConflictError("Oracle mission is not active")
            if not isinstance(snapshot, Mapping):
                raise MissionPlanUnavailableError(
                    "Cached V2 snapshot is unavailable",
                    ("V2_SNAPSHOT_UNAVAILABLE",),
                )

            rows = self.events.read()
            latest_evaluation = next(
                (
                    (row.get("payload") or {}).get("evaluation")
                    for row in reversed(rows)
                    if row.get("event_type") == "MISSION_EVALUATED"
                    and ((row.get("payload") or {}).get("mission") or {}).get(
                        "mission_id"
                    )
                    == mission_id
                ),
                None,
            )
            if not isinstance(latest_evaluation, Mapping):
                raise MissionPlanUnavailableError(
                    "Mission has no persisted evaluation",
                    ("MISSION_EVALUATION_UNAVAILABLE",),
                )
            evaluation_hash = latest_evaluation.get("snapshot_hash")
            if (
                not isinstance(evaluation_hash, str)
                or self._snapshot_hash(snapshot) != evaluation_hash
            ):
                raise MissionPlanUnavailableError(
                    "Cached snapshot no longer matches the latest evaluation",
                    ("EVALUATION_SNAPSHOT_MISMATCH",),
                )

            existing = next(
                (
                    (row.get("payload") or {}).get("plan")
                    for row in rows
                    if row.get("event_type") == "PLAN_CREATED"
                    and ((row.get("payload") or {}).get("mission") or {}).get(
                        "mission_id"
                    )
                    == mission_id
                ),
                None,
            )
            if existing is not None:
                if not isinstance(existing, Mapping):
                    raise MissionStateUnavailableError(
                        "Persisted Oracle plan is invalid"
                    )
                if existing.get("evaluation_snapshot_hash") != evaluation_hash:
                    raise MissionConflictError(
                        "Oracle mission already has a different plan"
                    )
                return deepcopy(dict(existing))

            reservations = self._reservation_totals(rows)
            try:
                plan = OracleTradePlanner.create(
                    mission_id=mission_id,
                    evaluation=latest_evaluation,
                    snapshot=snapshot,
                    reserved_risk=reservations["risk"],
                    reserved_capital=reservations["capital"],
                    now=now,
                    requested_quantity=requested_quantity,
                )
            except TradePlanError as error:
                raise MissionPlanUnavailableError(
                    "Oracle trade plan was rejected",
                    error.reasons,
                ) from error

            document = deepcopy(self._state)
            document["updated_at"] = now.isoformat()
            self._record_and_persist(
                "PLAN_CREATED",
                mission,
                document,
                idempotency_key=f"{mission_id}:plan:{evaluation_hash}",
                event_payload={"plan": plan},
                recorded_at=now.isoformat(),
            )
            return deepcopy(plan)

    def plan_demo(
        self,
        mission_id: str,
        snapshot: Mapping[str, Any],
        *,
        option_type: str,
        lots: int,
    ) -> dict[str, Any]:
        """Create an isolated demo plan without claiming directional evidence."""
        with self._lock:
            self._require_available()
            now = self._now()
            mission = self._mission(mission_id)
            if mission["status"] != "ACTIVE" or mission["mode"] != "DEMO_PAPER":
                raise MissionConflictError("Demo mission is not active")
            rows = self.events.read()
            existing = next(
                (
                    (row.get("payload") or {}).get("plan")
                    for row in rows
                    if row.get("event_type") == "PLAN_CREATED"
                    and ((row.get("payload") or {}).get("mission") or {}).get(
                        "mission_id"
                    )
                    == mission_id
                ),
                None,
            )
            if isinstance(existing, Mapping):
                return deepcopy(dict(existing))
            try:
                plan = OracleTradePlanner.create_demo(
                    mission_id=mission_id,
                    snapshot=snapshot,
                    option_type=option_type,
                    lots=lots,
                    now=now,
                )
            except TradePlanError as error:
                raise MissionPlanUnavailableError(
                    "Oracle demo plan was rejected", error.reasons
                ) from error
            updated = deepcopy(mission)
            updated.update(
                {
                    "decision": option_type,
                    "outcome": "DEMO_PLANNED",
                    "contract": plan["contract"],
                    "updated_at": now.isoformat(),
                }
            )
            document = self._replace_mission(updated)
            document["updated_at"] = now.isoformat()
            self._record_and_persist(
                "PLAN_CREATED",
                updated,
                document,
                idempotency_key=f"{mission_id}:demo-plan",
                event_payload={"plan": plan},
                recorded_at=now.isoformat(),
            )
            return deepcopy(plan)

    def complete_demo(self, mission_id: str, *, outcome: str = "CLOSED") -> dict[str, Any]:
        with self._lock:
            self._require_available()
            mission = self._mission(mission_id)
            if mission["mode"] != "DEMO_PAPER":
                raise MissionConflictError("Mission is not a demo mission")
            if mission["status"] != "ACTIVE":
                return deepcopy(mission)
            now = self._now()
            updated = deepcopy(mission)
            updated.update(
                {
                    "status": "COMPLETED",
                    "outcome": outcome,
                    "trades_used": 1 if outcome == "CLOSED" else 0,
                    "updated_at": now.isoformat(),
                    "terminal_reason": f"DEMO_{outcome}",
                }
            )
            document = self._replace_mission(updated)
            document["active_mission_id"] = None
            document["updated_at"] = now.isoformat()
            self._record_and_persist(
                "DEMO_MISSION_COMPLETED",
                updated,
                document,
                idempotency_key=f"{mission_id}:demo-completed",
                recorded_at=now.isoformat(),
            )
            return deepcopy(updated)

    def reservation_status(self) -> dict[str, Any]:
        with self._lock:
            self._require_available()
            self._expire_active(self._now())
            totals = self._reservation_totals(self.events.read())
            return {
                "reserved_risk": round(totals["risk"], 2),
                "reserved_capital": round(totals["capital"], 2),
                "active_plan_count": totals["count"],
                "execution_allowed": False,
            }

    def state_status(self) -> dict[str, Any]:
        return {
            "status": "AVAILABLE" if self._available else "UNAVAILABLE",
            "reason": self._unavailable_reason,
            "execution_allowed": False,
            "execution_influence": "ZERO",
        }

    def _load(self) -> None:
        try:
            state_exists = self.state_path.exists()
            if self.state_path.exists():
                document = self._read_state()
            else:
                document = self._empty_state()
            integrity = self.events.verify()
            if not integrity["valid"]:
                raise ValueError("mission event hash chain invalid")
            rows = self.events.read()
            self._validate_state(document)
            self._validate_event_checkpoint(document, rows)
            restored = self._restore_from_events(self._empty_state(), rows)
            restored["event_records"] = len(rows)
            restored["event_head"] = (
                rows[-1]["record_hash"] if rows else "GENESIS"
            )
            restored["updated_at"] = (
                rows[-1]["recorded_at"] if rows else document.get("updated_at")
            )
            if document["event_records"] == len(rows) and (
                document["missions"] != restored["missions"]
                or document["active_mission_id"] != restored["active_mission_id"]
            ):
                raise ValueError("mission snapshot does not match event history")
            self._validate_state(restored)
            if (state_exists or rows) and document != restored:
                _atomic_write(self.state_path, restored)
            self._state = restored
            active_id = self._state["active_mission_id"]
            if active_id is not None:
                active = self._mission(active_id)
                if active.get("outcome") is None and active.get("mode") != "DEMO_PAPER":
                    self._terminalize_evaluation_failure(
                        active,
                        self._now(),
                        terminal_reason="RESTART_RECOVERY_NO_OUTCOME",
                        unavailable_reasons=("RESTART_RECOVERY_NO_OUTCOME",),
                        message=(
                            "Active mission had no persisted outcome during restart"
                        ),
                    )
        except (OSError, ValueError, TypeError, RuntimeError):
            self._available = False
            self._unavailable_reason = "MISSION_STATE_CORRUPT"
            self._state = self._empty_state()

    def _restore_from_events(
        self,
        document: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        restored = deepcopy(document)
        by_id = {
            mission["mission_id"]: mission
            for mission in restored.get("missions", [])
            if isinstance(mission, Mapping) and mission.get("mission_id")
        }
        order = [
            mission["mission_id"]
            for mission in restored.get("missions", [])
            if isinstance(mission, Mapping) and mission.get("mission_id")
        ]
        for row in rows:
            mission = (row.get("payload") or {}).get("mission")
            if not isinstance(mission, Mapping):
                raise ValueError("mission event payload invalid")
            mission_id = mission.get("mission_id")
            if not isinstance(mission_id, str) or not mission_id:
                raise ValueError("mission event ID invalid")
            if mission_id not in by_id:
                order.append(mission_id)
            by_id[mission_id] = dict(mission)
        restored["missions"] = [by_id[mission_id] for mission_id in order]
        active_ids = [
            mission["mission_id"]
            for mission in restored["missions"]
            if mission.get("status") == "ACTIVE"
        ]
        if len(active_ids) > 1:
            raise ValueError("multiple active missions")
        restored["active_mission_id"] = active_ids[0] if active_ids else None
        return restored

    def _expire_active(self, now: datetime) -> None:
        mission_id = self._state["active_mission_id"]
        if mission_id is None:
            return
        mission = self._mission(mission_id)
        expires_at = self._parse_timestamp(mission["expires_at"])
        if now < expires_at:
            return

        updated = deepcopy(mission)
        updated.update(
            {
                "status": "EXPIRED",
                "outcome": "NO_TRADE",
                "updated_at": now.isoformat(),
                "terminal_reason": "TIMEOUT",
            }
        )
        document = self._replace_mission(updated)
        document["active_mission_id"] = None
        document["updated_at"] = now.isoformat()
        self._record_and_persist(
            "MISSION_EXPIRED",
            updated,
            document,
            idempotency_key=f"{mission_id}:expired",
        )

    def _terminalize_evaluation_failure(
        self,
        mission: Mapping[str, Any],
        now: datetime,
        *,
        terminal_reason: str,
        unavailable_reasons: tuple[str, ...],
        message: str,
    ) -> dict[str, Any]:
        if mission["status"] != "ACTIVE":
            return deepcopy(dict(mission))
        reasons = [
            str(reason)
            for reason in unavailable_reasons
            if str(reason).strip()
        ]
        updated = deepcopy(dict(mission))
        updated.update(
            {
                "status": "FAILED",
                "outcome": "NO_TRADE",
                "decision": "NO_TRADE",
                "updated_at": now.isoformat(),
                "terminal_reason": str(terminal_reason),
                "unavailable_reasons": reasons,
            }
        )
        document = self._replace_mission(updated)
        document["active_mission_id"] = None
        document["updated_at"] = now.isoformat()
        self._record_and_persist(
            "MISSION_EVALUATION_FAILED",
            updated,
            document,
            idempotency_key=f"{mission['mission_id']}:evaluation-failed",
            event_payload={
                "failure": {
                    "message": str(message),
                    "reasons": reasons,
                }
            },
            recorded_at=now.isoformat(),
        )
        return deepcopy(updated)

    def _record_and_persist(
        self,
        event_type: str,
        mission: Mapping[str, Any],
        document: dict[str, Any],
        *,
        idempotency_key: str,
        event_payload: Optional[Mapping[str, Any]] = None,
        recorded_at: Optional[str] = None,
    ) -> None:
        try:
            self.events.append(
                event_type,
                {"mission": mission, **dict(event_payload or {})},
                recorded_at=recorded_at or mission["updated_at"],
                idempotency_key=idempotency_key,
            )
            rows = self.events.read()
            integrity = self.events.verify()
            if not integrity["valid"]:
                raise ValueError("mission event hash chain invalid")
            document["event_records"] = len(rows)
            document["event_head"] = (
                rows[-1]["record_hash"] if rows else "GENESIS"
            )
            _atomic_write(self.state_path, document)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            self._available = False
            self._unavailable_reason = "MISSION_STATE_WRITE_FAILED"
            raise MissionStateUnavailableError(
                "Oracle mission state could not be persisted"
            ) from error
        self._state = document

    @staticmethod
    def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
        stable = deepcopy(dict(snapshot))
        polling = stable.get("polling")
        if isinstance(polling, Mapping):
            stable["polling"] = {
                key: value
                for key, value in polling.items()
                if key
                not in {
                    "delivery",
                    "projection_age_ms",
                    "refresh_in_progress",
                    "overlap_skipped",
                    "served_from_cache",
                }
            }
        try:
            canonical = json.dumps(
                stable,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise MissionEvaluationUnavailableError(
                "Cached V2 snapshot is malformed",
                ("V2_SNAPSHOT_MALFORMED",),
            ) from error
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _reservation_totals(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        active_ids = {
            mission["mission_id"]
            for mission in self._state["missions"]
            if mission.get("status") == "ACTIVE"
        }
        plans: dict[str, Mapping[str, Any]] = {}
        released_ids = {
            ((row.get("payload") or {}).get("mission") or {}).get("mission_id")
            for row in rows
            if row.get("event_type")
            in {"EXECUTION_CLOSED", "EXECUTION_REJECTED", "EXECUTION_FAILED"}
        }
        for row in rows:
            if row.get("event_type") != "PLAN_CREATED":
                continue
            payload = row.get("payload") or {}
            mission_id = (payload.get("mission") or {}).get("mission_id")
            plan = payload.get("plan")
            if (
                mission_id in active_ids
                and mission_id not in released_ids
                and isinstance(plan, Mapping)
            ):
                plans[mission_id] = plan
        return {
            "risk": sum(
                float(plan.get("total_maximum_risk") or 0.0)
                for plan in plans.values()
            ),
            "capital": sum(
                float(plan.get("capital_reserved") or 0.0)
                for plan in plans.values()
            ),
            "count": len(plans),
        }

    def _read_state(self) -> dict[str, Any]:
        import json

        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("mission state unreadable") from error
        if not isinstance(value, dict):
            raise ValueError("mission state must be an object")
        return value

    def _validate_state(self, document: Mapping[str, Any]) -> None:
        if document.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("mission state schema invalid")
        missions = document.get("missions")
        if not isinstance(missions, list):
            raise ValueError("mission state list invalid")
        seen: set[str] = set()
        active: list[str] = []
        for mission in missions:
            if not isinstance(mission, Mapping):
                raise ValueError("mission record invalid")
            mission_id = mission.get("mission_id")
            if not isinstance(mission_id, str) or not mission_id or mission_id in seen:
                raise ValueError("mission ID invalid")
            seen.add(mission_id)
            if mission.get("mode") not in {mode.value for mode in MissionMode}:
                raise ValueError("mission mode invalid")
            if mission.get("status") not in {
                "ACTIVE",
                "CANCELLED",
                "COMPLETED",
                "EXPIRED",
                "FAILED",
            }:
                raise ValueError("mission status invalid")
            if mission.get("max_trades") != 1:
                raise ValueError("mission trade limit invalid")
            if mission.get("trades_used") != 0:
                raise ValueError("mission trade usage invalid")
            if mission.get("execution_allowed") is not False:
                raise ValueError("mission execution boundary invalid")
            if mission.get("forced_trade") is not False:
                raise ValueError("mission forced-trade boundary invalid")
            if mission.get("contract") is not None:
                raise ValueError("mission contract must remain unreported")
            unavailable_reasons = mission.get("unavailable_reasons", [])
            if (
                not isinstance(unavailable_reasons, list)
                or any(
                    not isinstance(reason, str) or not reason
                    for reason in unavailable_reasons
                )
            ):
                raise ValueError("mission unavailable reasons invalid")
            if mission.get("safety") != self.SAFETY:
                raise ValueError("mission safety metadata invalid")
            self._parse_timestamp(mission.get("created_at"))
            self._parse_timestamp(mission.get("updated_at"))
            self._parse_timestamp(mission.get("expires_at"))
            if mission.get("status") == "ACTIVE":
                if mission.get("outcome") not in {None, "QUALIFIED"}:
                    raise ValueError("active mission outcome invalid")
                if (
                    mission.get("outcome") is None
                    and mission.get("decision") is not None
                ):
                    raise ValueError("unevaluated mission decision invalid")
                if (
                    mission.get("outcome") == "QUALIFIED"
                    and mission.get("decision") not in {"CALL", "PUT"}
                ):
                    raise ValueError("qualified mission decision invalid")
                active.append(mission_id)
            elif mission.get("outcome") != "NO_TRADE":
                raise ValueError("terminal mission outcome invalid")
            elif mission.get("status") in {"COMPLETED", "FAILED"} and (
                mission.get("decision") != "NO_TRADE"
            ):
                raise ValueError("terminal mission decision invalid")
        if len(active) > 1:
            raise ValueError("multiple active missions")
        active_id = document.get("active_mission_id")
        if active_id != (active[0] if active else None):
            raise ValueError("active mission pointer invalid")
        event_records = document.get("event_records")
        event_head = document.get("event_head")
        if (
            isinstance(event_records, bool)
            or not isinstance(event_records, int)
            or event_records < 0
        ):
            raise ValueError("mission event count invalid")
        if not isinstance(event_head, str) or not event_head:
            raise ValueError("mission event head invalid")
        if event_records == 0 and event_head != "GENESIS":
            raise ValueError("mission event checkpoint invalid")
        if missions and event_records == 0:
            raise ValueError("mission history is missing")

    @staticmethod
    def _validate_event_checkpoint(
        document: Mapping[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        recorded = document["event_records"]
        if recorded > len(rows):
            raise ValueError("mission event history was truncated")
        if recorded == 0:
            if document["event_head"] != "GENESIS":
                raise ValueError("mission event checkpoint invalid")
            return
        if rows[recorded - 1].get("record_hash") != document["event_head"]:
            raise ValueError("mission event checkpoint diverged")

    def _mission(self, mission_id: str) -> dict[str, Any]:
        normalized = str(mission_id).strip()
        mission = next(
            (
                row
                for row in self._state["missions"]
                if row["mission_id"] == normalized
            ),
            None,
        )
        if mission is None:
            raise MissionNotFoundError("Oracle mission was not found")
        return mission

    def _replace_mission(self, updated: Mapping[str, Any]) -> dict[str, Any]:
        document = deepcopy(self._state)
        document["missions"] = [
            dict(updated) if row["mission_id"] == updated["mission_id"] else row
            for row in document["missions"]
        ]
        return document

    def _require_available(self) -> None:
        if not self._available:
            raise MissionStateUnavailableError(
                self._unavailable_reason or "Oracle mission state is unavailable"
            )

    def _now(self) -> datetime:
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise MissionStateUnavailableError(
                "Oracle mission clock must be timezone-aware"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _required_text(value: Any, field: str, maximum: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > maximum:
            raise MissionValidationError(f"{field} is invalid")
        return normalized

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if not isinstance(value, str):
            raise MissionStateUnavailableError("Mission timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise MissionStateUnavailableError(
                "Mission timestamp is invalid"
            ) from error
        if parsed.tzinfo is None:
            raise MissionStateUnavailableError("Mission timestamp is invalid")
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _empty_state(cls) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "active_mission_id": None,
            "missions": [],
            "event_records": 0,
            "event_head": "GENESIS",
            "updated_at": None,
        }
