"""CITADEL Luna Production Cognitive Adapter.

Connects the audited gpt-5.6-luna model via Experiential Labs as CITADEL's
solitary production cognitive analyst.
Enforces:
- Exact model identity: requested_model == "gpt-5.6-luna", actual_model == "gpt-5.6-luna"
- Zero cash cost: enforce_zero_cost = True (fails closed if cost > 0)
- Mandatory privacy sanitization before dispatch (fail closed on any private token)
- Strict NATIVE_JSON_SCHEMA enforcement with competing hypotheses contract
- Isolated failure handling (never crashes the coordinator/service)
"""

from __future__ import annotations

import json
import logging
from src.oracle_sol.luna_input_receipt import persist_receipt, digest
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.competing_hypotheses_contract import INSTRUCTIONS, SCHEMA
from src.oracle_sol.experiential_adapter import ExperientialAdapter
from src.oracle_sol.privacy_sanitizer import (
    PrivacyViolationError,
    sanitize_brain_packet,
    verify_sanitized_payload,
)

logger = logging.getLogger(__name__)

PRODUCTION_MODEL_ID = "gpt-5.6-luna"
RECEIPT_DIRECTORY = "data/sol_shadow/luna_inputs"


class LunaCognitiveAdapter:
    """Production cognitive analyst adapter for gpt-5.6-luna."""

    def __init__(
        self,
        model_name: str = PRODUCTION_MODEL_ID,
        backend_adapter: Optional[ExperientialAdapter] = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.model_name = model_name
        self.backend = backend_adapter or ExperientialAdapter(
            model_name=self.model_name,
            enforce_zero_cost=True,
            reject_substituted_model=True,
        )
        self.timeout_seconds = timeout_seconds
        self.last_telemetry: Dict[str, Any] = {}

    @property
    def configured_model(self) -> str:
        return self.model_name

    def is_available(self) -> bool:
        return self.backend.is_available()

    def analyze(
        self,
        packet: BrainPacket,
        unseen_events: Optional[Sequence[Any]] = None,
        decision_cutoff_ist: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Executes a bounded, privacy-sanitized reasoning cycle on gpt-5.6-luna."""
        request_id = f"luna_rev_{packet.revision}_{packet.session_id}"
        telemetry: Dict[str, Any] = {
            "request_id": request_id,
            "provider": "experiential",
            "requested_model": self.model_name,
            "response_model": None,
            "status": "UNAVAILABLE",
            "latency_ms": 0.0,
            "cost_micro_usd": 0,
            "error": None,
            "error_class": None,
            "http_status": None,
        }

        # 1. Deterministic Privacy Sanitization
        try:
            sanitized_packet = sanitize_brain_packet(
                packet,
                unseen_events=unseen_events,
                decision_cutoff_ist=decision_cutoff_ist,
            )
            payload_str = json.dumps(sanitized_packet, indent=2)
            valid, reason = verify_sanitized_payload(payload_str)
            if not valid:
                telemetry["error_class"] = "PRIVACY_VIOLATION_BLOCKED"
                telemetry["error"] = reason
                self.last_telemetry = telemetry
                return None, telemetry
        except PrivacyViolationError as pve:
            telemetry["error_class"] = "PRIVACY_VIOLATION_BLOCKED"
            telemetry["error"] = str(pve)
            self.last_telemetry = telemetry
            return None, telemetry
        except Exception as exc:
            telemetry["error_class"] = "SANITIZATION_FAILED"
            telemetry["error"] = str(exc)
            self.last_telemetry = telemetry
            return None, telemetry

        # 2. Network Reasoning Dispatch
        try:
            receipt = {}
            def record_request(request_bytes):
                receipt.update(persist_receipt(RECEIPT_DIRECTORY, request_bytes, packet))

            output, raw_tel = self.backend.invoke_reasoning(
                request_id=request_id,
                system_prompt=(
                    INSTRUCTIONS
                    + "\nCRITICAL EVIDENCE CITATION REQUIREMENTS:"
                    + "\n1. Non-empty citations: Every item in 'conclusions' and every hypothesis in 'hypotheses' MUST include at least one valid evidence_id in its 'evidence_ids' array. Never return an empty array ([]). If discussing missing data or next watch triggers, cite the observable anchor metric ID (such as 'metric:spot_price' or 'metric:straddle_price') that anchors the condition."
                    + "\n2. Exact IDs only: ALL cited evidence_ids MUST be exact identifier strings present in the input (from current_facts, timeline, or events). Never cite IDs whose value is null or unavailable."
                    + "\n3. Mandatory 'why_now': In 'conclusions', at least one conclusion item MUST have 'purpose': 'why_now' grounded in observable evidence_ids. Other conclusions may use 'call_case', 'put_case', 'option_response', 'missing_confirmation', 'internal_tension', 'watch_next'."
                    + "\n4. Style: Use simple English, one concise sentence per conclusion. Current facts are observations; previous_model_view is a previous model assertion, never canonical truth. Explain relationships and what changed, not an indicator checklist. Preserve caveats and missing-versus-contradictory evidence. Do not start with 'the recorded sequence', 'based on the provided evidence', or 'the model believes'."
                ),
                user_prompt=payload_str,
                schema=SCHEMA,
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=3500,
                structured_mode="NATIVE_JSON_SCHEMA",
                before_send=record_request,
                single_attempt=True,
            )
            telemetry.update(raw_tel)
            self.last_telemetry = telemetry

            if output is None:
                telemetry["status"] = raw_tel.get("error_class") or "FAILED"
                return None, telemetry

            if not receipt:
                telemetry["status"] = "INPUT_RECEIPT_MISSING"
                return None, telemetry
            receipt["output_hash"] = digest(output)
            telemetry["input_receipt"] = receipt

            # 3. Model Identity Invariant Check
            if raw_tel.get("response_model") != self.model_name:
                telemetry["status"] = "MODEL_SUBSTITUTION_REJECTED"
                telemetry["error_class"] = "MODEL_SUBSTITUTION_REJECTED"
                telemetry["error"] = f"Expected '{self.model_name}', received '{raw_tel.get('response_model')}'"
                return None, telemetry

            # 4. Commercial Zero-Cost Check
            cost_micro = raw_tel.get("cost_micro_usd", 0)
            if cost_micro > 0:
                telemetry["status"] = "COMMERCIAL_STATE_VIOLATION"
                telemetry["error_class"] = "COMMERCIAL_STATE_VIOLATION"
                telemetry["error"] = f"Monetary cost incurred: {cost_micro} micro-USD"
                return None, telemetry

            telemetry["status"] = "CURRENT"
            return output, telemetry

        except Exception as exc:
            logger.error("LunaCognitiveAdapter exception: %s", exc)
            telemetry["error_class"] = type(exc).__name__
            telemetry["error"] = str(exc)
            telemetry["status"] = "EXCEPTION"
            self.last_telemetry = telemetry
            return None, telemetry
