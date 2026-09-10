"""CITADEL Multi-Model Live Shadow Runtime V1.3.

Provides asynchronous, non-blocking background orchestration for Gemini Fast Scout
and Sol Option Specialist alongside Luna's official cognitive state.

Core Safety Guarantees:
- AI_EXECUTION_INFLUENCE == 0.0 (Hard gate)
- BROKER_SUBMISSION is False (Hard gate)
- AI_VOB_INFLUENCE == 0.0 (Hard gate)
- Bounded concurrency: maximum 1 in-flight generation per model.
- Complete timeout and failure isolation: slow/failing challenger never delays Luna, SSE, or FastAPI.
- Stale result protection: superseded findings are discarded from the current cockpit projection.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.privacy_sanitizer import sanitize_brain_packet
from src.oracle_sol.shadow_orchestrator import (
    AI_EXECUTION_INFLUENCE,
    AI_VOB_INFLUENCE,
    BROKER_SUBMISSION,
    GEMINI_SCOUT_MODEL_ID,
    PRIMARY_MODEL_ID,
    SOL_CHALLENGER_MODEL_ID,
    CanonicalShadowReceipt,
    ShadowOrchestratorRouter,
)
from src.oracle_sol.shadow_specialists import (
    GeminiScoutAdapter,
    GeminiScoutOutput,
    SolOptionSpecialistAdapter,
    SolOptionSpecialistOutput,
    validated_specialist_view,
)

logger = logging.getLogger(__name__)

LIVE_SHADOW_STATUS_PATH = "data/sol_shadow/live_shadow_status.json"


# =====================================================================
# SOL OPTION SPECIALIST PAUSE GATE (COST CONTROL / INPUT HARDENING)
# =====================================================================
# Fail-closed gate: paused while option-economics inputs are incomplete.
# Reversible only via explicit administrative reconfiguration.
SOL_DISPATCH_ENABLED: bool = False
SOL_OPTION_SPECIALIST_ENABLED: bool = False


def is_sol_option_specialist_enabled() -> bool:
    """Check if Sol Option Specialist provider dispatch is enabled."""
    if not SOL_DISPATCH_ENABLED:
        return False
    if os.getenv("CITADEL_PAUSE_SOL", "0").strip().lower() in {"1", "true", "yes"}:
        return False
    env = os.getenv("CITADEL_SOL_OPTION_SPECIALIST_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes"}
    return SOL_OPTION_SPECIALIST_ENABLED


# =====================================================================
# GEMINI FAST SCOUT PAUSE GATE (COST CONTROL / ARCHITECTURE HARDENING)
# =====================================================================
# Fail-closed gate: paused while input and architecture hardening is underway.
# Reversible only via explicit administrative reconfiguration.
GEMINI_DISPATCH_ENABLED: bool = False
GEMINI_FAST_SCOUT_ENABLED: bool = False


def is_gemini_fast_scout_enabled() -> bool:
    """Check if Gemini Fast Scout provider dispatch is enabled."""
    if not GEMINI_DISPATCH_ENABLED:
        return False
    if os.getenv("CITADEL_PAUSE_GEMINI", "0").strip().lower() in {"1", "true", "yes"}:
        return False
    env = os.getenv("CITADEL_GEMINI_FAST_SCOUT_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes"}
    return GEMINI_FAST_SCOUT_ENABLED


class LiveShadowOrchestrator:
    """Production runtime managing live shadow execution of Gemini and Sol."""

    _instance: Optional["LiveShadowOrchestrator"] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "LiveShadowOrchestrator":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(
        self,
        router: Optional[ShadowOrchestratorRouter] = None,
        gemini_adapter: Optional[GeminiScoutAdapter] = None,
        sol_adapter: Optional[SolOptionSpecialistAdapter] = None,
        status_path: str = LIVE_SHADOW_STATUS_PATH,
        sol_enabled: Optional[bool] = None,
        gemini_enabled: Optional[bool] = None,
    ) -> None:
        self.status_path = Path(status_path)
        self._sol_enabled = sol_enabled if sol_enabled is not None else is_sol_option_specialist_enabled()
        self._gemini_enabled = gemini_enabled if gemini_enabled is not None else is_gemini_fast_scout_enabled()
        self.router = router or ShadowOrchestratorRouter(sol_enabled=self._sol_enabled, gemini_enabled=self._gemini_enabled)
        self.gemini_adapter = gemini_adapter or GeminiScoutAdapter()
        self.sol_adapter = sol_adapter or SolOptionSpecialistAdapter()
        if hasattr(self.router, "sol_enabled"):
            self.router.sol_enabled = self._sol_enabled
        if hasattr(self.router, "gemini_enabled"):
            self.router.gemini_enabled = self._gemini_enabled

        self._lock = threading.RLock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="citadel-shadow"
        )

        self._gemini_in_flight = False
        self._sol_in_flight = False
        self._pending_gemini = None
        self._pending_sol = None
        self._latest_receipt_id: Optional[str] = None
        self._latest_revision: int = 0
        self._latest_session: Optional[str] = None

        self._latest_gemini_view: Optional[Dict[str, Any]] = None
        self._latest_sol_view: Optional[Dict[str, Any]] = None

        # Lifecycle metrics
        self.metrics = {
            "gemini_dispatches": 0,
            "gemini_completions": 0,
            "gemini_failures": 0,
            "gemini_stale_dropped": 0,
            "sol_dispatches": 0,
            "sol_completions": 0,
            "sol_failures": 0,
            "sol_stale_dropped": 0,
        }

        self._sol_readiness_checklist: Dict[str, Any] = self._build_sol_readiness_checklist()

        # Load persisted status if exists
        self._load_persisted_status()
        self._persist_status_locked()

    def pause_gemini(self, reason: str = "INPUT_ARCHITECTURE_HARDENING") -> None:
        """Safely pause Gemini Fast Scout provider dispatch and cancel pending queue."""
        with self._lock:
            self._gemini_enabled = False
            if hasattr(self.router, "gemini_enabled"):
                self.router.gemini_enabled = False
            self._pending_gemini = None
            self._gemini_in_flight = False
            if self._latest_gemini_view:
                if self._latest_gemini_view.get("status") == "CURRENT":
                    self._latest_gemini_view["status"] = "STALE"
                self._latest_gemini_view["paused"] = True
                self._latest_gemini_view["pause_reason"] = reason
                self._latest_gemini_view["display_status"] = "PAUSED · INPUT/ARCHITECTURE HARDENING"
            self._persist_status_locked()
            logger.info("Gemini Fast Scout dispatch paused: %s", reason)

    def resume_gemini(self) -> None:
        """Resume Gemini Fast Scout provider dispatch."""
        with self._lock:
            self._gemini_enabled = True
            if hasattr(self.router, "gemini_enabled"):
                self.router.gemini_enabled = True
            if self._latest_gemini_view:
                self._latest_gemini_view["paused"] = False
                self._latest_gemini_view.pop("pause_reason", None)
                self._latest_gemini_view.pop("display_status", None)
            self._persist_status_locked()
            logger.info("Gemini Fast Scout dispatch resumed")

    def pause_sol(self, reason: str = "COST_STOP") -> None:
        """Safely pause Sol Option Specialist provider dispatch and cancel pending queue."""
        with self._lock:
            self._sol_enabled = False
            if hasattr(self.router, "sol_enabled"):
                self.router.sol_enabled = False
            self._pending_sol = None
            self._sol_in_flight = False
            if self._latest_sol_view:
                if self._latest_sol_view.get("status") == "CURRENT":
                    self._latest_sol_view["status"] = "STALE"
                self._latest_sol_view["paused"] = True
                self._latest_sol_view["pause_reason"] = reason
                self._latest_sol_view["display_status"] = f"PAUSED · {reason.replace('_', ' ')}"
            self._persist_status_locked()
            logger.info("Sol Option Specialist dispatch paused: %s", reason)

    def resume_sol(self) -> None:
        """Resume Sol Option Specialist provider dispatch."""
        with self._lock:
            self._sol_enabled = True
            if hasattr(self.router, "sol_enabled"):
                self.router.sol_enabled = True
            if self._latest_sol_view:
                self._latest_sol_view["paused"] = False
                self._latest_sol_view.pop("pause_reason", None)
                self._latest_sol_view.pop("display_status", None)
            self._persist_status_locked()
            logger.info("Sol Option Specialist dispatch resumed")

    def _load_persisted_status(self) -> None:
        if self.status_path.exists():
            try:
                with open(self.status_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._latest_gemini_view = data.get("gemini_scout")
                    self._latest_sol_view = data.get("sol_option_specialist")
                    self._latest_revision = data.get("latest_revision", 0)
                    self._latest_receipt_id = data.get("latest_receipt_id")
                    self._latest_session = data.get("session_date")
                    if not self._sol_enabled and self._latest_sol_view:
                        if self._latest_sol_view.get("status") == "CURRENT":
                            self._latest_sol_view["status"] = "STALE"
                        self._latest_sol_view["paused"] = True
                        self._latest_sol_view["pause_reason"] = "INPUT_HARDENING"
                        self._latest_sol_view["display_status"] = "PAUSED · INPUT HARDENING"
                    if not self._gemini_enabled and self._latest_gemini_view:
                        if self._latest_gemini_view.get("status") == "CURRENT":
                            self._latest_gemini_view["status"] = "STALE"
                        self._latest_gemini_view["paused"] = True
                        self._latest_gemini_view["pause_reason"] = "INPUT_ARCHITECTURE_HARDENING"
                        self._latest_gemini_view["display_status"] = "PAUSED · INPUT/ARCHITECTURE HARDENING"
            except Exception as exc:
                logger.warning("Could not read existing shadow status: %s", exc)

    def _build_sol_readiness_checklist(
        self, packet: Optional[BrainPacket] = None, receipt: Optional[CanonicalShadowReceipt] = None
    ) -> Dict[str, Any]:
        """Expose and record readiness status of required option-economics inputs while paused."""
        facts: Dict[str, Any] = {}
        if packet and hasattr(packet, "canonical_state") and isinstance(packet.canonical_state, dict):
            facts = packet.canonical_state
        elif receipt and hasattr(receipt, "current_facts") and isinstance(receipt.current_facts, dict):
            for k, v in receipt.current_facts.items():
                facts[k] = v.get("value") if isinstance(v, dict) else v

        atm_strike = facts.get("atm_strike")
        ce_sec = facts.get("ce_atm_security_id")
        pe_sec = facts.get("pe_atm_security_id")
        ce_prem = facts.get("ce_atm_premium")
        pe_prem = facts.get("pe_atm_premium")
        atm_iv = facts.get("atm_iv")
        straddle_chg = facts.get("straddle_change_15m")
        spot = facts.get("spot_price")
        fut = facts.get("futures_price")
        basis = facts.get("basis")
        flow_delta = facts.get("flow_net_delta")
        rev = packet.revision if packet else (receipt.revision if receipt else getattr(self, "_latest_revision", 0))
        rcpt_id = receipt.receipt_id if receipt else (packet.packet_id if packet else getattr(self, "_latest_receipt_id", None))

        checklist = {
            "option_contract_strike": {
                "ready": bool(atm_strike is not None and (ce_sec or pe_sec)),
                "value": f"ATM {atm_strike} (CE:{ce_sec}, PE:{pe_sec})" if atm_strike else "MISSING",
                "collected": bool(atm_strike is not None),
            },
            "expiry": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Contract expiry date not populated in canonical state",
            },
            "time_to_expiry": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Time remaining to expiry not computed",
            },
            "premium": {
                "ready": bool(ce_prem is not None and pe_prem is not None),
                "value": f"CE: {ce_prem}, PE: {pe_prem}" if (ce_prem and pe_prem) else "INCOMPLETE",
                "collected": bool(ce_prem is not None or pe_prem is not None),
            },
            "bid_ask": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Option top bid/ask spread not in canonical state",
            },
            "same_option_premium_change_history": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Multi-window same-strike premium history not tracked",
            },
            "atm_iv": {
                "ready": bool(atm_iv is not None),
                "value": f"{atm_iv}%" if atm_iv is not None else "MISSING",
                "collected": bool(atm_iv is not None),
            },
            "iv_baseline_reference": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "IV historical baseline/percentile not established",
            },
            "straddle_change": {
                "ready": bool(straddle_chg is not None),
                "value": straddle_chg if straddle_chg is not None else "UNAVAILABLE (null)",
                "collected": False,
                "reason": "15-minute straddle change unavailable",
            },
            "theta_if_required": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Option theta not computed",
            },
            "fair_value_if_required": {
                "ready": False,
                "value": "MISSING",
                "collected": False,
                "reason": "Option theoretical fair value not computed",
            },
            "underlying_futures_basis": {
                "ready": bool(spot is not None and fut is not None and basis is not None),
                "value": (
                    f"Spot: {spot}, Fut: {fut}, Basis: {float(basis):.2f}"
                    if (spot and fut and basis is not None)
                    else "INCOMPLETE"
                ),
                "collected": bool(spot is not None and fut is not None),
            },
            "required_flow_evidence": {
                "ready": bool(flow_delta is not None),
                "value": f"flow_net_delta={flow_delta}" if flow_delta is not None else "UNAVAILABLE (null)",
                "collected": False,
                "reason": "Directional flow net delta unavailable",
            },
            "correct_receipt_revision": {
                "ready": bool(rcpt_id and rev),
                "value": f"rev_{rev} ({str(rcpt_id)[:12]}...)" if (rcpt_id and rev) else "UNBOUND",
                "collected": bool(rcpt_id and rev),
            },
        }
        ready_count = sum(1 for item in checklist.values() if isinstance(item, dict) and item.get("ready"))
        checklist["_summary"] = {
            "ready_count": ready_count,
            "total_count": 14,
            "status": "INPUT_HARDENING_REQUIRED" if ready_count < 14 else "READY",
        }
        return checklist

    def _persist_status_locked(self) -> None:
        """Write current status atomically to disk for external viewers."""
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            gemini_view = dict(self._latest_gemini_view) if self._latest_gemini_view else None
            gemini_active = bool(self._gemini_enabled and GEMINI_DISPATCH_ENABLED)
            if not gemini_active and gemini_view:
                gemini_view["in_flight"] = False
                gemini_view["paused"] = True
                pause_reason = gemini_view.get("pause_reason", "INPUT_ARCHITECTURE_HARDENING")
                gemini_view["pause_reason"] = pause_reason
                if gemini_view.get("status") == "CURRENT":
                    gemini_view["status"] = "STALE"
                gemini_view["display_status"] = gemini_view.get("display_status") or "PAUSED · INPUT/ARCHITECTURE HARDENING"

            sol_view = dict(self._latest_sol_view) if self._latest_sol_view else None
            sol_active = bool(self._sol_enabled and SOL_DISPATCH_ENABLED)
            if not sol_active and sol_view:
                sol_view["in_flight"] = False
                sol_view["paused"] = True
                pause_reason = sol_view.get("pause_reason", "COST_STOP")
                sol_view["pause_reason"] = pause_reason
                if sol_view.get("status") == "CURRENT":
                    sol_view["status"] = "STALE"
                sol_view["display_status"] = sol_view.get("display_status") or f"PAUSED · {pause_reason.replace('_', ' ')}"
                if self._sol_readiness_checklist:
                    sol_view["readiness_checklist"] = self._sol_readiness_checklist

            payload = {
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "latest_revision": self._latest_revision,
                "latest_receipt_id": self._latest_receipt_id,
                "session_date": self._latest_session,
                "gemini_in_flight": False if not self._gemini_enabled else self._gemini_in_flight,
                "gemini_paused": not self._gemini_enabled,
                "gemini_pause_state": "PAUSED · INPUT/ARCHITECTURE HARDENING" if not self._gemini_enabled else "ACTIVE",
                "sol_in_flight": False if not self._sol_enabled else self._sol_in_flight,
                "sol_paused": not self._sol_enabled,
                "sol_pause_state": "PAUSED · INPUT HARDENING" if not self._sol_enabled else "ACTIVE",
                "sol_readiness_checklist": self._sol_readiness_checklist,
                "gemini_scout": gemini_view,
                "sol_option_specialist": sol_view,
                "metrics": dict(self.metrics),
                "invariants": {
                    "ai_execution_influence": AI_EXECUTION_INFLUENCE,
                    "broker_submission": BROKER_SUBMISSION,
                    "ai_vob_influence": AI_VOB_INFLUENCE,
                    "sol_dispatch_enabled": sol_active,
                    "gemini_dispatch_enabled": gemini_active,
                },
            }
            temp_file = self.status_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(temp_file, self.status_path)
        except Exception as exc:
            logger.error("Failed to persist live shadow status: %s", exc)

    def process_live_packet(
        self,
        packet: BrainPacket,
        recent_events: Sequence[Dict[str, Any]] = (),
        current_time_epoch: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluates router triggers and initiates non-blocking shadow calls if eligible."""
        assert AI_EXECUTION_INFLUENCE == 0.0, "FATAL: AI execution influence must be ZERO"
        assert BROKER_SUBMISSION is False, "FATAL: Broker submission must be FALSE"
        assert AI_VOB_INFLUENCE == 0.0, "FATAL: AI VOB influence must be ZERO"

        now_epoch = current_time_epoch or time.time()
        receipt = CanonicalShadowReceipt.from_packet_payload(sanitize_brain_packet(packet), revision=packet.revision)

        with self._lock:
            if self._latest_session is not None and receipt.session_date < self._latest_session:
                return {"status": "STALE_SESSION_REJECTED", "dispatched_gemini": False, "dispatched_sol": False}
            if receipt.session_date == self._latest_session and (receipt.receipt_id == self._latest_receipt_id or receipt.revision <= self._latest_revision):
                return {"status": "DUPLICATE_OR_OLDER_RECEIPT", "dispatched_gemini": False, "dispatched_sol": False}
            if receipt.session_date != self._latest_session:
                if self._latest_session is not None and isinstance(self.router, ShadowOrchestratorRouter):
                    self.router = ShadowOrchestratorRouter()
                self._latest_gemini_view = self._latest_sol_view = None
                self._pending_gemini = self._pending_sol = None
            self._latest_receipt_id = receipt.receipt_id
            self._latest_revision = packet.revision
            self._latest_session = receipt.session_date

            # Always evaluate and track required option-economics inputs on every live packet
            self._sol_readiness_checklist = self._build_sol_readiness_checklist(packet, receipt)

            # Route decision via V1.2 tested logic
            decision = self.router.evaluate_routing(
                receipt,
                recent_events=[e.to_dict() if hasattr(e, "to_dict") else e for e in recent_events],
                current_time_epoch=now_epoch,
            )

            dispatched_gemini = False
            dispatched_sol = False

            # One latest pending packet per busy specialist, never a growing queue.
            if self._gemini_enabled:
                if self._gemini_in_flight and (decision.invoke_gemini or self._pending_gemini):
                    self._pending_gemini = (receipt, packet)
            else:
                self._pending_gemini = None

            if self._sol_enabled:
                if self._sol_in_flight and (decision.invoke_sol or self._pending_sol):
                    self._pending_sol = (receipt, packet)
            else:
                self._pending_sol = None

            if self._gemini_enabled and decision.invoke_gemini and not self._gemini_in_flight:
                self._gemini_in_flight = True
                self.metrics["gemini_dispatches"] += 1
                dispatched_gemini = True
                self._executor.submit(self._run_gemini_async, receipt, packet)

            if self._sol_enabled and decision.invoke_sol and not self._sol_in_flight:
                self._sol_in_flight = True
                self.metrics["sol_dispatches"] += 1
                dispatched_sol = True
                self._executor.submit(self._run_sol_async, receipt, packet)

            self._persist_status_locked()

        return {
            "receipt_id": receipt.receipt_id,
            "revision": receipt.revision,
            "decision": decision,
            "dispatched_gemini": dispatched_gemini,
            "dispatched_sol": dispatched_sol,
        }

    def _run_gemini_async(self, receipt: CanonicalShadowReceipt, packet: BrainPacket) -> None:
        try:
            output, tel = self.gemini_adapter.analyze(receipt, packet)
            with self._lock:
                if output and tel.get("status") == "CURRENT" and output.receipt_id == receipt.receipt_id and output.revision == receipt.revision and output.model_id == GEMINI_SCOUT_MODEL_ID and not output.unsupported_inference_flag:
                    # Check staleness against active frontier
                    # Every superseded receipt is non-current, including one revision behind.
                    if receipt.receipt_id != self._latest_receipt_id or receipt.session_date != self._latest_session:
                        self.metrics["gemini_stale_dropped"] += 1
                        logger.info(
                            "Gemini output for rev %d superseded by rev %d (dropped from current projection)",
                            receipt.revision,
                            self._latest_revision,
                        )
                    else:
                        self.metrics["gemini_completions"] += 1
                        self._latest_gemini_view = {
                            "schema_version": output.schema_version,
                            "model_id": output.model_id,
                            "role": output.role,
                            "receipt_id": output.receipt_id,
                            "revision": output.revision,
                            "session_date": receipt.session_date,
                            "packet_hash": receipt.packet_hash,
                            "decision_cutoff": receipt.decision_cutoff_ist,
                            "semantic_state": output.semantic_state,
                            "headline": output.headline,
                            "bullets": output.bullets,
                            "missing_evidence": output.missing_evidence,
                            "evidence_ids": output.evidence_ids,
                            "deserves_luna_review": output.deserves_luna_review,
                            "unsupported_inference_flag": output.unsupported_inference_flag,
                            "unsupported_inference_reason": output.unsupported_inference_reason,
                            "updated_at": output.evaluated_at_utc,
                            "status": "STALE" if not self._gemini_enabled else "CURRENT",
                            "paused": not self._gemini_enabled,
                            "pause_reason": "INPUT_ARCHITECTURE_HARDENING" if not self._gemini_enabled else None,
                            "display_status": "PAUSED · INPUT/ARCHITECTURE HARDENING" if not self._gemini_enabled else None,
                            "telemetry": tel,
                        }
                else:
                    self.metrics["gemini_failures"] += 1
                    logger.warning("Gemini Scout returned unsuccessful: %s", tel.get("error"))
                self._persist_status_locked()
        except Exception as exc:
            with self._lock:
                self.metrics["gemini_failures"] += 1
                self._persist_status_locked()
            logger.error("Async Gemini execution failed: %s", exc)
        finally:
            with self._lock:
                self._gemini_in_flight = False
                if not self._gemini_enabled:
                    self._pending_gemini = None
                elif self._pending_gemini:
                    pending, self._pending_gemini = self._pending_gemini, None
                    self._gemini_in_flight = True
                    self.metrics["gemini_dispatches"] += 1
                    self._executor.submit(self._run_gemini_async, *pending)

    def _run_sol_async(self, receipt: CanonicalShadowReceipt, packet: BrainPacket) -> None:
        try:
            output, tel = self.sol_adapter.analyze(receipt, packet)
            with self._lock:
                if output and tel.get("status") == "CURRENT" and output.receipt_id == receipt.receipt_id and output.revision == receipt.revision and output.model_id == SOL_CHALLENGER_MODEL_ID:
                    if receipt.receipt_id != self._latest_receipt_id or receipt.session_date != self._latest_session:
                        self.metrics["sol_stale_dropped"] += 1
                        logger.info(
                            "Sol output for rev %d superseded by rev %d (dropped from current projection)",
                            receipt.revision,
                            self._latest_revision,
                        )
                    else:
                        self.metrics["sol_completions"] += 1
                        self._latest_sol_view = {
                            "schema_version": output.schema_version,
                            "model_id": output.model_id,
                            "role": output.role,
                            "receipt_id": output.receipt_id,
                            "revision": output.revision,
                            "session_date": receipt.session_date,
                            "packet_hash": receipt.packet_hash,
                            "decision_cutoff": receipt.decision_cutoff_ist,
                            "buying_state": output.buying_state,
                            "headline": output.headline,
                            "bullets": output.bullets,
                            "missing_evidence": output.missing_evidence,
                            "evidence_ids": output.evidence_ids,
                            "direction_vs_trade_quality_conflict": output.direction_vs_trade_quality_conflict,
                            "updated_at": output.evaluated_at_utc,
                            "status": "STALE" if not self._sol_enabled else "CURRENT",
                            "paused": not self._sol_enabled,
                            "pause_reason": "INPUT_HARDENING" if not self._sol_enabled else None,
                            "display_status": "PAUSED · INPUT HARDENING" if not self._sol_enabled else None,
                            "telemetry": tel,
                        }
                else:
                    self.metrics["sol_failures"] += 1
                    logger.warning("Sol Option Specialist returned unsuccessful: %s", tel.get("error"))
                self._persist_status_locked()
        except Exception as exc:
            with self._lock:
                self.metrics["sol_failures"] += 1
                self._persist_status_locked()
            logger.error("Async Sol execution failed: %s", exc)
        finally:
            with self._lock:
                self._sol_in_flight = False
                if not self._sol_enabled:
                    self._pending_sol = None
                elif self._pending_sol:
                    pending, self._pending_sol = self._pending_sol, None
                    self._sol_in_flight = True
                    self.metrics["sol_dispatches"] += 1
                    self._executor.submit(self._run_sol_async, *pending)

    def get_projected_views(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Returns read-only specialist projections with computed ages and freshness status."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            gemini_raw = dict(self._latest_gemini_view) if self._latest_gemini_view else None
            sol_raw = dict(self._latest_sol_view) if self._latest_sol_view else None
            gemini_inflight = self._gemini_in_flight
            sol_inflight = self._sol_in_flight
            latest_receipt = self._latest_receipt_id
            latest_session = self._latest_session

        def format_view(raw: Optional[Dict[str, Any]], role_name: str, model_id: str) -> Dict[str, Any]:
            if not raw or not validated_specialist_view(raw):
                return {
                    "model_id": model_id,
                    "role": role_name,
                    "status": "AWAITING_FIRST_ANALYSIS",
                    "headline": f"{role_name.replace('_', ' ')} initializing...",
                    "bullets": [],
                    "missing_evidence": [],
                    "age_seconds": None,
                    "updated_at": None,
                    "receipt_id": None,
                    "revision": None,
                }

            updated_str = raw.get("updated_at")
            age = None
            status = "LAST_KNOWN"
            if updated_str:
                try:
                    dt = datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
                    if not dt.tzinfo:
                        raise ValueError("Timestamp timezone missing")
                    age = (now - dt.astimezone(timezone.utc)).total_seconds()
                    if (
                        age < 0
                        or raw.get("receipt_id") != latest_receipt
                        or raw.get("session_date") != latest_session
                        or (self._latest_revision is not None and raw.get("revision") != self._latest_revision)
                        or raw.get("unsupported_inference_flag")
                    ):
                        status = "STALE"
                    elif age < 60.0:
                        status = "CURRENT"
                    elif age < 180.0:
                        status = "STALE"
                    else:
                        status = "OUTDATED"
                except Exception:
                    pass

            return {
                **raw,
                "age_seconds": age,
                "status": status,
            }

        gemini_proj = format_view(gemini_raw, "FAST_SCOUT", GEMINI_SCOUT_MODEL_ID)
        sol_proj = format_view(sol_raw, "OPTION_SPECIALIST", SOL_CHALLENGER_MODEL_ID)

        if gemini_inflight and self._gemini_enabled:
            gemini_proj["in_flight"] = True
        if sol_inflight and self._sol_enabled:
            sol_proj["in_flight"] = True

        if not self._gemini_enabled:
            gemini_proj["in_flight"] = False
            gemini_proj["paused"] = True
            pause_reason = gemini_raw.get("pause_reason", "INPUT_ARCHITECTURE_HARDENING") if gemini_raw else "INPUT_ARCHITECTURE_HARDENING"
            gemini_proj["pause_reason"] = pause_reason
            gemini_proj["display_status"] = gemini_raw.get("display_status") if (gemini_raw and gemini_raw.get("display_status")) else "PAUSED · INPUT/ARCHITECTURE HARDENING"
            if gemini_proj.get("status") == "CURRENT":
                gemini_proj["status"] = "STALE"

        if not self._sol_enabled:
            sol_proj["in_flight"] = False
            sol_proj["paused"] = True
            pause_reason = sol_raw.get("pause_reason", "INPUT_HARDENING") if sol_raw else "INPUT_HARDENING"
            sol_proj["pause_reason"] = pause_reason
            sol_proj["display_status"] = sol_raw.get("display_status") if (sol_raw and sol_raw.get("display_status")) else f"PAUSED · {pause_reason.replace('_', ' ')}"
            if sol_proj.get("status") == "CURRENT":
                sol_proj["status"] = "STALE"
            if self._sol_readiness_checklist:
                sol_proj["readiness_checklist"] = self._sol_readiness_checklist

        return {
            "gemini_scout": gemini_proj,
            "sol_option_specialist": sol_proj,
        }
