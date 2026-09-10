"""Independent deterministic Guardian for Phase-5 paper positions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable, Mapping

from src.strategy_lab.storage import ImmutableStream

from .contracts import GUARDIAN_POLICY_VERSION, ProtectionPlan
from .paper import Phase5PaperExecutionAdapter


class IndependentPaperGuardian:
    ACTIONS = {"HOLD", "TIGHTEN_STOP", "PARTIAL_EXIT", "EXIT", "FAILED_SAFE", "RECONCILIATION_REQUIRED"}

    def __init__(self, root: str | Path, *, execution: Phase5PaperExecutionAdapter,
                 input_provider: Callable[[str], Mapping[str, Any] | None] | None = None,
                 on_decision: Callable[[ProtectionPlan, Mapping[str, Any]], None] | None = None,
                 clock=None, poll_seconds: float = 1.0):
        self.root = Path(root)
        self.execution = execution
        self.input_provider = input_provider
        self.on_decision = on_decision
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.stream = ImmutableStream(self.root / "guardian_events.jsonl", max_bytes=100 * 1024 * 1024, max_files=1)
        self._stop = Event()
        self._thread: Thread | None = None
        self._health = {"status": "STOPPED", "last_cycle_at": None, "last_error": None}

    def decide(self, protection: ProtectionPlan, inputs: Mapping[str, Any]) -> tuple[str, str, float | None]:
        if not protection.verify_hash() or protection.status != "ACTIVE":
            return "RECONCILIATION_REQUIRED", "PROTECTION_MISSING_OR_INVALID", None
        if inputs.get("paper_route_healthy") is not True:
            return "RECONCILIATION_REQUIRED", "PAPER_ROUTE_UNHEALTHY", None
        if inputs.get("kill_switch_active") is True:
            return "EXIT", "KILL_SWITCH_ACTIVE", None
        if inputs.get("quote_fresh") is not True or inputs.get("bid") is None:
            return "FAILED_SAFE", "STALE_OR_MISSING_MARKET_DATA", None
        bid = float(inputs["bid"])
        if bid <= protection.current_hard_stop:
            return "EXIT", "HARD_PREMIUM_STOP_HIT", None
        if bid >= protection.natural_targets[0]:
            partial = inputs.get("partial_exit_quantity")
            if partial is not None and 0 < int(partial) < protection.protected_quantity:
                return "PARTIAL_EXIT", "FIRST_NATURAL_TARGET_PARTIAL", float(int(partial))
            return "EXIT", "NATURAL_TARGET_HIT", None
        if inputs.get("structural_invalidated") is True:
            return "EXIT", "STRUCTURAL_INVALIDATION", None
        if inputs.get("premium_confirmed") is False:
            return "EXIT", "PREMIUM_NON_CONFIRMATION", None
        if inputs.get("authority_material_reversal") is True:
            return "EXIT", "VOB_OSE_ARGUS_MATERIAL_REVERSAL", None
        now = self._now()
        if now >= datetime.fromisoformat(protection.time_exit_at.replace("Z", "+00:00")):
            return "EXIT", "TIME_WINDOW_EXPIRED", None
        tighten = inputs.get("tighten_stop_to")
        if tighten is not None and protection.current_hard_stop <= float(tighten) < bid:
            return "TIGHTEN_STOP", "DETERMINISTIC_RISK_REDUCTION", float(tighten)
        return "HOLD", "ALL_PROTECTION_GATES_HEALTHY", None

    def cycle(self, protection: ProtectionPlan, inputs: Mapping[str, Any]) -> dict[str, Any]:
        action, reason, value = self.decide(protection, inputs)
        now = self._now()
        outcome = None
        if action == "TIGHTEN_STOP":
            updated = self.execution.tighten_stop(protection, float(value), float(inputs["bid"]))
            outcome = {"protection_hash": updated.content_hash, "new_stop": updated.current_hard_stop}
        elif action == "EXIT":
            outcome = self.execution.exit_position(protection.position_id, price=float(inputs["bid"]),
                                                   reason=reason, event_key=str(inputs.get("event_id") or now.isoformat()))
            self.execution.mark_protection_exited(protection, reason=reason)
        elif action == "PARTIAL_EXIT":
            outcome = self.execution.exit_position(protection.position_id, price=float(inputs["bid"]),
                reason=reason, event_key=str(inputs.get("event_id") or now.isoformat()),
                close_quantity=int(value))
        row = self.stream.append("GUARDIAN_DECISION", {
            "protection_id": protection.protection_id, "position_id": protection.position_id,
            "action": action, "reason_code": reason, "value": value, "outcome": outcome,
            "policy_version": GUARDIAN_POLICY_VERSION, "paper_only": True,
            "live_trading_enabled": False, "broker_submission": False,
            "llm_used": False, "learning_evidence_used": False,
        }, recorded_at=now.isoformat(), idempotency_key=f"guardian:{protection.position_id}:{inputs.get('event_id')}")
        self._health.update({"status": "HEALTHY", "last_cycle_at": now.isoformat(), "last_error": None})
        result = {"action": action, "reason": reason, "outcome": outcome, "event_hash": row["record_hash"]}
        if self.on_decision is not None:
            self.on_decision(protection, result)
        return result

    def start(self) -> None:
        if self.input_provider is None or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="oracle-independent-paper-guardian", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._health["status"] = "STOPPED"

    def health(self) -> dict[str, Any]:
        return {**self._health, "worker_alive": bool(self._thread and self._thread.is_alive()),
                "browser_independent": True, "frontend_required": False, "llm_required": False,
                "policy_version": GUARDIAN_POLICY_VERSION, "paper_only": True,
                "live_trading_enabled": False, "broker_submission": False}

    def events(self, position_id: str) -> list[dict[str, Any]]:
        return [row for row in self.stream.read() if (row.get("payload") or {}).get("position_id") == position_id]

    def _run(self) -> None:
        self._health["status"] = "HEALTHY"
        while not self._stop.wait(self.poll_seconds):
            # The provider returns explicit protection + inputs pairs. No UI state is read.
            try:
                rows = self.input_provider("ACTIVE") if self.input_provider else None
                for row in rows or ():
                    self.cycle(row["protection"], row["inputs"])
            except Exception as error:
                self._health.update({"status": "DEGRADED", "last_error": f"{type(error).__name__}:{error}"})

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeError("VERIFIED_TIME_UNAVAILABLE")
        return value
