"""Qwen Fast Market Sentinel Adapter (Phase-1.1 Truth Repair).

Continuous fast observer role:
- Evaluates canonical processed evidence independently (Zero knowledge of GPT synthesis).
- Target model: qwen/qwen3.8-27b via Groq.
- Strictly small structured JSON output (100–250 useful tokens).
- ZERO deterministic trade-direction fallbacks. If model fails, preserves last valid
  observation and reports UNAVAILABLE / RATE_LIMITED / AWAITING_FIRST_ANALYSIS.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.ayush_analysis_protocol import protocol_for
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.contracts import ProviderCallTelemetry, QwenObservation
from src.oracle_sol.groq_adapter import GroqBrainAdapter

logger = logging.getLogger(__name__)

QWEN_SENTINEL_SYSTEM_PROMPT = """You are the CITADEL ORACLE FAST MARKET SENTINEL (qwen/qwen3.8-27b).
Your job is CONTINUOUS FAST OBSERVATION of real market dynamics.
You are an OBSERVER, NOT the final trade decision owner. Be concise, objective, and fast.

CRITICAL OPERATING & SEMANTIC RULES:
1. Ground every claim strictly in the provided canonical evidence IDs. Never cite hallucinated IDs.
2. Strict OI Semantic Rule: Symmetrical open interest build alone never resolves buyer vs writer direction. Distinguish OBSERVED from INTERPRETATION.
3. Strict GEX Semantic Rule: Positive net GEX supplies dealer pinning/volatility context (LONG_GAMMA_PIN). It is NOT net call gamma and NOT a standalone trade signal.
4. Strict Order Flow Rule: Order flow metrics (absorption, delta, aggression) derive from NIFTY futures. NEVER mislabel them as option-side flow (no "call absorption" or "sellers taking aggression on the call side").
5. Allowed continuation_status values:
   - CONTINUATION_STRENGTHENING
   - CONTINUATION_INTACT
   - CONTINUATION_LOSING_PROGRESS
   - REVERSAL_WATCH
   - REVERSAL_DEVELOPING
   - TRANSITION_UNRESOLVED
6. Output strictly a single valid JSON object matching the requested schema. Target 100-250 tokens.
"""

QWEN_SENTINEL_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "market_phase": {"type": "string"},
        "continuation_status": {
            "type": "string",
            "enum": [
                "CONTINUATION_STRENGTHENING",
                "CONTINUATION_INTACT",
                "CONTINUATION_LOSING_PROGRESS",
                "REVERSAL_WATCH",
                "REVERSAL_DEVELOPING",
                "TRANSITION_UNRESOLVED",
            ],
        },
        "current_side_pressure": {"type": "string"},
        "earliest_contradiction": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "evidence_ids"],
        },
        "aggression_price_response": {"type": "string"},
        "call_premium_response": {"type": "string"},
        "put_premium_response": {"type": "string"},
        "reversal_watch": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["NONE", "WATCH", "DEVELOPING"]},
                "direction": {"type": "string", "enum": ["PUT_TO_CALL", "CALL_TO_PUT", "NONE", "UNRESOLVED"]},
                "why": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "direction", "why", "evidence_ids"],
        },
        "strongest_new_relationship": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "market_phase",
        "continuation_status",
        "current_side_pressure",
        "earliest_contradiction",
        "aggression_price_response",
        "call_premium_response",
        "put_premium_response",
        "reversal_watch",
        "strongest_new_relationship",
        "unresolved",
    ],
    "additionalProperties": False,
}


class QwenSentinelAdapter:
    """Fast Market Sentinel client wiring qwen/qwen3.8-27b on Groq."""

    def __init__(
        self,
        backend_adapter: Optional[Any] = None,
        model_name: str = "qwen/qwen3.8-27b",
    ) -> None:
        self.model_name = model_name
        self.backend_adapter = backend_adapter or GroqBrainAdapter(model_name=self.model_name)
        self.last_observation: Optional[QwenObservation] = None
        self.last_latency_ms: Optional[float] = None
        self.last_http_status: Optional[int] = None  # MUST default to None, NOT 200
        self.last_telemetry: Optional[ProviderCallTelemetry] = None

    def observe(self, packet: BrainPacket) -> QwenObservation:
        """Executes independent sentinel analysis over canonical BrainPacket evidence."""
        import hashlib
        start_t = time.perf_counter()
        started_iso = datetime.now(timezone.utc).isoformat()
        revision = packet.revision
        req_id = f"qwen_{packet.session_id}_{packet.revision}_{int(time.time()*1000)}"

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

        # Query live model via GroqBrainAdapter
        if self.backend_adapter and hasattr(self.backend_adapter, "invoke_reasoning"):
            try:
                prompt = self._build_sentinel_prompt(packet)
                call_tele.request_sent = True
                raw, tele = self.backend_adapter.invoke_reasoning(
                    system_prompt=QWEN_SENTINEL_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    schema=QWEN_SENTINEL_OUTPUT_SCHEMA,
                    request_id=req_id,
                )
                latency = (time.perf_counter() - start_t) * 1000.0
                call_tele.latency_ms = latency
                call_tele.completed_at = datetime.now(timezone.utc).isoformat()
                self.last_latency_ms = latency

                # Capture actual HTTP status from adapter response
                http_st = tele.get("http_status")
                call_tele.http_status = http_st
                self.last_http_status = http_st
                call_tele.response_received = http_st is not None
                call_tele.provider_request_id = tele.get("request_id")
                call_tele.prompt_tokens = tele.get("prompt_tokens", 0)
                call_tele.completion_tokens = tele.get("completion_tokens", 0)
                call_tele.total_tokens = tele.get("total_tokens", 0)
                call_tele.cached_tokens = tele.get("cached_tokens", 0)
                call_tele.schema_status = tele.get("schema_status")
                call_tele.rate_headers = tele.get("rate_limits")

                if http_st == 200 and tele.get("schema_status") == "SCHEMA_VALID_JSON" and isinstance(raw, dict):
                    output_error = cognitive_output_error(raw, QWEN_SENTINEL_OUTPUT_SCHEMA, packet)
                    if output_error:
                        call_tele.schema_status = output_error
                        call_tele.error_category = output_error
                        self.last_telemetry = call_tele
                        return self._handle_model_unavailable(packet, "OUTPUT_INVALID", latency, call_tele)
                    out_bytes = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
                    call_tele.output_hash = hashlib.sha256(out_bytes).hexdigest()

                    contra = raw.get("earliest_contradiction", {})
                    if not isinstance(contra, dict):
                        contra = {"summary": str(contra), "evidence_ids": []}

                    rw = raw.get("reversal_watch", {})
                    if not isinstance(rw, dict):
                        rw = {"status": "NONE", "direction": "NONE", "why": str(rw), "evidence_ids": []}

                    all_eids = list(contra.get("evidence_ids", [])) + list(rw.get("evidence_ids", []))
                    valid_eids = [eid for eid in all_eids if eid in packet.valid_evidence_ids]

                    obs = QwenObservation(
                        observed_at=call_tele.completed_at,
                        input_revision=revision,
                        market_phase=raw.get("market_phase", "OBSERVATION"),
                        continuation_status=raw.get("continuation_status", "TRANSITION_UNRESOLVED"),
                        current_side_pressure=raw.get("current_side_pressure", "UNRESOLVED"),
                        earliest_contradiction=contra,
                        aggression_price_response=raw.get("aggression_price_response", "UNRESOLVED"),
                        call_premium_response=raw.get("call_premium_response", "UNRESOLVED"),
                        put_premium_response=raw.get("put_premium_response", "UNRESOLVED"),
                        reversal_watch=rw,
                        strongest_new_relationship=raw.get("strongest_new_relationship", "NONE"),
                        unresolved=raw.get("unresolved", []),
                        evidence_ids=valid_eids,
                        model_name=self.model_name,
                        status="CURRENT",
                        latency_ms=latency,
                        telemetry=call_tele,
                    )
                    self.last_observation = obs
                    self.last_telemetry = call_tele
                    return obs

                # Provider rate-limited or error
                status_label = "RATE_LIMITED" if http_st == 429 else "UNAVAILABLE"
                call_tele.error_category = tele.get("error", status_label)
                self.last_telemetry = call_tele
                logger.warning("Qwen invocation non-successful (%s, http=%s)", status_label, http_st)
                return self._handle_model_unavailable(packet, status_label, latency, call_tele)

            except Exception as exc:
                latency = (time.perf_counter() - start_t) * 1000.0
                err_str = str(exc).lower()
                status_label = "RATE_LIMITED" if "429" in err_str or "rate" in err_str else "UNAVAILABLE"
                call_tele.latency_ms = latency
                call_tele.completed_at = datetime.now(timezone.utc).isoformat()
                call_tele.error_category = status_label
                self.last_latency_ms = latency
                self.last_http_status = 429 if "429" in err_str else None
                call_tele.http_status = self.last_http_status
                self.last_telemetry = call_tele
                logger.warning("Qwen backend adapter exception (%s): %s", status_label, exc)
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
    ) -> QwenObservation:
        """Preserves last valid observation or returns clean non-directional holding state.

        ZERO hardcoded directional logic or fake trading opinions.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        if self.last_observation:
            # Preserve last valid observation without fabricating new direction
            preserved = QwenObservation(
                observed_at=self.last_observation.observed_at,
                input_revision=self.last_observation.input_revision,
                market_phase=self.last_observation.market_phase,
                continuation_status=self.last_observation.continuation_status,
                current_side_pressure=self.last_observation.current_side_pressure,
                earliest_contradiction=self.last_observation.earliest_contradiction,
                aggression_price_response=self.last_observation.aggression_price_response,
                call_premium_response=self.last_observation.call_premium_response,
                put_premium_response=self.last_observation.put_premium_response,
                reversal_watch=self.last_observation.reversal_watch,
                strongest_new_relationship=self.last_observation.strongest_new_relationship,
                unresolved=self.last_observation.unresolved,
                evidence_ids=self.last_observation.evidence_ids,
                model_name=self.model_name,
                status=status_label,
                latency_ms=latency,
                telemetry=call_tele or self.last_telemetry,
            )
            return preserved

        # Neutral holding state on first failure
        return QwenObservation(
            observed_at=now_iso,
            input_revision=packet.revision,
            market_phase="OBSERVATION",
            continuation_status="TRANSITION_UNRESOLVED",
            current_side_pressure="UNRESOLVED",
            earliest_contradiction={"summary": "Awaiting canonical observation", "evidence_ids": []},
            aggression_price_response="UNRESOLVED",
            call_premium_response="UNRESOLVED",
            put_premium_response="UNRESOLVED",
            reversal_watch={"status": "NONE", "direction": "NONE", "why": "None", "evidence_ids": []},
            strongest_new_relationship="NONE",
            unresolved=[],
            evidence_ids=[],
            model_name=self.model_name,
            status=status_label,
            latency_ms=latency,
            telemetry=call_tele or self.last_telemetry,
        )

    def _build_sentinel_prompt(self, packet: BrainPacket) -> str:
        packet_dict = packet.to_dict()
        # Strictly zero echo chamber: strip GPT thesis from Qwen input
        packet_dict.pop("previous_thesis", None)
        return ("ANALYSIS PROTOCOL:\n" + json.dumps(protocol_for("qwen"), separators=(",", ":"))
                + f"\nCANONICAL PROCESSED MARKET EVIDENCE (REVISION {packet.revision}):\n"
                + json.dumps(packet_dict, separators=(",", ":")))
