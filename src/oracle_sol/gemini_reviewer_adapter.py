"""Gemini Independent Senior Reviewer Adapter (Phase-1.1 Truth Repair).

Independent senior observer role:
- Evaluates canonical processed evidence independently (Zero knowledge of GPT synthesis).
- Target model: gemini-3.8-flash (configured in repository).
- Zero veto authority (advisory only).
- Strictly non-blocking: quota unavailability or 429 immediately returns status="QUOTA_BLOCKED".
- ZERO deterministic trade-direction fallbacks.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.ayush_analysis_protocol import protocol_for
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.contracts import GeminiReview, ProviderCallTelemetry
from src.oracle_sol.gemini_adapter import GeminiModelAdapter

logger = logging.getLogger(__name__)

GEMINI_REVIEWER_SYSTEM_PROMPT = """You are the CITADEL ORACLE INDEPENDENT SENIOR REVIEWER (Gemini 3.8 Flash).
Your role is purely advisory review over canonical market evidence.
You possess ZERO veto authority. You do not vote or decide trades.

Focus on subtle contradictions:
1. Is aggression failing to displace price in NIFTY futures (underlying absorption)? (Do NOT confuse underlying flow with option flow).
2. Are same-contract option premiums disagreeing with spot direction?
3. Is futures basis or VWAP divergence signaling a hidden trap?
4. Symmetrical OI build is positioning, not directional proof. Total net GEX is pinning context, not net call gamma.
5. Output strictly a single valid JSON object matching the requested schema.
"""

GEMINI_REVIEWER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string"},
        "strongest_agreement": {"type": "string"},
        "strongest_disagreement": {"type": "string"},
        "relationship_primary_may_have_missed": {"type": "string"},
        "reversal_risk": {
            "type": "string",
            "enum": ["LOW", "MODERATE", "ELEVATED", "HIGH", "UNKNOWN"],
        },
        "premium_warning": {"type": "string"},
        "late_state_warning": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "interpretation",
        "strongest_agreement",
        "strongest_disagreement",
        "relationship_primary_may_have_missed",
        "reversal_risk",
        "premium_warning",
        "late_state_warning",
        "evidence_ids",
    ],
    "additionalProperties": False,
}


class GeminiReviewerAdapter:
    """Independent Senior Reviewer client wiring gemini-3.8-flash."""

    def __init__(
        self,
        backend_adapter: Optional[Any] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.backend_adapter = backend_adapter or GeminiModelAdapter()
        self.model_name = model_name or "gemini-3.7-flash"
        self.last_review: Optional[GeminiReview] = None
        self.last_latency_ms: Optional[float] = None
        self.last_http_status: Optional[int] = None  # MUST default to None, NOT 200
        self.last_telemetry: Optional[ProviderCallTelemetry] = None

    def review(self, packet: BrainPacket) -> GeminiReview:
        """Executes independent senior review over canonical BrainPacket evidence."""
        import hashlib
        start_t = time.perf_counter()
        started_iso = datetime.now(timezone.utc).isoformat()
        revision = packet.revision
        req_id = f"gem_{packet.session_id}_{packet.revision}_{int(time.time()*1000)}"

        # Compute input hash
        input_bytes = json.dumps(packet.to_dict(), sort_keys=True, default=str).encode("utf-8")
        input_hash = hashlib.sha256(input_bytes).hexdigest()

        # Initialize lifecycle telemetry with strict defaults
        call_tele = ProviderCallTelemetry(
            request_attempted=True,
            request_sent=False,
            response_received=False,
            request_id=req_id,
            model_id=self.model_name,
            http_status=None,
            started_at=started_iso,
            input_revision=revision,
            input_hash=input_hash,
        )

        # Check if live Gemini backend adapter is available
        if self.backend_adapter and hasattr(self.backend_adapter, "query_reasoning"):
            try:
                prompt = ("ANALYSIS PROTOCOL:\n" + json.dumps(protocol_for("gemini"), separators=(",", ":"))
                          + f"\nINDEPENDENT SENIOR REVIEW OVER CANONICAL EVIDENCE (REVISION {revision}):\n"
                          + json.dumps(packet.to_dict(), separators=(",", ":")))
                raw, tele, _ = self.backend_adapter.query_reasoning(
                    system_prompt=GEMINI_REVIEWER_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    schema=GEMINI_REVIEWER_OUTPUT_SCHEMA,
                    cycle_id=req_id,
                )
                latency = (time.perf_counter() - start_t) * 1000.0
                call_tele.latency_ms = latency
                call_tele.completed_at = datetime.now(timezone.utc).isoformat()
                self.last_latency_ms = latency

                # Check if an actual network request was sent
                was_sent = bool(tele.get("real_api_call_occurred") or tele.get("request_sent"))
                call_tele.request_sent = was_sent

                if was_sent:
                    # Real network call was dispatched
                    call_tele.response_received = bool(tele.get("response_received", True))
                    call_tele.http_status = tele.get("http_status")
                    self.last_http_status = call_tele.http_status
                else:
                    # Request was blocked locally before sending
                    call_tele.response_received = False
                    call_tele.http_status = None
                    call_tele.error_category = tele.get("status", "LOCAL_GUARD_BLOCKED")
                    self.last_http_status = None

                call_tele.provider_request_id = tele.get("provider_request_id")
                call_tele.schema_status = tele.get("status")

                if call_tele.request_sent and call_tele.http_status == 200 and tele.get("status") == "COMPLETED" and isinstance(raw, dict):
                    output_error = cognitive_output_error(raw, GEMINI_REVIEWER_OUTPUT_SCHEMA, packet)
                    if output_error:
                        call_tele.schema_status = output_error
                        call_tele.error_category = output_error
                        self.last_telemetry = call_tele
                        return self._handle_model_unavailable(packet, "OUTPUT_INVALID", latency, call_tele)
                    valid_eids = [eid for eid in raw.get("evidence_ids", []) if eid in packet.valid_evidence_ids]
                    out_bytes = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
                    call_tele.output_hash = hashlib.sha256(out_bytes).hexdigest()

                    rev = GeminiReview(
                        reviewed_at=call_tele.completed_at,
                        input_revision=revision,
                        interpretation=raw.get("interpretation", "CANONICAL_REVIEW"),
                        strongest_agreement=raw.get("strongest_agreement", "EVIDENCE_CONSISTENT"),
                        strongest_disagreement=raw.get("strongest_disagreement", "NONE"),
                        relationship_primary_may_have_missed=raw.get("relationship_primary_may_have_missed", "NONE"),
                        reversal_risk=raw.get("reversal_risk", "UNKNOWN"),
                        premium_warning=raw.get("premium_warning", "NONE"),
                        late_state_warning=raw.get("late_state_warning", "NONE"),
                        evidence_ids=valid_eids,
                        status="CURRENT",
                        model_name=self.model_name,
                        latency_ms=latency,
                        telemetry=call_tele,
                    )
                    self.last_review = rev
                    self.last_telemetry = call_tele
                    return rev

                status_label = "QUOTA_BLOCKED" if call_tele.http_status == 429 or "QUOTA" in str(tele.get("status")) else "UNAVAILABLE"
                self.last_telemetry = call_tele
                return self._handle_model_unavailable(packet, status_label, latency, call_tele)

            except Exception as exc:
                latency = (time.perf_counter() - start_t) * 1000.0
                err_str = str(exc).lower()
                status_label = "QUOTA_BLOCKED" if "429" in err_str or "quota" in err_str else "UNAVAILABLE"
                call_tele.latency_ms = latency
                call_tele.completed_at = datetime.now(timezone.utc).isoformat()
                call_tele.error_category = status_label
                self.last_latency_ms = latency
                self.last_http_status = 429 if "429" in err_str else None
                call_tele.http_status = self.last_http_status
                self.last_telemetry = call_tele
                logger.warning("Gemini reviewer error (%s): %s", status_label, exc)
                return self._handle_model_unavailable(packet, status_label, latency, call_tele)

        latency = (time.perf_counter() - start_t) * 1000.0
        call_tele.latency_ms = latency
        call_tele.completed_at = datetime.now(timezone.utc).isoformat()
        call_tele.error_category = "BACKEND_UNCONFIGURED"
        self.last_latency_ms = latency
        self.last_http_status = None
        self.last_telemetry = call_tele
        return self._handle_model_unavailable(packet, "UNAVAILABLE", latency, call_tele)

    def _handle_model_unavailable(
        self,
        packet: BrainPacket,
        status_label: str,
        latency: float,
        call_tele: Optional[ProviderCallTelemetry] = None,
    ) -> GeminiReview:
        """Preserves last valid review or returns clean non-directional holding state.

        ZERO hardcoded directional logic or fake trading opinions.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        if self.last_review:
            preserved = GeminiReview(
                reviewed_at=self.last_review.reviewed_at,
                input_revision=self.last_review.input_revision,
                interpretation=self.last_review.interpretation,
                strongest_agreement=self.last_review.strongest_agreement,
                strongest_disagreement=self.last_review.strongest_disagreement,
                relationship_primary_may_have_missed=self.last_review.relationship_primary_may_have_missed,
                reversal_risk=self.last_review.reversal_risk,
                premium_warning=self.last_review.premium_warning,
                late_state_warning=self.last_review.late_state_warning,
                evidence_ids=self.last_review.evidence_ids,
                status=status_label,
                model_name=self.model_name,
                latency_ms=latency,
                telemetry=call_tele or self.last_telemetry,
            )
            return preserved

        # Neutral holding state on first failure
        return GeminiReview(
            reviewed_at=now_iso,
            input_revision=packet.revision,
            interpretation="AWAITING_FIRST_ANALYSIS",
            strongest_agreement="NONE",
            strongest_disagreement="NONE",
            relationship_primary_may_have_missed="NONE",
            reversal_risk="UNKNOWN",
            premium_warning="NONE",
            late_state_warning="NONE",
            evidence_ids=[],
            status=status_label,
            model_name=self.model_name,
            latency_ms=latency,
            telemetry=call_tele or self.last_telemetry,
        )
