"""Paper-only Oracle execution through OpenAlgo Analyzer and a durable Guardian."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

import requests

from src.execution.paper_state import (
    DuplicatePaperEvent,
    PaperStateService,
)
from src.strategy_lab.storage import ImmutableStream, _atomic_write


IST = ZoneInfo("Asia/Kolkata")
TERMINAL = {"CLOSED", "REJECTED", "FAILED"}
STATES = {
    "PLANNED",
    "SUBMITTING",
    "OPEN",
    "EXITING",
    "CLOSED",
    "REJECTED",
    "FAILED",
    "RECONCILIATION_REQUIRED",
}


class OracleExecutionError(RuntimeError):
    code = "ORACLE_EXECUTION_ERROR"


class OracleExecutionBlocked(OracleExecutionError):
    code = "ORACLE_EXECUTION_BLOCKED"


class OracleExecutionUnavailable(OracleExecutionError):
    code = "ORACLE_EXECUTION_UNAVAILABLE"


class OpenAlgoAnalyzerClient:
    """Small fail-closed HTTP adapter; credentials are never returned or persisted."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 4.0,
        session: Optional[requests.Session] = None,
    ):
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        if normalized_base_url.endswith("/api/v1"):
            normalized_base_url = normalized_base_url[: -len("/api/v1")]
        self.base_url = normalized_base_url.rstrip("/")
        self.api_key = str(api_key or "")
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def analyzer(self) -> Mapping[str, Any]:
        if not self.configured:
            raise OracleExecutionUnavailable("OPENALGO_CONFIG_UNAVAILABLE")
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/analyzer",
                json={"apikey": self.api_key},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise OracleExecutionUnavailable("OPENALGO_UNREACHABLE") from error

        if 300 <= response.status_code < 400:
            raise OracleExecutionUnavailable("AUTH_REDIRECT_ERROR")

        media_type = str(response.headers.get("Content-Type") or "").split(
            ";", 1
        )[0].strip().lower()
        if media_type != "application/json" and not media_type.endswith("+json"):
            code = (
                "AUTH_OR_ROUTE_ERROR"
                if response.status_code == 200
                else "OPENALGO_RESPONSE_INVALID"
            )
            raise OracleExecutionUnavailable(code)
        try:
            body = response.json()
        except ValueError as error:
            raise OracleExecutionUnavailable("OPENALGO_RESPONSE_INVALID") from error
        if not isinstance(body, Mapping):
            raise OracleExecutionUnavailable("OPENALGO_RESPONSE_INVALID")
        if response.status_code != 200 or body.get("status") != "success":
            raise OracleExecutionUnavailable("AUTH_OR_ROUTE_ERROR")
        data = body.get("data")
        if (
            not isinstance(data, Mapping)
            or type(data.get("analyze_mode")) is not bool
            or not isinstance(data.get("mode"), str)
        ):
            raise OracleExecutionUnavailable("OPENALGO_RESPONSE_INVALID")
        result = dict(body)
        result["_http_status"] = response.status_code
        return result

    def place(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._post(
            "/api/v1/placeorder", {"apikey": self.api_key, **dict(payload)}
        )

    def lookup(self, client_order_id: str) -> Mapping[str, Any]:
        return self._post(
            "/api/v1/orderbyclientid",
            {"apikey": self.api_key, "client_order_id": client_order_id},
        )

    def order_status(self, order_id: str) -> Mapping[str, Any]:
        return self._post(
            "/api/v1/orderstatus",
            {"apikey": self.api_key, "strategy": "ORACLE", "orderid": order_id},
        )

    def _post(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.configured:
            raise OracleExecutionUnavailable("OPENALGO_CONFIG_UNAVAILABLE")
        try:
            response = self.session.post(
                f"{self.base_url}{path}", json=dict(payload), timeout=self.timeout
            )
        except requests.RequestException as error:
            raise OracleExecutionUnavailable("OPENALGO_UNREACHABLE") from error
        try:
            body = response.json()
        except ValueError as error:
            raise OracleExecutionUnavailable("OPENALGO_RESPONSE_INVALID") from error
        if not isinstance(body, Mapping):
            raise OracleExecutionUnavailable("OPENALGO_RESPONSE_INVALID")
        result = dict(body)
        result["_http_status"] = response.status_code
        return result


class OraclePaperAutopilot:
    """Exactly-once Analyzer execution and paper-position Guardian."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        root: Path,
        *,
        missions,
        openalgo: OpenAlgoAnalyzerClient,
        paper_state: PaperStateService,
        snapshot_provider: Callable[[], Mapping[str, Any]],
        now_provider: Optional[Callable[[], datetime]] = None,
    ):
        self.root = Path(root)
        self.state_path = self.root / "guardian_state.json"
        self.events = ImmutableStream(self.root / "execution_events.jsonl")
        self.journal = ImmutableStream(self.root / "execution_journal.jsonl")
        self.missions = missions
        self.openalgo = openalgo
        self.paper_state = paper_state
        self.snapshot_provider = snapshot_provider
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._available = True
        self._reason: Optional[str] = None
        self._state: dict[str, Any] = self._empty()
        self._load()

    def execute(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            mission, plan = self._mission_and_plan(mission_id)
            if mission["mode"] not in {"CONFIRM", "PAPER_AUTOPILOT", "DEMO_PAPER"}:
                raise OracleExecutionBlocked("ADVISE_MISSION_CANNOT_EXECUTE")
            current = self._state["guardians"].get(mission_id)
            if current:
                if current["plan_id"] != plan["plan_id"]:
                    raise OracleExecutionBlocked("MISSION_PLAN_CONFLICT")
                if current["state"] in {
                    "SUBMITTING",
                    "EXITING",
                    "RECONCILIATION_REQUIRED",
                }:
                    current = self._reconcile(current)
                return self._public(current)

            self._validate_plan(plan)
            self._require_analyzer()
            entry_key = self._client_id("e", plan["plan_id"])
            guardian = {
                "schema_version": self.SCHEMA_VERSION,
                "mission_id": mission_id,
                "plan_id": plan["plan_id"],
                "state": "PLANNED",
                "contract": plan["contract"],
                "underlying": plan["underlying"],
                "security_id": str(plan["security_id"]),
                "option_type": plan.get("option_type"),
                "strike": plan.get("strike"),
                "expiry": plan.get("expiry"),
                "lot_size": int(plan["lot_size"]),
                "approved_quantity": int(plan["approved_quantity"]),
                "filled_quantity": 0,
                "entry_fill_price": None,
                "entry_client_order_id": entry_key,
                "entry_order_id": None,
                "exit_client_order_id": None,
                "exit_order_id": None,
                "initial_stop": float(plan["final_sl"]),
                "current_stop": float(plan["final_sl"]),
                "structural_invalidation": float(plan["structural_invalidation"]),
                "mapped_premium_sl": plan.get("mapped_premium_sl"),
                "target_1": float(plan["target_1"]),
                "target_2": float(plan["target_2"]),
                "trail_start": float(plan["trail_start"]),
                "trail_rule": plan["trail_rule"],
                "time_exit": plan["time_exit"],
                "max_hold_seconds": plan.get("max_hold_seconds"),
                "opened_at": None,
                "execution_origin": plan.get("execution_origin", "ORACLE"),
                "directional_edge": plan.get("directional_edge"),
                "exclude_from_strategy_stats": bool(plan.get("exclude_from_strategy_stats")),
                "exclude_from_backtests": bool(plan.get("exclude_from_backtests")),
                "exclude_from_performance_metrics": bool(plan.get("exclude_from_performance_metrics")),
                "high_watermark": None,
                "break_even_done": False,
                "trailing_active": False,
                "exit_reason": None,
                "last_quote": None,
                "last_quote_timestamp": None,
                "health": "READY",
                "reason": None,
                "created_at": self._now().isoformat(),
                "updated_at": self._now().isoformat(),
                "last_heartbeat": None,
                "paper_position_id": f"oracle_{plan['plan_id']}",
            }
            self._transition(guardian, "SUBMITTING", "ENTRY_SUBMISSION_STARTED")
            payload = self._entry_payload(plan, entry_key)
            try:
                response = self.openalgo.place(payload)
            except OracleExecutionUnavailable:
                self._transition(
                    guardian,
                    "RECONCILIATION_REQUIRED",
                    "ENTRY_SUBMISSION_OUTCOME_UNCERTAIN",
                )
                return self._public(guardian)
            return self._public(self._accept_submission(guardian, response, entry=True))

    def guardian(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_available()
            current = self._state["guardians"].get(mission_id)
            if not current:
                mission, plan = self._mission_and_plan(mission_id)
                return {
                    "mission_id": mission["mission_id"],
                    "plan_id": plan["plan_id"],
                    "state": "PLANNED",
                    "health": "READY",
                    **self._safety(),
                }
            if current["state"] in {
                "SUBMITTING",
                "EXITING",
                "RECONCILIATION_REQUIRED",
            }:
                current = self._reconcile(current)
            if current["state"] == "OPEN":
                self._heartbeat(current)
            return self._public(current)

    def exit(self, mission_id: str, reason: str = "MANUAL_EXIT_NOW") -> dict[str, Any]:
        with self._lock:
            self._require_available()
            guardian = self._state["guardians"].get(mission_id)
            if not guardian:
                raise OracleExecutionBlocked("GUARDIAN_NOT_OPEN")
            if guardian["state"] in {"EXITING", "CLOSED"}:
                return self._public(guardian)
            if guardian["state"] != "OPEN":
                raise OracleExecutionBlocked("GUARDIAN_NOT_OPEN")
            return self._public(self._begin_exit(guardian, reason))

    def recover(self) -> dict[str, Any]:
        with self._lock:
            for guardian in list(self._state["guardians"].values()):
                if guardian["state"] in {
                    "SUBMITTING",
                    "EXITING",
                    "RECONCILIATION_REQUIRED",
                }:
                    self._reconcile(guardian)
            return {
                "status": "AVAILABLE" if self._available else "UNAVAILABLE",
                "guardians": len(self._state["guardians"]),
                "reason": self._reason,
            }

    def has_active_execution(self, mission_id: str) -> bool:
        """Prevent mission cancellation from orphaning a submitted/open order."""
        with self._lock:
            self._require_available()
            guardian = self._state["guardians"].get(mission_id)
            return bool(guardian and guardian.get("state") not in TERMINAL)

    def _heartbeat(self, guardian: dict[str, Any]) -> None:
        now = self._now()
        guardian["last_heartbeat"] = now.isoformat()
        try:
            analyzer = self.openalgo.analyzer()
        except OracleExecutionUnavailable:
            guardian["health"] = "DISCONNECTED"
            guardian["reason"] = "OPENALGO_DISCONNECTED"
            self._persist(guardian, "GUARDIAN_HEARTBEAT_DISCONNECTED")
            return
        analyzer_data = analyzer.get("data")
        analyze_mode = (
            analyzer_data.get("analyze_mode")
            if isinstance(analyzer_data, Mapping)
            else analyzer.get("analyze_mode")
        )
        mode = (
            analyzer_data.get("mode")
            if isinstance(analyzer_data, Mapping)
            else analyzer.get("mode")
        )
        if (
            analyzer.get("status") != "success"
            or analyze_mode is not True
            or mode != "analyze"
        ):
            guardian["health"] = "DISCONNECTED"
            guardian["reason"] = "OPENALGO_ANALYZER_OFF"
            self._persist(guardian, "GUARDIAN_HEARTBEAT_DISCONNECTED")
            return
        try:
            snapshot = self.snapshot_provider()
            quote = self._held_quote(snapshot, guardian["security_id"])
        except (RuntimeError, ValueError, TypeError):
            guardian["health"] = "STALE"
            guardian["reason"] = "HELD_CONTRACT_QUOTE_UNAVAILABLE"
            self._persist(guardian, "GUARDIAN_HEARTBEAT_STALE")
            return
        guardian["last_quote"] = quote["price"]
        guardian["last_quote_timestamp"] = quote["timestamp"]
        if not quote["fresh"]:
            guardian["health"] = "STALE"
            guardian["reason"] = "HELD_CONTRACT_QUOTE_STALE"
            self._persist(guardian, "GUARDIAN_HEARTBEAT_STALE")
            return
        guardian["health"] = "HEALTHY"
        guardian["reason"] = None
        price = quote["price"]
        guardian["high_watermark"] = max(
            price, float(guardian["high_watermark"] or price)
        )
        underlying = self._underlying_quote(snapshot)
        if underlying is not None:
            invalidated = (
                guardian.get("option_type") == "CE"
                and underlying <= float(guardian["structural_invalidation"])
            ) or (
                guardian.get("option_type") == "PE"
                and underlying >= float(guardian["structural_invalidation"])
            )
            if invalidated:
                self._begin_exit(guardian, "STRUCTURAL_INVALIDATION")
                return
        if price <= float(guardian["current_stop"]):
            self._begin_exit(guardian, "STOP_LOSS")
            return
        if price >= float(guardian["target_2"]):
            self._begin_exit(guardian, "TARGET_2")
            return
        if price >= float(guardian["target_1"]):
            guardian["break_even_done"] = True
            guardian["trailing_active"] = True
            guardian["current_stop"] = max(
                float(guardian["current_stop"]),
                float(guardian["entry_fill_price"]),
                float(guardian["high_watermark"])
                - (
                    float(guardian["entry_fill_price"])
                    - float(guardian["initial_stop"])
                ),
            )
        if now.astimezone(IST).time() >= time(15, 20):
            self._begin_exit(guardian, "TIME_EXIT")
            return
        if guardian.get("max_hold_seconds") and guardian.get("opened_at"):
            opened = datetime.fromisoformat(str(guardian["opened_at"]).replace("Z", "+00:00"))
            if (now - opened.astimezone(timezone.utc)).total_seconds() >= int(guardian["max_hold_seconds"]):
                self._begin_exit(guardian, "DEMO_TIMED_EXIT")
                return
        try:
            position = self.paper_state.update_mark(
                guardian["paper_position_id"],
                price,
                self._event_id(guardian, f"mark:{quote['timestamp']}"),
                stop_price=guardian["current_stop"],
                break_even_done=guardian["break_even_done"],
                trailing_active=guardian["trailing_active"],
            )
            guardian["current_stop"] = position.stop_price
        except DuplicatePaperEvent:
            pass
        self._persist(guardian, "GUARDIAN_HEARTBEAT")

    def _begin_exit(self, guardian: dict[str, Any], reason: str) -> dict[str, Any]:
        key = guardian.get("exit_client_order_id") or self._client_id(
            "x", f"{guardian['plan_id']}:{reason}"
        )
        guardian["exit_client_order_id"] = key
        guardian["exit_reason"] = str(reason)
        self._transition(guardian, "EXITING", f"EXIT_{reason}")
        payload = {
            "client_order_id": key,
            "strategy": "ORACLE",
            "exchange": self._exchange(guardian.get("option_type")),
            "symbol": guardian["contract"],
            "action": "SELL",
            "quantity": int(guardian["filled_quantity"]),
            "pricetype": "MARKET",
            "product": "MIS",
            "price": 0,
            "trigger_price": 0,
            "disclosed_quantity": 0,
        }
        try:
            response = self.openalgo.place(payload)
        except OracleExecutionUnavailable:
            self._transition(
                guardian,
                "RECONCILIATION_REQUIRED",
                "EXIT_SUBMISSION_OUTCOME_UNCERTAIN",
            )
            return guardian
        return self._accept_submission(guardian, response, entry=False)

    def _accept_submission(
        self, guardian: dict[str, Any], response: Mapping[str, Any], *, entry: bool
    ) -> dict[str, Any]:
        status = int(response.get("_http_status") or 0)
        if status == 409:
            self._transition(guardian, "FAILED", "IDEMPOTENCY_CONFLICT")
            return guardian
        if status >= 400 or response.get("status") != "success":
            self._transition(
                guardian,
                "REJECTED",
                "OPENALGO_ORDER_REJECTED",
            )
            return guardian
        order_id = response.get("orderid")
        if not isinstance(order_id, (str, int)) or not str(order_id):
            self._transition(
                guardian,
                "RECONCILIATION_REQUIRED",
                "OPENALGO_ORDER_ID_UNAVAILABLE",
            )
            return guardian
        guardian["entry_order_id" if entry else "exit_order_id"] = str(order_id)
        return self._reconcile(guardian)

    def _reconcile(self, guardian: dict[str, Any]) -> dict[str, Any]:
        entry = guardian["state"] == "SUBMITTING" or (
            guardian["state"] == "RECONCILIATION_REQUIRED"
            and not guardian.get("entry_fill_price")
        )
        client_id = (
            guardian["entry_client_order_id"]
            if entry
            else guardian.get("exit_client_order_id")
        )
        if not client_id:
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "CLIENT_ORDER_ID_UNAVAILABLE"
            )
            return guardian
        try:
            lookup = self.openalgo.lookup(client_id)
        except OracleExecutionUnavailable:
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "OPENALGO_LOOKUP_UNAVAILABLE"
            )
            return guardian
        if int(lookup.get("_http_status") or 0) == 404:
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "REMOTE_ORDER_NOT_FOUND"
            )
            return guardian
        order_id = lookup.get("orderid")
        if not order_id:
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "REMOTE_ORDER_ID_UNAVAILABLE"
            )
            return guardian
        guardian["entry_order_id" if entry else "exit_order_id"] = str(order_id)
        try:
            status = self.openalgo.order_status(str(order_id))
        except OracleExecutionUnavailable:
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "ORDER_STATUS_UNAVAILABLE"
            )
            return guardian
        data = status.get("data")
        if not isinstance(data, Mapping):
            self._transition(
                guardian, "RECONCILIATION_REQUIRED", "ORDER_STATUS_INVALID"
            )
            return guardian
        remote = str(data.get("order_status") or "").lower()
        if remote in {"rejected", "cancelled", "canceled"}:
            self._transition(guardian, "REJECTED", f"REMOTE_{remote.upper()}")
            return guardian
        filled = self._non_negative_int(data.get("filled_quantity"))
        average = self._positive_number(data.get("average_price"))
        if filled <= 0 or average is None:
            target = "EXITING" if not entry else "SUBMITTING"
            self._transition(guardian, target, f"REMOTE_{remote.upper() or 'PENDING'}")
            return guardian
        if entry:
            if filled != int(guardian["approved_quantity"]):
                self._transition(
                    guardian,
                    "RECONCILIATION_REQUIRED",
                    "PARTIAL_ENTRY_FILL_REQUIRES_RECONCILIATION",
                )
                return guardian
            guardian["filled_quantity"] = filled
            guardian["entry_fill_price"] = average
            guardian["opened_at"] = self._now().isoformat()
            guardian["high_watermark"] = average
            try:
                self.paper_state.open_position(
                    position_id=guardian["paper_position_id"],
                    request_id=guardian["entry_client_order_id"],
                    event_id=self._event_id(guardian, "entry_fill"),
                    symbol=guardian["contract"],
                    side="BUY",
                    raw_quantity=filled,
                    entry_price=average,
                    instrument_id=guardian["security_id"],
                    lot_size=guardian["lot_size"],
                    option_type=guardian.get("option_type"),
                    strike=guardian.get("strike"),
                    expiry=guardian.get("expiry"),
                    stop_price=guardian["initial_stop"],
                    target_price=guardian["target_2"],
                    reason="ORACLE_APPROVED_PLAN",
                )
            except DuplicatePaperEvent:
                pass
            self._transition(guardian, "OPEN", "ENTRY_FILL_VERIFIED")
            return guardian
        if filled != int(guardian["filled_quantity"]):
            self._transition(
                guardian,
                "RECONCILIATION_REQUIRED",
                "PARTIAL_EXIT_FILL_REQUIRES_RECONCILIATION",
            )
            return guardian
        try:
            self.paper_state.close_position(
                guardian["paper_position_id"],
                average,
                self._event_id(guardian, "exit_fill"),
                request_id=guardian["exit_client_order_id"],
                exit_reason=guardian["exit_reason"] or "ORACLE_EXIT",
            )
        except DuplicatePaperEvent:
            pass
        self._transition(guardian, "CLOSED", "EXIT_FILL_VERIFIED")
        return guardian

    def _mission_and_plan(self, mission_id: str) -> tuple[dict, dict]:
        self._require_available()
        mission = self.missions.get(mission_id)
        if mission["status"] != "ACTIVE":
            raise OracleExecutionBlocked("MISSION_NOT_ACTIVE")
        rows = self.missions.events.read()
        plan = next(
            (
                (row.get("payload") or {}).get("plan")
                for row in reversed(rows)
                if row.get("event_type") == "PLAN_CREATED"
                and ((row.get("payload") or {}).get("mission") or {}).get(
                    "mission_id"
                )
                == mission_id
            ),
            None,
        )
        if not isinstance(plan, Mapping):
            raise OracleExecutionBlocked("APPROVED_PLAN_UNAVAILABLE")
        return mission, deepcopy(dict(plan))

    @staticmethod
    def _validate_plan(plan: Mapping[str, Any]) -> None:
        required = (
            "plan_id",
            "contract",
            "security_id",
            "lot_size",
            "approved_quantity",
            "final_sl",
            "target_1",
            "target_2",
            "maximum_entry",
        )
        if any(plan.get(key) is None for key in required):
            raise OracleExecutionBlocked("PLAN_CONTRACT_INCOMPLETE")
        if (
            plan.get("status") != "APPROVED"
            or plan.get("contract_locked") is not True
            or plan.get("paper_only") is not True
            or plan.get("live_trading_enabled") is not False
            or plan.get("broker_submission") is not False
            or plan.get("execution_allowed") is not False
        ):
            raise OracleExecutionBlocked("PLAN_SAFETY_INVALID")
        quantity = plan.get("approved_quantity")
        maximum = plan.get("maximum_approved_quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            or quantity != maximum
        ):
            raise OracleExecutionBlocked("PLAN_QUANTITY_INVALID")

    def _require_analyzer(self) -> None:
        response = self.openalgo.analyzer()
        data = response.get("data")
        analyze_mode = (
            data.get("analyze_mode")
            if isinstance(data, Mapping)
            else response.get("analyze_mode")
        )
        mode = (
            data.get("mode")
            if isinstance(data, Mapping)
            else response.get("mode")
        )
        if (
            int(response.get("_http_status") or 0) != 200
            or response.get("status") != "success"
            or analyze_mode is not True
            or mode != "analyze"
        ):
            raise OracleExecutionBlocked("OPENALGO_ANALYZER_REQUIRED")

    def _entry_payload(
        self, plan: Mapping[str, Any], client_id: str
    ) -> dict[str, Any]:
        return {
            "client_order_id": client_id,
            "strategy": "ORACLE",
            "exchange": self._exchange(plan.get("option_type")),
            "symbol": plan["contract"],
            "action": "BUY",
            "quantity": int(plan["approved_quantity"]),
            "pricetype": "LIMIT",
            "product": "MIS",
            "price": float(plan["maximum_entry"]),
            "trigger_price": 0,
            "disclosed_quantity": 0,
        }

    @staticmethod
    def _held_quote(snapshot: Mapping[str, Any], security_id: str) -> dict[str, Any]:
        execution = snapshot.get("execution")
        if not isinstance(execution, Mapping):
            raise ValueError("snapshot execution unavailable")
        argus = execution.get("argus")
        if not isinstance(argus, Mapping):
            raise ValueError("ARGUS unavailable")
        data = argus.get("data")
        if not isinstance(data, Mapping):
            raise ValueError("ARGUS data unavailable")
        tactical = data.get("tactical_edge")
        ranks = tactical.get("all_candidate_ranks") if isinstance(tactical, Mapping) else None
        if not isinstance(ranks, list):
            raise ValueError("candidate quotes unavailable")
        row = next(
            (
                item
                for item in ranks
                if isinstance(item, Mapping)
                and str(item.get("security_id")) == str(security_id)
            ),
            None,
        )
        if row is None:
            raise ValueError("held quote unavailable")
        price = OraclePaperAutopilot._positive_number(
            row.get("premium") or row.get("ltp")
        )
        timestamp = row.get("source_timestamp") or row.get("fetched_at")
        if price is None or not isinstance(timestamp, str):
            raise ValueError("held quote invalid")
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
        return {"price": price, "timestamp": timestamp, "fresh": 0 <= age <= 30}

    @staticmethod
    def _underlying_quote(snapshot: Mapping[str, Any]) -> Optional[float]:
        try:
            return OraclePaperAutopilot._positive_number(
                snapshot["execution"]["argus"]["data"]["underlying"]["ltp"]
            )
        except (KeyError, TypeError):
            return None

    def _transition(self, guardian: dict, target: str, reason: str) -> None:
        if target not in STATES:
            raise OracleExecutionUnavailable("GUARDIAN_STATE_INVALID")
        guardian["state"] = target
        guardian["reason"] = reason
        guardian["updated_at"] = self._now().isoformat()
        self._persist(guardian, reason)
        if target in TERMINAL:
            mission = self.missions.get(guardian["mission_id"])
            self.missions.events.append(
                f"EXECUTION_{target}",
                {"mission": mission, "guardian_state": target, "reason": reason},
                recorded_at=guardian["updated_at"],
                idempotency_key=f"{guardian['mission_id']}:execution:{target}",
            )

    def _persist(self, guardian: dict, event_type: str) -> None:
        self._state["guardians"][guardian["mission_id"]] = deepcopy(guardian)
        self._state["updated_at"] = guardian["updated_at"]
        self.events.append(
            event_type,
            {"guardian": guardian},
            recorded_at=guardian["updated_at"],
            idempotency_key=(
                f"{guardian['mission_id']}:{event_type}:"
                f"{guardian['state']}:{guardian['updated_at']}"
            ),
        )
        if event_type in {
            "ENTRY_FILL_VERIFIED",
            "EXIT_FILL_VERIFIED",
            "STOP_LOSS",
            "TARGET_2",
            "TIME_EXIT",
        }:
            self.journal.append(
                event_type,
                {
                    "mission_id": guardian["mission_id"],
                    "plan_id": guardian["plan_id"],
                    "contract": guardian["contract"],
                    "security_id": guardian["security_id"],
                    "state": guardian["state"],
                    "quantity": guardian["filled_quantity"],
                    "price": guardian.get("last_quote"),
                    "reason": guardian.get("exit_reason"),
                },
                recorded_at=guardian["updated_at"],
                idempotency_key=f"{guardian['mission_id']}:{event_type}",
            )
        _atomic_write(self.state_path, self._state)

    def _load(self) -> None:
        try:
            if self.state_path.exists():
                value = json.loads(self.state_path.read_text(encoding="utf-8"))
            else:
                value = self._empty()
            if (
                value.get("schema_version") != self.SCHEMA_VERSION
                or not isinstance(value.get("guardians"), dict)
                or not self.events.verify()["valid"]
                or not self.journal.verify()["valid"]
            ):
                raise ValueError("guardian state invalid")
            for row in value["guardians"].values():
                if row.get("state") not in STATES:
                    raise ValueError("guardian record invalid")
            self._state = value
        except (OSError, ValueError, TypeError, RuntimeError):
            self._available = False
            self._reason = "GUARDIAN_STATE_CORRUPT"
            self._state = self._empty()

    def _require_available(self) -> None:
        if not self._available:
            raise OracleExecutionUnavailable(self._reason or "GUARDIAN_UNAVAILABLE")

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def _public(self, guardian: Mapping[str, Any]) -> dict[str, Any]:
        hidden = {
            "entry_order_id",
            "exit_order_id",
            "entry_client_order_id",
            "exit_client_order_id",
        }
        result = {key: deepcopy(value) for key, value in guardian.items() if key not in hidden}
        result["remote_order_reference_present"] = bool(
            guardian.get("entry_order_id") or guardian.get("exit_order_id")
        )
        result.update(self._safety())
        return result

    @staticmethod
    def _safety() -> dict[str, Any]:
        return {
            "execution_allowed": False,
            "execution_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "openalgo_analyzer_submission": True,
            "direct_dhan_fallback": False,
        }

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": 1, "guardians": {}, "updated_at": None}

    @staticmethod
    def _client_id(kind: str, value: str) -> str:
        digest = hashlib.sha256(str(value).encode()).hexdigest()[:24]
        return f"orc_{kind}_{digest}"

    @staticmethod
    def _event_id(guardian: Mapping[str, Any], suffix: str) -> str:
        return "oracle_evt_" + hashlib.sha256(
            f"{guardian['mission_id']}:{suffix}".encode()
        ).hexdigest()[:24]

    @staticmethod
    def _exchange(option_type: Any) -> str:
        return "NFO" if option_type in {"CE", "PE"} else "NSE"

    @staticmethod
    def _positive_number(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result > 0 else None

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        try:
            result = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, result)
