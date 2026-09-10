"""GPT-OSS Primary Deep Synthesizer Adapter (Phase-1.1 Truth Repair).

Primary Synthesizer role:
- Evaluates ALL FIVE hypotheses concurrently:
  1. CALL_CONTINUATION
  2. PUT_CONTINUATION
  3. PUT_TO_CALL_REVERSAL
  4. CALL_TO_PUT_REVERSAL
  5. NO_TRADE_TRANSITION
- Produces compact operational decision output (current_state, setup_family, entry_window, why_now, reversal_watch).
- Target model: openai/gpt-oss-120b via Groq.
- Zero echo chamber: Qwen & Gemini inputs are explicitly tagged UNTRUSTED_MODEL_HYPOTHESIS.
  GPT is barred from citing peer opinions as canonical evidence.
- ZERO deterministic trade-direction fallbacks. If model fails, preserves last valid
  synthesis and reports UNAVAILABLE / RATE_LIMITED / AWAITING_FIRST_ANALYSIS.
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
from src.oracle_sol.contracts import (
    GeminiReview,
    HypothesisState,
    PrimarySynthesisOutput,
    ProviderCallTelemetry,
    QwenObservation,
)
from src.oracle_sol.groq_adapter import GroqBrainAdapter

logger = logging.getLogger(__name__)

SYNTHESIZER_SYSTEM_PROMPT = """You are the CITADEL ORACLE PRIMARY DEEP SYNTHESIZER (openai/gpt-oss-120b).
You evaluate canonical market evidence across five concurrent hypotheses without forcing a single winner.

REASONING METHODOLOGY:
Your analysis must strictly distinguish:
- FACT: canonical data directly observed in evidence (e.g. spot price, LTP, flow delta, strike OI change).
- RELATIONSHIP: how two or more facts changed together (e.g. underlying price progress vs option premium expansion vs passive order flow refills).
- INTERPRETATION: what hypothesis is strengthened or weakened by that relationship.

CRITICAL OPERATING & SEMANTIC RULES:
1. STRICT GROUNDING IN EVIDENCE IDS:
   Ground every claim in canonical evidence IDs from the packet (e.g. metric:..., rel:..., evt_...).
   Never cite hallucinated or unprovided IDs.
2. ZERO MODEL-TO-MODEL ECHO CHAMBERS:
   Qwen and Gemini inputs are labeled [UNTRUSTED_MODEL_HYPOTHESIS].
   You MUST NOT cite peer opinions (qwen:... or gemini:...) as market evidence.
3. OPEN INTEREST (OI) SEMANTIC FIREWALL:
   - Symmetrical open interest build alone NEVER establishes directional conviction or distinguishes buyer vs writer.
   - You MUST distinguish OBSERVED (e.g. "Call OI increased at strike X") from INTERPRETATION (which requires corroborating premium + underlying + IV + aggression evidence).
   - FORBIDDEN: "Call OI build supports CALL", "Call OI build is bullish", "Call OI confirms CALL" unless independent canonical price/premium/flow evidence resolves direction.
4. DEALER GEX SEMANTIC FIREWALL:
   - Positive net GEX supplies aggregate dealer gamma exposure and volatility pinning context (e.g. LONG_GAMMA_PIN).
   - Positive net GEX must NEVER be translated into "net call gamma", "call gamma dominates", or "bullish gamma".
   - GEX is NOT a standalone directional signal. Positive GEX alone cannot support CALL; negative GEX alone cannot support PUT.
5. ORDER FLOW & ABSORPTION SEMANTIC FIREWALL:
   - Order flow metrics (seller_absorption, buyer_absorption, failed_aggression, flow_net_delta) derive strictly from NIFTY FUTURES.
   - NEVER mislabel underlying futures order flow as option-side flow! (FORBIDDEN: "call absorption", "absorption on the call side", "sellers taking aggression on the call side", "put-side absorption").
   - seller_absorption means aggressive selling in NIFTY futures met passive bids refilling with poor downside progress.
   - Numeric absorption values (e.g. 0.3028) must NOT be qualitatively labeled HIGH, LOW, STRONG, or WEAK unless canonical state is SELLERS_ABSORBED or BUYERS_ABSORBED (0.45 threshold). Reason relationally through numbers.
6. WHY_NOW REQUIREMENTS:
   - Every bullet MUST represent a multi-factor market relationship between multiple facts, not an isolated single indicator reading (no "PCR = X", "GEX is positive", "Call OI is 2x").
   - Every bullet must cite at least one evidence ID.
7. ENTRY_WINDOW REQUIREMENTS:
   - ENTRY_WINDOW = READY requires grounded NOW reasoning explaining why the opportunity is actionable now and what specific invalidation conditions would change your mind.
8. CONCURRENT 5 HYPOTHESES:
   Concurrently evaluate: call_continuation, put_continuation, put_to_call_reversal, call_to_put_reversal, no_trade_transition.
   Classify supporting evidence into DIRECT_DIRECTIONAL, CONFIRMING_CONTEXT, NON_DIRECTIONAL_CONTEXT, or UNRESOLVED.
   Do NOT build a primary CALL or PUT thesis primarily from NON_DIRECTIONAL_CONTEXT.
9. OUTPUT FORMAT:
   Strictly emit a single valid JSON object matching the requested schema.
"""

SYNTHESIZER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "current_state": {
            "type": "string",
            "enum": ["CALL", "PUT", "CALL_DEVELOPING", "PUT_DEVELOPING", "REVERSAL_WATCH", "NO_TRADE"],
        },
        "setup_family": {
            "type": "string",
            "enum": ["CONTINUATION", "REVERSAL", "TRANSITION", "UNRESOLVED"],
        },
        "entry_window": {
            "type": "string",
            "enum": ["READY", "APPROACHING", "WAIT", "INVALID", "UNRESOLVED"],
        },
        "why_now": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
            "description": "Each bullet must include its original canonical evidence ID(s) inline in square brackets. A root evidence_ids list does not attribute evidence to individual bullets. Never cite memo codes or model opinions.",
        },
        "reversal_watch": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["PUT_TO_CALL", "CALL_TO_PUT", "NONE", "UNRESOLVED"]},
                "status": {"type": "string", "enum": ["NONE", "WATCH", "DEVELOPING"]},
                "first_contradiction": {"type": "string"},
                "what_failed": {"type": "string"},
                "premium_confirmation": {"type": "string", "enum": ["CONFIRMING", "PARTIAL", "DIVERGING", "UNRESOLVED"]},
                "what_still_opposes": {"type": "string"},
                "why_not_confirmed": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "direction",
                "status",
                "first_contradiction",
                "what_failed",
                "premium_confirmation",
                "what_still_opposes",
                "why_not_confirmed",
                "evidence_ids",
            ],
        },
        "option_buyer_side": {
            "type": "string",
            "enum": ["CALL_FAVOURABLE", "PUT_FAVOURABLE", "BOTH_POOR", "UNRESOLVED"],
        },
        "premium_confirmation": {
            "type": "string",
            "enum": ["CONFIRMING", "PARTIAL", "DIVERGING", "UNRESOLVED"],
        },
        "what_would_change_my_mind": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 2,
        },
        "five_hypotheses": {
            "type": "object",
            "properties": {
                "call_continuation": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
                        "why": {"type": "string"},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "premium_confirmation": {"type": "string"},
                        "what_changed_since_previous": {"type": "string"},
                    },
                    "required": ["status", "why", "supporting_evidence_ids", "opposing_evidence_ids", "premium_confirmation", "what_changed_since_previous"],
                },
                "put_continuation": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
                        "why": {"type": "string"},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "premium_confirmation": {"type": "string"},
                        "what_changed_since_previous": {"type": "string"},
                    },
                    "required": ["status", "why", "supporting_evidence_ids", "opposing_evidence_ids", "premium_confirmation", "what_changed_since_previous"],
                },
                "put_to_call_reversal": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
                        "why": {"type": "string"},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "premium_confirmation": {"type": "string"},
                        "what_changed_since_previous": {"type": "string"},
                    },
                    "required": ["status", "why", "supporting_evidence_ids", "opposing_evidence_ids", "premium_confirmation", "what_changed_since_previous"],
                },
                "call_to_put_reversal": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
                        "why": {"type": "string"},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "premium_confirmation": {"type": "string"},
                        "what_changed_since_previous": {"type": "string"},
                    },
                    "required": ["status", "why", "supporting_evidence_ids", "opposing_evidence_ids", "premium_confirmation", "what_changed_since_previous"],
                },
                "no_trade_transition": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
                        "why": {"type": "string"},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "opposing_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "premium_confirmation": {"type": "string"},
                        "what_changed_since_previous": {"type": "string"},
                    },
                    "required": ["status", "why", "supporting_evidence_ids", "opposing_evidence_ids", "premium_confirmation", "what_changed_since_previous"],
                },
            },
            "required": [
                "call_continuation",
                "put_continuation",
                "put_to_call_reversal",
                "call_to_put_reversal",
                "no_trade_transition",
            ],
        },
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "current_state",
        "setup_family",
        "entry_window",
        "why_now",
        "reversal_watch",
        "option_buyer_side",
        "premium_confirmation",
        "what_would_change_my_mind",
        "five_hypotheses",
        "evidence_ids",
    ],
    "additionalProperties": False,
}


class SynthesizerAdapter:
    """Primary Deep Synthesizer client wiring openai/gpt-oss-120b on Groq."""

    def __init__(
        self,
        backend_adapter: Optional[Any] = None,
        model_name: str = "openai/gpt-oss-120b",
    ) -> None:
        self.model_name = model_name
        self.backend_adapter = backend_adapter or GroqBrainAdapter(model_name=self.model_name)
        self.last_synthesis: Optional[PrimarySynthesisOutput] = None
        self.last_latency_ms: Optional[float] = None
        self.last_http_status: Optional[int] = None  # MUST default to None, NOT 200
        self.last_telemetry: Optional[ProviderCallTelemetry] = None

    def synthesize(
        self,
        packet: BrainPacket,
        qwen_obs: Optional[QwenObservation] = None,
        gemini_rev: Optional[GeminiReview] = None,
    ) -> PrimarySynthesisOutput:
        """Executes deep primary synthesis across all 5 hypotheses concurrently."""
        import hashlib
        start_t = time.perf_counter()
        started_iso = datetime.now(timezone.utc).isoformat()
        revision = packet.revision
        req_id = f"gpt_{packet.session_id}_{packet.revision}_{int(time.time()*1000)}"

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
                prompt = self._build_synthesizer_prompt(packet, qwen_obs, gemini_rev)
                call_tele.request_sent = True
                raw, tele = self.backend_adapter.invoke_reasoning(
                    system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    schema=SYNTHESIZER_OUTPUT_SCHEMA,
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
                    output_error = cognitive_output_error(raw, SYNTHESIZER_OUTPUT_SCHEMA, packet)
                    if output_error:
                        call_tele.schema_status = output_error
                        call_tele.error_category = output_error
                        self.last_telemetry = call_tele
                        return self._handle_model_unavailable(packet, "OUTPUT_INVALID", latency, call_tele)
                    out_bytes = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
                    call_tele.output_hash = hashlib.sha256(out_bytes).hexdigest()

                    cited_eids = [eid for eid in raw.get("evidence_ids", []) if eid in packet.valid_evidence_ids]
                    rw = raw.get("reversal_watch", {})
                    if not isinstance(rw, dict):
                        rw = {"direction": "NONE", "status": "NONE", "first_contradiction": "NONE", "what_failed": "NONE", "premium_confirmation": "UNRESOLVED", "what_still_opposes": "", "why_not_confirmed": "", "evidence_ids": []}

                    synth = PrimarySynthesisOutput(
                        current_state=raw["current_state"],
                        setup_family=raw.get("setup_family", "TRANSITION"),
                        entry_window=raw.get("entry_window", "WAIT"),
                        why_now=raw.get("why_now", [])[:3],
                        reversal_watch=rw,
                        option_buyer_side=raw.get("option_buyer_side", "UNRESOLVED"),
                        premium_confirmation=raw.get("premium_confirmation", "UNRESOLVED"),
                        what_would_change_my_mind=raw.get("what_would_change_my_mind", [])[:2],
                        five_hypotheses=raw.get("five_hypotheses", {}),
                        evidence_ids=cited_eids,
                        model_name=self.model_name,
                        status="CURRENT",
                        input_revision=revision,
                        synthesized_at=call_tele.completed_at,
                        latency_ms=latency,
                        telemetry=call_tele,
                    )
                    self.last_synthesis = synth
                    self.last_telemetry = call_tele
                    return synth

                status_label = "RATE_LIMITED" if http_st == 429 else "UNAVAILABLE"
                call_tele.error_category = tele.get("error", status_label)
                self.last_telemetry = call_tele
                logger.warning("GPT invocation non-successful (%s, http=%s)", status_label, http_st)
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
                logger.warning("GPT backend adapter exception (%s): %s", status_label, exc)
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
    ) -> PrimarySynthesisOutput:
        """Preserves last valid synthesis or returns clean non-directional holding state.

        ZERO hardcoded directional logic or fake trading opinions.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        if self.last_synthesis:
            preserved = PrimarySynthesisOutput(
                current_state=self.last_synthesis.current_state,
                setup_family=self.last_synthesis.setup_family,
                entry_window=self.last_synthesis.entry_window,
                why_now=self.last_synthesis.why_now,
                reversal_watch=self.last_synthesis.reversal_watch,
                option_buyer_side=self.last_synthesis.option_buyer_side,
                premium_confirmation=self.last_synthesis.premium_confirmation,
                what_would_change_my_mind=self.last_synthesis.what_would_change_my_mind,
                five_hypotheses=self.last_synthesis.five_hypotheses,
                evidence_ids=self.last_synthesis.evidence_ids,
                model_name=self.model_name,
                status=status_label,
                input_revision=self.last_synthesis.input_revision,
                synthesized_at=self.last_synthesis.synthesized_at,
                latency_ms=latency,
                telemetry=call_tele or self.last_telemetry,
            )
            return preserved

        return PrimarySynthesisOutput(
            current_state="AWAITING_FIRST_ANALYSIS",
            setup_family="UNRESOLVED",
            entry_window="WAIT",
            why_now=["Awaiting canonical model inference"],
            reversal_watch={"direction": "NONE", "status": "NONE", "first_contradiction": "None", "what_failed": "None", "premium_confirmation": "UNRESOLVED", "what_still_opposes": "", "why_not_confirmed": "", "evidence_ids": []},
            option_buyer_side="UNRESOLVED",
            premium_confirmation="UNRESOLVED",
            what_would_change_my_mind=["Receipt of live model inference"],
            five_hypotheses={},
            evidence_ids=[],
            model_name=self.model_name,
            status=status_label,
            input_revision=packet.revision,
            synthesized_at=now_iso,
            latency_ms=latency,
            telemetry=call_tele or self.last_telemetry,
        )

    def _build_synthesizer_prompt(
        self,
        packet: BrainPacket,
        qwen_obs: Optional[QwenObservation],
        gemini_rev: Optional[GeminiReview],
    ) -> str:
        semantic_boundaries = """SEMANTIC METADATA & BOUNDARIES:
- metric:seller_absorption: instrument=NIFTY_FUTURES, producer=ORDER_FLOW_FEATURES, unit=ratio (0 to 1). Meaning: Underlying NIFTY futures passive order flow response where aggressive selling met passive bid refills with poor downward price progress. Canonical threshold for SELLERS_ABSORBED is 0.45; lower values are MIXED. NOT an option-side flow metric. Must NOT be called "call absorption" or "sellers taking aggression on the call side". Do NOT invent qualitative buckets (HIGH/LOW) for numeric values.
- metric:buyer_absorption: instrument=NIFTY_FUTURES, producer=ORDER_FLOW_FEATURES, unit=ratio (0 to 1). Meaning: Underlying NIFTY futures passive order flow response where aggressive buying met passive ask refills. Canonical threshold for BUYERS_ABSORBED is 0.45. NOT an option-side flow metric.
- metric:call_oi_build / metric:put_oi_build: instrument=NIFTY_OPTIONS. Meaning: Open interest activity in Call/Put strikes. Symmetrical OI build alone cannot establish directional conviction or distinguish buyer vs writer without corroborating price/premium/flow. Forbidden: claiming OI build alone is bullish or supports CALL.
- metric:total_net_gex_inr_cr: instrument=NIFTY_DERIVATIVES, unit=INR Crores. Meaning: Market maker aggregate gamma exposure. Volatility / pinning / amplification context. Positive GEX means dealer long gamma / pinning context (e.g. LONG_GAMMA_PIN). Forbidden: translating positive GEX into "net call gamma" or claiming it confirms CALL direction.
- metric:dealer_regime: instrument=NIFTY_DERIVATIVES (e.g. LONG_GAMMA_PIN). Context for volatility dampening, NOT a standalone directional signal."""

        prompt_sections = [
            "ANALYSIS PROTOCOL:\n" + json.dumps(protocol_for("gpt"), separators=(",", ":")),
            semantic_boundaries,
            f"\nCANONICAL MARKET EVIDENCE (REVISION {packet.revision}):",
            json.dumps(packet.to_dict(), separators=(",", ":")),
        ]

        if qwen_obs:
            prompt_sections.append(
                "\n[UNTRUSTED_MODEL_HYPOTHESIS - QWEN SENTINEL OBSERVATION - DO NOT CITE AS CANONICAL EVIDENCE]:\n"
                + json.dumps(qwen_obs.to_dict(), indent=1)
            )

        if gemini_rev:
            prompt_sections.append(
                "\n[UNTRUSTED_MODEL_HYPOTHESIS - GEMINI SENIOR REVIEW - DO NOT CITE AS CANONICAL EVIDENCE]:\n"
                + json.dumps(gemini_rev.to_dict(), indent=1)
            )

        prompt_sections.append("\nSYNTHESIZE ALL 5 HYPOTHESES CONCURRENTLY. CITE ONLY CANONICAL EVIDENCE IDS:")
        return "\n".join(prompt_sections)
