"""CITADEL Multi-Model Live Shadow Implementation V1.3 — Specialist Contracts & Adapters.

Defines:
1. Gemini Fast Scout (gemini-3.7-flash):
   - Fast reflexivity, flow shifts, pressure exhaustion, reversal watch, gamma changes.
   - Output: semantic_state, headline, bullets (max 3), missing_evidence, deserves_luna_review.
   - Strict order-flow missing evidence guard: forbids asserting aggression/absorption if flow missing.

2. Sol Option Specialist (gpt-5.6-sol):
   - Evaluates whether buying the relevant option is attractive NOW (pricing, IV, basis, decay).
   - Output: buying_state, headline, bullets (max 3), missing_evidence.

3. Immutable challenger artifact persistence in data/sol_shadow/challengers/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import jsonschema
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.luna_input_receipt import persist_receipt, digest, valid_binding
from src.oracle_sol.experiential_adapter import ExperientialAdapter
from src.oracle_sol.privacy_sanitizer import (
    PrivacyViolationError,
    sanitize_brain_packet,
    verify_sanitized_payload,
)
from src.oracle_sol.shadow_orchestrator import (
    AI_EXECUTION_INFLUENCE,
    AI_VOB_INFLUENCE,
    BROKER_SUBMISSION,
    GEMINI_SCOUT_MODEL_ID,
    SOL_CHALLENGER_MODEL_ID,
    CanonicalShadowReceipt,
    GeminiEvidenceGuard,
    canonical_digest,
)

logger = logging.getLogger(__name__)

CHALLENGER_ARTIFACT_DIR = "data/sol_shadow/challengers"
REQUEST_RECEIPT_DIR = "data/sol_shadow/luna_inputs"

# =====================================================================
# 1. SPECIALIST DATA STRUCTURES & SCHEMAS
# =====================================================================

GEMINI_SEMANTIC_STATES = (
    "POSSIBLE_REVERSAL",
    "FLOW_SHIFT",
    "FAILED_PRESSURE",
    "ABSORPTION",
    "CONTROL_STABLE",
    "UNKNOWN",
)

SOL_BUYING_STATES = (
    "CALL_ATTRACTIVE",
    "PUT_ATTRACTIVE",
    "WAIT",
    "AVOID_CHASE",
    "UNRESOLVED",
)


@dataclass(frozen=True)
class GeminiScoutOutput:
    schema_version: str = "1.3.0-fast-scout"
    role: str = "FAST_SCOUT"
    model_id: str = GEMINI_SCOUT_MODEL_ID
    receipt_id: str = ""
    revision: int = 0
    semantic_state: str = "UNKNOWN"
    headline: str = ""
    bullets: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    deserves_luna_review: bool = False
    unsupported_inference_flag: bool = False
    unsupported_inference_reason: Optional[str] = None
    evaluated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SolOptionSpecialistOutput:
    schema_version: str = "1.3.0-option-specialist"
    role: str = "OPTION_SPECIALIST"
    model_id: str = SOL_CHALLENGER_MODEL_ID
    receipt_id: str = ""
    revision: int = 0
    buying_state: str = "UNRESOLVED"
    headline: str = ""
    bullets: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    direction_vs_trade_quality_conflict: bool = False
    evaluated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =====================================================================
# 2. PROMPT INSTRUCTIONS & NATIVE JSON SCHEMAS
# =====================================================================

GEMINI_SCOUT_INSTRUCTIONS = """You are CITADEL's Fast Reflexivity and Flow Scout (gemini-3.7-flash).
Your duty is rapid situational awareness:
- Detect fast changes, control shifts, failed pressure, reversal pressure, gamma/flow reflexivity, and subtle market dynamics a human might overlook quickly.
- Do NOT issue trading commands or make execution recommendations.
- Keep prose concise, grounded, and in plain English.
- Return EXACTLY 1 headline (under 15 words) and AT MOST 3 bullet points (1 short sentence each).
- State must be one of: "POSSIBLE_REVERSAL", "FLOW_SHIFT", "FAILED_PRESSURE", "ABSORPTION", "CONTROL_STABLE", "UNKNOWN".

CRITICAL EVIDENCE HONESTY RULE:
- If order flow metrics (CVD, MLOFI, flow_net_delta) are missing, UNAVAILABLE, or null, DO NOT invent buyer aggression, seller aggression, absorption, or CVD control.
- List all missing or unavailable metrics in 'missing_evidence'.
- If the observation is significant enough that Luna should review it before standard cadence, set 'deserves_luna_review' = true; otherwise false.
- Cite supplied canonical evidence_ids. Distinguish current levels from temporal change. Missing confirmation is not contrary evidence. Flow statistics alone do not prove absorption or participant identity.
"""

GEMINI_SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.3.0-fast-scout"]},
        "role": {"type": "string", "enum": ["FAST_SCOUT"]},
        "semantic_state": {
            "type": "string",
            "enum": list(GEMINI_SEMANTIC_STATES),
        },
        "headline": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "missing_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "deserves_luna_review": {"type": "boolean"},
    },
    "required": [
        "schema_version",
        "role",
        "semantic_state",
        "headline",
        "bullets",
        "missing_evidence",
        "deserves_luna_review",
    ],
    "additionalProperties": False,
}

SOL_OPTION_SPECIALIST_INSTRUCTIONS = """You are CITADEL's Option Economics Specialist (gpt-5.6-sol).
Your sole mission is to judge whether buying the relevant option (CE or PE) is actually attractive NOW, even if underlying direction seems correct.
Evaluate:
- IV level and IV change (cheap vs expensive volatility)
- Premium expansion or stretch (are buyers chasing late?)
- Futures basis drag and carry costs
- Time decay and risk/reward payoff structure

State must be one of:
- "CALL_ATTRACTIVE": Spot directional setup is supported by attractive option pricing / IV.
- "PUT_ATTRACTIVE": Downside setup is supported by attractive option pricing / IV.
- "WAIT": Volatility or premium conditions are not clear; wait for better pricing.
- "AVOID_CHASE": Underlying moved, but premium/IV expanded too much; risk/reward is unfavorable for fresh long options.
- "UNRESOLVED": Key option metrics are missing or conflicting.

Format:
- Keep prose concise, direct, and in plain English (no trader jargon or essays).
- Return EXACTLY 1 headline (under 15 words) and AT MOST 3 bullet points (1 short sentence each).
- List any missing inputs in 'missing_evidence'.
- Flag 'direction_vs_trade_quality_conflict' = true if underlying direction is right but the option buy is bad.
- Cite supplied canonical evidence_ids. Do not equate high IV with expensive options without comparative evidence. Basis sign is not direction or option drag by itself. Do not infer aggressor side from OI or premium. Missing theta, time remaining, fair value or classified trades must remain unknown. Compare same-security premium/IV changes to underlying response; direction and buying quality are different questions.
"""

SOL_OPTION_SPECIALIST_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.3.0-option-specialist"]},
        "role": {"type": "string", "enum": ["OPTION_SPECIALIST"]},
        "buying_state": {
            "type": "string",
            "enum": list(SOL_BUYING_STATES),
        },
        "headline": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "missing_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "direction_vs_trade_quality_conflict": {"type": "boolean"},
    },
    "required": [
        "schema_version",
        "role",
        "buying_state",
        "headline",
        "bullets",
        "missing_evidence",
        "direction_vs_trade_quality_conflict",
    ],
    "additionalProperties": False,
}


# =====================================================================
# 3. IMMUTABLE ARTIFACT PERSISTENCE
# =====================================================================

for _schema in (GEMINI_SCOUT_SCHEMA, SOL_OPTION_SPECIALIST_SCHEMA):
    _schema["properties"]["evidence_ids"] = {"type": "array", "items": {"type": "string"}, "minItems": 1}
    _schema["required"].append("evidence_ids")


def _validate_specialist(output, schema, packet):
    jsonschema.validate(output, schema)
    ids = output["evidence_ids"]
    if packet is None or any(eid not in packet.valid_evidence_ids for eid in ids):
        return "UNRESOLVED_EVIDENCE_ID"
    supplied = sanitize_brain_packet(packet)
    visible_ids = {fact.get("evidence_id") for fact in supplied["current_facts"].values()}
    visible_ids.update(event.get("event_id") for frame in supplied["timeline"] for event in frame["events"])
    if any(eid not in visible_ids for eid in ids):
        return "EVIDENCE_NOT_IN_OUTBOUND_PACKET"
    for claim in [output["headline"], *output["bullets"]]:
        error = EvidenceGate.validate_factual_claim(claim, ids, packet)
        if error:
            return error
    return None


def validated_specialist_view(view):
    """Disk/UI records require the same exact input/output proof as live results."""
    if not isinstance(view, dict):
        return False
    telemetry = view.get("telemetry") or {}
    raw = telemetry.get("validated_output")
    receipt = telemetry.get("input_receipt") or {}
    return (isinstance(raw, dict)
            and telemetry.get("validation_status") == "ACCEPTED"
            and view.get("receipt_id") == receipt.get("parent_receipt_id")
            and valid_binding(receipt, raw, view.get("session_date"), view.get("revision"), view.get("model_id"))
            and all(view.get(key) == value for key, value in raw.items()))


def persist_challenger_artifact(
    role: str,
    receipt_id: str,
    revision: int,
    session_date: str,
    payload: Dict[str, Any],
    base_dir: str = CHALLENGER_ARTIFACT_DIR,
) -> str:
    """Persists a challenger output immutably to disk bound to receipt and revision."""
    target_dir = Path(base_dir) / session_date
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{receipt_id[:16]}_rev{revision}_{role.lower()}.json"
    target_path = target_dir / filename

    data = {
        "parent_receipt_id": receipt_id,
        "parent_revision": revision,
        "session_date": session_date,
        "role": role,
        "persisted_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }

    with open(target_path, "x", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return str(target_path)


# =====================================================================
# 4. GEMINI FAST SCOUT ADAPTER
# =====================================================================

class GeminiScoutAdapter:
    """Invokes gemini-3.7-flash with strict privacy sanitization and evidence guards."""

    def __init__(
        self,
        model_name: str = GEMINI_SCOUT_MODEL_ID,
        backend: Optional[ExperientialAdapter] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.backend = backend or ExperientialAdapter(
            model_name=self.model_name,
            enforce_zero_cost=True,
            reject_substituted_model=True,
        )
        self.timeout_seconds = timeout_seconds
        self.last_telemetry: Dict[str, Any] = {}

    def is_available(self) -> bool:
        return self.backend.is_available()

    def analyze(
        self,
        receipt: CanonicalShadowReceipt,
        packet: Optional[BrainPacket] = None,
    ) -> Tuple[Optional[GeminiScoutOutput], Dict[str, Any]]:
        """Executes a bounded reasoning call on gemini-3.7-flash."""
        request_id = f"scout_{receipt.receipt_id[:12]}_rev_{receipt.revision}"
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
        }

        # Guard constraints for prompt
        constraints = GeminiEvidenceGuard.prepare_gemini_prompt_constraints(receipt)
        system_prompt = f"{GEMINI_SCOUT_INSTRUCTIONS}\n\n{constraints}"

        if packet is None:
            telemetry["status"] = "CANONICAL_PACKET_REQUIRED"
            return None, telemetry
        user_prompt_data = sanitize_brain_packet(packet)
        payload_str = json.dumps(user_prompt_data, indent=2)
        request_receipt = {}
        def before_send(body):
            request_receipt.update(persist_receipt(REQUEST_RECEIPT_DIR, body, packet))

        try:
            valid, reason = verify_sanitized_payload(payload_str)
            if not valid:
                telemetry["error_class"] = "PRIVACY_VIOLATION_BLOCKED"
                telemetry["error"] = reason
                self.last_telemetry = telemetry
                return None, telemetry
        except Exception as exc:
            telemetry["error_class"] = "SANITIZATION_FAILED"
            telemetry["error"] = str(exc)
            self.last_telemetry = telemetry
            return None, telemetry

        try:
            output_json, raw_tel = self.backend.invoke_reasoning(
                request_id=request_id,
                system_prompt=system_prompt,
                user_prompt=payload_str,
                schema=GEMINI_SCOUT_SCHEMA,
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=2500,
                structured_mode="NATIVE_JSON_SCHEMA",
                single_attempt=True,
                before_send=before_send,
            )
            telemetry.update(raw_tel)
            telemetry["input_receipt"] = request_receipt
            self.last_telemetry = telemetry

            if output_json is None:
                telemetry["status"] = raw_tel.get("error_class") or "FAILED"
                return None, telemetry

            request_receipt["output_hash"] = digest(output_json)
            if not valid_binding(request_receipt, output_json, packet.session_id, packet.revision, self.model_name):
                telemetry["status"], telemetry["error"] = "REJECTED", "INPUT_RECEIPT_MISMATCH"
                return None, telemetry
            telemetry["audit_path"] = persist_challenger_artifact(
                "GEMINI_RAW", receipt.receipt_id, receipt.revision, receipt.session_date,
                {"output": output_json, "input_receipt": request_receipt, "validation_status": "NOT_YET_VALIDATED"})

            error = _validate_specialist(output_json, GEMINI_SCOUT_SCHEMA, packet)
            if error:
                telemetry["status"], telemetry["error"] = "REJECTED", error
                return None, telemetry

            # Validate evidence guard on raw response
            full_text = f"{output_json.get('headline', '')} {' '.join(output_json.get('bullets', []))}"
            is_valid_evidence, unsupported_reason = GeminiEvidenceGuard.validate_gemini_response(
                full_text, receipt
            )

            if not is_valid_evidence:
                telemetry["status"], telemetry["error"] = "REJECTED", unsupported_reason
                return None, telemetry
            bullets = list(output_json.get("bullets", []))[:3]
            semantic_state = output_json.get("semantic_state", "UNKNOWN")
            if semantic_state not in GEMINI_SEMANTIC_STATES:
                semantic_state = "UNKNOWN"

            scout_out = GeminiScoutOutput(
                schema_version="1.3.0-fast-scout",
                role="FAST_SCOUT",
                model_id=self.model_name,
                receipt_id=receipt.receipt_id,
                revision=receipt.revision,
                semantic_state=semantic_state,
                headline=str(output_json.get("headline", "")).strip(),
                bullets=bullets,
                missing_evidence=list(output_json.get("missing_evidence", [])),
                evidence_ids=output_json["evidence_ids"],
                deserves_luna_review=bool(output_json.get("deserves_luna_review", False)),
                unsupported_inference_flag=not is_valid_evidence,
                unsupported_inference_reason=unsupported_reason,
            )

            # Persist artifact
            persist_challenger_artifact(
                role="GEMINI_SCOUT",
                receipt_id=receipt.receipt_id,
                revision=receipt.revision,
                session_date=receipt.session_date,
                payload=scout_out.to_dict(),
            )

            telemetry.update(status="CURRENT", validation_status="ACCEPTED", validated_output=output_json)
            return scout_out, telemetry

        except Exception as exc:
            logger.error("GeminiScoutAdapter error: %s", exc)
            telemetry["error_class"] = type(exc).__name__
            telemetry["error"] = str(exc)
            telemetry["status"] = "EXCEPTION"
            self.last_telemetry = telemetry
            return None, telemetry


# =====================================================================
# 5. SOL OPTION SPECIALIST ADAPTER
# =====================================================================

class SolOptionSpecialistAdapter:
    """Invokes gpt-5.6-sol with option-economic evaluation."""

    def __init__(
        self,
        model_name: str = SOL_CHALLENGER_MODEL_ID,
        backend: Optional[ExperientialAdapter] = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model_name = model_name
        self.backend = backend or ExperientialAdapter(
            model_name=self.model_name,
            enforce_zero_cost=True,
            reject_substituted_model=True,
        )
        self.timeout_seconds = timeout_seconds
        self.last_telemetry: Dict[str, Any] = {}

    def is_available(self) -> bool:
        from src.oracle_sol.shadow_runtime import is_sol_option_specialist_enabled
        if not is_sol_option_specialist_enabled():
            return False
        return self.backend.is_available()

    def analyze(
        self,
        receipt: CanonicalShadowReceipt,
        packet: Optional[BrainPacket] = None,
    ) -> Tuple[Optional[SolOptionSpecialistOutput], Dict[str, Any]]:
        """Executes a bounded reasoning call on gpt-5.6-sol."""
        request_id = f"sol_opt_{receipt.receipt_id[:12]}_rev_{receipt.revision}"
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
        }

        from src.oracle_sol.shadow_runtime import is_sol_option_specialist_enabled
        if not is_sol_option_specialist_enabled() and type(self.backend).__name__ == "ExperientialAdapter":
            telemetry["status"] = "SOL_DISPATCH_PAUSED"
            telemetry["error"] = "Sol Option Specialist provider dispatch is paused (SOL_DISPATCH_ENABLED = False)"
            self.last_telemetry = telemetry
            return None, telemetry

        if packet is None:
            telemetry["status"] = "CANONICAL_PACKET_REQUIRED"
            return None, telemetry
        user_prompt_data = sanitize_brain_packet(packet)
        payload_str = json.dumps(user_prompt_data, indent=2)
        request_receipt = {}
        def before_send(body):
            request_receipt.update(persist_receipt(REQUEST_RECEIPT_DIR, body, packet))

        try:
            valid, reason = verify_sanitized_payload(payload_str)
            if not valid:
                telemetry["error_class"] = "PRIVACY_VIOLATION_BLOCKED"
                telemetry["error"] = reason
                self.last_telemetry = telemetry
                return None, telemetry
        except Exception as exc:
            telemetry["error_class"] = "SANITIZATION_FAILED"
            telemetry["error"] = str(exc)
            self.last_telemetry = telemetry
            return None, telemetry

        try:
            output_json, raw_tel = self.backend.invoke_reasoning(
                request_id=request_id,
                system_prompt=SOL_OPTION_SPECIALIST_INSTRUCTIONS,
                user_prompt=payload_str,
                schema=SOL_OPTION_SPECIALIST_SCHEMA,
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=1000,
                structured_mode="NATIVE_JSON_SCHEMA",
                single_attempt=True,
                before_send=before_send,
            )
            telemetry.update(raw_tel)
            telemetry["input_receipt"] = request_receipt
            self.last_telemetry = telemetry

            if output_json is None:
                telemetry["status"] = raw_tel.get("error_class") or "FAILED"
                return None, telemetry

            request_receipt["output_hash"] = digest(output_json)
            if not valid_binding(request_receipt, output_json, packet.session_id, packet.revision, self.model_name):
                telemetry["status"], telemetry["error"] = "REJECTED", "INPUT_RECEIPT_MISMATCH"
                return None, telemetry
            telemetry["audit_path"] = persist_challenger_artifact(
                "SOL_RAW", receipt.receipt_id, receipt.revision, receipt.session_date,
                {"output": output_json, "input_receipt": request_receipt, "validation_status": "NOT_YET_VALIDATED"})

            error = _validate_specialist(output_json, SOL_OPTION_SPECIALIST_SCHEMA, packet)
            if error:
                telemetry["status"], telemetry["error"] = "REJECTED", error
                return None, telemetry
            bullets = list(output_json.get("bullets", []))[:3]
            buying_state = output_json.get("buying_state", "UNRESOLVED")
            if buying_state not in SOL_BUYING_STATES:
                buying_state = "UNRESOLVED"

            sol_out = SolOptionSpecialistOutput(
                schema_version="1.3.0-option-specialist",
                role="OPTION_SPECIALIST",
                model_id=self.model_name,
                receipt_id=receipt.receipt_id,
                revision=receipt.revision,
                buying_state=buying_state,
                headline=str(output_json.get("headline", "")).strip(),
                bullets=bullets,
                missing_evidence=list(output_json.get("missing_evidence", [])),
                evidence_ids=output_json["evidence_ids"],
                direction_vs_trade_quality_conflict=bool(
                    output_json.get("direction_vs_trade_quality_conflict", False)
                ),
            )

            # Persist artifact
            persist_challenger_artifact(
                role="SOL_OPTION_SPECIALIST",
                receipt_id=receipt.receipt_id,
                revision=receipt.revision,
                session_date=receipt.session_date,
                payload=sol_out.to_dict(),
            )

            telemetry.update(status="CURRENT", validation_status="ACCEPTED", validated_output=output_json)
            return sol_out, telemetry

        except Exception as exc:
            logger.error("SolOptionSpecialistAdapter error: %s", exc)
            telemetry["error_class"] = type(exc).__name__
            telemetry["error"] = str(exc)
            telemetry["status"] = "EXCEPTION"
            self.last_telemetry = telemetry
            return None, telemetry
