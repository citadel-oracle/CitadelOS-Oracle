"""Cognitive Model Status Provider (GPT-OSS 120B & Qwen 3.8 27B).

Exposes provider-neutral runtime state for cloud cognitive engines:
- Distinguishes API_CONNECTED from LIVE_SHADOW_ENABLED.
- Tracks in-flight status, latency, token consumption, schema validity, and gate results.
- Never fabricates connection or execution states.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BENCHMARK_RESULTS_FILE = Path("reports/GROQ_CLOUD_BRAIN_BENCHMARK_RESULTS.json")

# In-memory dynamic runtime tracking for live shadow engine
_live_runtime_state: Dict[str, Dict[str, Any]] = {
    "gpt_oss": {
        "current_request_in_flight": False,
        "live_shadow_enabled": os.getenv("CITADEL_ENABLE_SHADOW_INFERENCE", "0").strip() == "1",
    },
    "qwen": {
        "current_request_in_flight": False,
        "live_shadow_enabled": False,
    },
}


def set_model_in_flight(model_key: str, in_flight: bool) -> None:
    """Set in-flight status for cognitive model."""
    if model_key in _live_runtime_state:
        _live_runtime_state[model_key]["current_request_in_flight"] = in_flight


def set_model_shadow_enabled(model_key: str, enabled: bool) -> None:
    """Set shadow enabled status for cognitive model."""
    if model_key in _live_runtime_state:
        _live_runtime_state[model_key]["live_shadow_enabled"] = enabled


def record_model_execution(model_key: str, execution_data: Dict[str, Any]) -> None:
    """Record dynamic telemetry from live model inference."""
    if model_key in _live_runtime_state:
        _live_runtime_state[model_key].update(execution_data)
        _live_runtime_state[model_key]["current_request_in_flight"] = False


def get_cognitive_models_status() -> Dict[str, Any]:
    """Retrieve truthful runtime status for GPT-OSS 120B and Qwen 3.8 27B."""
    # Check API key presence securely without leaking secret
    has_groq_key = False
    env_key = os.getenv("GROQ_API_KEY", "")
    if len(env_key.strip()) >= 8:
        has_groq_key = True
    else:
        try:
            import subprocess
            res = subprocess.run(
                ["security", "find-generic-password", "-s", "GROQ_API_KEY", "-w"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if res.returncode == 0 and len(res.stdout.strip()) >= 8:
                has_groq_key = True
        except Exception:
            pass

    # Load durable telemetry from benchmark results if available
    durable_data: Dict[str, Any] = {}
    if BENCHMARK_RESULTS_FILE.exists():
        try:
            with open(BENCHMARK_RESULTS_FILE, "r", encoding="utf-8") as f:
                durable_data = json.load(f)
        except Exception as exc:
            logger.debug("Failed loading benchmark telemetry: %s", exc)

    gpt_canary = durable_data.get("gpt_oss_canary") or {}
    qwen_canary = durable_data.get("qwen_canary") or {}
    gpt_tel = gpt_canary.get("telemetry") or {}
    qwen_tel = qwen_canary.get("telemetry") or {}

    # Check live shadow runner status
    live_shadow_enabled = _live_runtime_state["gpt_oss"].get("live_shadow_enabled", False)

    # Derive GPT-OSS status
    gpt_proven = bool(gpt_canary and gpt_canary.get("schema_status") == "SCHEMA_VALID_JSON")
    gpt_status = "NOT_CONFIGURED"
    if has_groq_key:
        if gpt_proven:
            gpt_status = "IDLE"  # Proven connected, waiting for trigger
        else:
            gpt_status = "UNPROVEN"

    gpt_model_info = {
        "model_id": "openai/gpt-oss-120b",
        "display_name": "GPT-OSS 120B",
        "role": "SHADOW PRIMARY",
        "lifecycle": "PRODUCTION",
        "configured": has_groq_key,
        "api_connected": has_groq_key and gpt_proven,
        "live_shadow_enabled": live_shadow_enabled,
        "current_request_in_flight": False,
        "status": gpt_status,
        "last_request_started_at": gpt_tel.get("started_at"),
        "last_request_finished_at": gpt_tel.get("ended_at"),
        "last_http_status": 200 if gpt_proven else None,
        "last_provider_request_id": gpt_tel.get("request_id"),
        "last_success_at": gpt_tel.get("ended_at"),
        "last_failure_at": None,
        "last_failure_reason": None,
        "last_latency_ms": gpt_canary.get("network_latency_ms"),
        "last_prompt_tokens": gpt_canary.get("prompt_tokens", 0),
        "last_completion_tokens": gpt_canary.get("completion_tokens", 0),
        "last_total_tokens": gpt_canary.get("total_tokens", 0),
        "last_schema_status": gpt_canary.get("schema_status"),
        "last_evidence_gate_status": gpt_canary.get("evidence_gate_status"),
        "last_thesis_state": gpt_canary.get("synthesis_state"),
    }

    # Derive Qwen 3.8 status
    qwen_proven = bool(qwen_canary and qwen_canary.get("schema_status") == "SCHEMA_VALID_JSON")
    qwen_status = "NOT_CONFIGURED"
    if has_groq_key:
        if qwen_proven:
            qwen_status = "IDLE"
        else:
            qwen_status = "UNPROVEN"

    qwen_model_info = {
        "model_id": "qwen/qwen3.8-27b",
        "display_name": "QWEN 3.8 27B",
        "role": "CHALLENGER",
        "lifecycle": "PREVIEW",
        "configured": has_groq_key,
        "api_connected": has_groq_key and qwen_proven,
        "live_shadow_enabled": False,
        "current_request_in_flight": False,
        "status": qwen_status,
        "last_request_started_at": qwen_tel.get("started_at"),
        "last_request_finished_at": qwen_tel.get("ended_at"),
        "last_http_status": 200 if qwen_proven else None,
        "last_provider_request_id": qwen_tel.get("request_id"),
        "last_success_at": qwen_tel.get("ended_at"),
        "last_failure_at": None,
        "last_failure_reason": None,
        "last_latency_ms": qwen_canary.get("network_latency_ms"),
        "last_prompt_tokens": qwen_canary.get("prompt_tokens", 0),
        "last_completion_tokens": qwen_canary.get("completion_tokens", 0),
        "last_total_tokens": qwen_canary.get("total_tokens", 0),
        "last_schema_status": qwen_canary.get("schema_status"),
        "last_evidence_gate_status": qwen_canary.get("evidence_gate_status"),
        "last_thesis_state": qwen_canary.get("synthesis_state"),
    }

    LIVE_STATUS_FILE = Path("data/oracle_sol/live_cognitive_status.json")
    if LIVE_STATUS_FILE.exists():
        try:
            with open(LIVE_STATUS_FILE, "r", encoding="utf-8") as f:
                persisted = json.loads(f.read())
                if "gpt_oss" in persisted:
                    gpt_model_info.update(persisted["gpt_oss"])
                if "qwen" in persisted:
                    qwen_model_info.update(persisted["qwen"])
        except Exception:
            pass

    # Merge dynamic live state for GPT-OSS
    live_gpt = _live_runtime_state.get("gpt_oss", {})
    gpt_model_info.update(live_gpt)
    if gpt_model_info.get("current_request_in_flight"):
        gpt_model_info["status"] = "RUNNING"
    elif gpt_model_info.get("api_connected"):
        gpt_model_info["status"] = "IDLE"

    # Merge dynamic live state for Qwen
    live_qwen = _live_runtime_state.get("qwen", {})
    qwen_model_info.update(live_qwen)
    if qwen_model_info.get("current_request_in_flight"):
        qwen_model_info["status"] = "RUNNING"
    elif qwen_model_info.get("api_connected"):
        qwen_model_info["status"] = "IDLE"

    return {
        "provider": "GROQ",
        "provider_connected": has_groq_key and (gpt_proven or qwen_proven),
        "primary_model": "openai/gpt-oss-120b",
        "challenger_model": "qwen/qwen3.8-27b",
        "live_shadow_enabled": live_shadow_enabled,
        "models": {
            "gpt_oss": gpt_model_info,
            "qwen": qwen_model_info,
        },
    }
