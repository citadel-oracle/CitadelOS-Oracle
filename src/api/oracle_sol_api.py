"""FastAPI Router for CITADEL ORACLE SOL MARKET BRAIN (P0.2 Hardened).

Provides REST and SSE endpoints for the minimal Beacon HUD, state inspection,
exact input replay with hash verification, and visible persistence diagnostics.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import secrets
import subprocess
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from src.oracle_sol.service import SolMarketBrainService

router = APIRouter(prefix="/v1/oracle/sol", tags=["Oracle Sol"])
SPARK_CAPABILITY_ENV = "CITADEL_SPARK_INGEST_TOKEN"
SPARK_CAPABILITY_HEADER = "x-citadel-spark-token"


def validate_sol_sse_frame(frame: bytes) -> bytes:
    """Pass through the service-owned SSE frame exactly once."""
    if not isinstance(frame, bytes) or not frame.startswith(b"event: beacon_state\ndata: "):
        raise ValueError("Invalid Sol SSE queue frame")
    if not frame.endswith(b"\n\n"):
        raise ValueError("Incomplete Sol SSE queue frame")
    return frame


def get_secure_spark_capability_token() -> Optional[str]:
    """Retrieve Spark ingest capability token securely from env or macOS Keychain."""
    env_token = os.getenv(SPARK_CAPABILITY_ENV, "").strip()
    if env_token:
        return env_token

    user_name = os.getenv("USER") or "ayushmudgal"
    for cmd in (
        ["security", "find-generic-password", "-a", user_name, "-s", SPARK_CAPABILITY_ENV, "-w"],
        ["security", "find-generic-password", "-s", SPARK_CAPABILITY_ENV, "-w"],
    ):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    return None


def _require_spark_capability(request: Request) -> None:
    """Authorize local external-context mutation without exposing the token."""
    expected = get_secure_spark_capability_token()
    if not expected:
        raise HTTPException(status_code=503, detail="External-context mutation capability is not configured.")

    supplied = request.headers.get(SPARK_CAPABILITY_HEADER, "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="External-context mutation authorization failed.")


def _reject_production_test_fixture(payload: Dict[str, Any]) -> None:
    """Keep caller-controlled mock verification out of production HTTP ingress."""
    source_type = str(payload.get("source_type", "")).strip().upper()
    if bool(payload.get("is_test_fixture")) or source_type == "TEST_FIXTURE":
        raise HTTPException(status_code=422, detail="Test fixtures are not accepted by production external-context ingress.")


@router.get("/state")
async def get_sol_state() -> Dict[str, Any]:
    """Retrieve full Sol Market Brain state including active thesis and events."""
    service = SolMarketBrainService.get_instance()
    return service.get_latest_state()


@router.get("/beacon")
async def get_sol_beacon() -> Dict[str, Any]:
    """Retrieve minimal Beacon state for HUD presentation."""
    service = SolMarketBrainService.get_instance()
    return service.get_latest_beacon_state()


@router.post("/analyze-now")
async def trigger_analyze_now(request: Request) -> Dict[str, Any]:
    """Manually prioritize an immediate reasoning pass consuming from the quota ledger."""
    if os.getenv("CITADEL_ENABLE_MANUAL_GEMINI_ANALYSIS", "0").strip() != "1":
        raise HTTPException(status_code=404, detail="Manual Gemini analysis is disabled.")
    use_reserved_quota = False
    try:
        body = await request.json()
        if isinstance(body, dict):
            use_reserved_quota = bool(body.get("use_reserved_quota", False) or body.get("USE_RESERVED_QUOTA", False))
    except Exception:
        pass

    service = SolMarketBrainService.get_instance()
    try:
        thesis, beacon, telemetry, envelope = service.analyze_now(use_reserved_quota=use_reserved_quota)
        return {
            "status": telemetry.get("status", "SUCCESS"),
            "model_label": telemetry.get("model_label", service.model_adapter.configured_model),
            "beacon": beacon.to_dict(),
            "telemetry": telemetry,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Manual analysis failed: {str(exc)}")


@router.get("/stream")
async def get_sol_beacon_stream(request: Request):
    """Server-Sent Events (SSE) stream for real-time Beacon HUD updates."""
    service = SolMarketBrainService.get_instance()
    q = service.subscribe_sse()

    async def event_generator():
        try:
            # Emit immediate initial state frame
            init_beacon = service.get_latest_beacon_state()
            init_bytes = json.dumps(init_beacon, default=str).encode("utf-8")
            yield b"event: beacon_state\ndata: " + init_bytes + b"\n\n"

            while not await request.is_disconnected():
                try:
                    frame = q.get_nowait()
                    yield validate_sol_sse_frame(frame)
                except queue.Empty:
                    await asyncio.sleep(0.5)
                    yield b"event: sol_heartbeat\ndata: {}\n\n"
        finally:
            service.unsubscribe_sse(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Citadel-Transport": "SOL_BEACON_SSE",
        },
    )


@router.get("/replay/{cycle_id}")
def replay_sol_cycle(cycle_id: str) -> Dict[str, Any]:
    """Reconstruct exact input payload and verify bit-exact hash replay."""
    service = SolMarketBrainService.get_instance()
    verification = service.replay_engine.verify_exact_input_replay(cycle_id)
    if not verification.get("found"):
        raise HTTPException(status_code=404, detail=f"Cycle ID '{cycle_id}' not found in ledger.")
    exact_envelope = service.replay_engine.reconstruct_exact_input_envelope(cycle_id)
    return {
        "cycle_id": cycle_id,
        "verification": verification,
        "exact_request_envelope": exact_envelope,
    }


@router.get("/health")
def get_sol_health() -> Dict[str, Any]:
    """Return diagnostic health, worker status, and visible persistence health."""
    service = SolMarketBrainService.get_instance()
    beacon = service.get_latest_beacon()
    return {
        "service": "SolMarketBrainService",
        "vob_free_verified": "ZERO_VOB_ALLOWLIST_CONFIRMED",
        "system_status": beacon.system_status,
        "reasoning_status": beacon.reasoning_status,
        "market_verdict": beacon.market_verdict,
        "worker": service.worker.health(),
        "persistence": service.shadow_ledger.health(),
        "configured_model": service.model_adapter.configured_model,
        "actually_invoked_model": beacon.actually_invoked_model,
        "model_configured": service.model_adapter.is_configured,
        "provider_telemetry": service.get_provider_health(),
    }


@router.post("/external-context/ingest")
async def ingest_external_context(request: Request) -> Dict[str, Any]:
    """Localhost ingest endpoint for Spark structured external market context."""
    _require_spark_capability(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(exc)}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="External-context payload must be a JSON object.")
    _reject_production_test_fixture(payload)

    service = SolMarketBrainService.get_instance()
    ok, errors, context_obj = service.ingest_external_context(payload)
    if not ok or not context_obj:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "REJECTED",
                "validation_errors": errors,
            },
        )

    return {
        "status": "ACCEPTED",
        "external_context_id": context_obj.external_context_id,
        "market_session_date": context_obj.market_session_date,
        "received_at_utc": context_obj.received_at_utc,
        "total_items": context_obj.total_items_count(),
        "provenance_hash": context_obj.provenance_hash,
    }


@router.get("/external-context")
def get_external_context() -> Dict[str, Any]:
    """Retrieve current external context health and summary for active session."""
    service = SolMarketBrainService.get_instance()
    return service.external_context_store.get_health_summary(service.memory._session_date)


@router.post("/external-context/reload")
def reload_external_context(request: Request) -> Dict[str, Any]:
    """Reload external context store from disk history."""
    _require_spark_capability(request)
    service = SolMarketBrainService.get_instance()
    service.external_context_store.reload()
    return {
        "status": "RELOADED",
        "summary": service.external_context_store.get_health_summary(service.memory._session_date),
    }


# ── DETERMINISTIC EXTERNAL CONTEXT CORE & LOCAL BRAIN ENDPOINTS ──

@router.get("/local-brain/state")
def get_local_brain_state() -> Dict[str, Any]:
    """Retrieve state and telemetry of local Qwen 3.5 9B cognitive engine."""
    from src.oracle_sol.local_brain_service import LocalBrainService
    state = LocalBrainService.get_instance().get_shadow_state()
    service = SolMarketBrainService.get_instance()
    state["production_bridge"] = (
        service.cognitive_bridge.get_telemetry()
        if service.cognitive_bridge is not None
        else {"bridge_state": "DISABLED"}
    )
    return state


@router.post("/local-brain/run")
def trigger_local_brain_cycle() -> Dict[str, Any]:
    """Reject request-driven cognition; production is canonical-event driven."""
    raise HTTPException(
        status_code=409,
        detail="Production cognition is event-driven; manual provider execution is disabled.",
    )


@router.get("/external-context/core-state")
def get_external_context_core_state() -> Dict[str, Any]:
    """Retrieve health and provider status from deterministic ExternalContextCore."""
    from src.external_context.core import ExternalContextCore
    return ExternalContextCore.get_instance().get_health()


@router.post("/external-context/poll-now")
def trigger_external_context_poll() -> Dict[str, Any]:
    """Force an immediate out-of-band poll of external providers (RBI, SEBI, GDELT, etc.)."""
    from src.external_context.core import ExternalContextCore
    return ExternalContextCore.get_instance().poll_all_now()


@router.get("/external-context/events")
def get_external_context_events(limit: int = 20) -> Any:
    """Retrieve verified external events from Tier A (RBI/SEBI/MoSPI), Tier B (News), Tier C (GDELT)."""
    from src.external_context.core import ExternalContextCore
    return [e.to_dict() for e in ExternalContextCore.get_instance().get_latest_events(limit=limit)]


@router.get("/external-context/quotes")
def get_external_context_quotes() -> Any:
    """Retrieve world market quotes basket with exact/proxy and session status."""
    from src.external_context.core import ExternalContextCore
    return [q.to_dict() for q in ExternalContextCore.get_instance().get_latest_quotes()]


@router.get("/cognitive-decision")
async def get_cognitive_decision() -> Dict[str, Any]:
    """Read-only, revision-coherent cockpit view of accepted model output."""
    from src.oracle_sol.thesis_graph import ThesisGraph
    from src.oracle_sol.cognitive_projection import project_cognitive_decision

    service = SolMarketBrainService.get_instance()
    graph = (
        service.cognitive_bridge.thesis_graph
        if service.cognitive_bridge is not None
        else ThesisGraph(storage_path="data/oracle_sol/thesis_graph.jsonl")
    )
    active = graph.get_active_thesis()
    previous = next((node for node in graph.get_history(limit=10)
                     if active and node.thesis_id == active.supersedes_thesis_id), None)
    live_status = {}
    try:
        with open("data/oracle_sol/live_cognitive_status.json", "r", encoding="utf-8") as stream:
            live_status = json.load(stream)
    except (OSError, ValueError):
        pass
    with service._lock:
        snap_ref = service._latest_snapshot
    snapshot = snap_ref.to_dict() if snap_ref else {}
    bridge_status = service.cognitive_bridge.get_telemetry() if service.cognitive_bridge else {"bridge_state": "DISABLED"}
    live_status["inference_in_flight"] = bridge_status.get("cycle_in_flight", False)
    cognitive = project_cognitive_decision(active, previous, live_status, snapshot)
    return {
        "cognitive_live": cognitive,
        "revision": cognitive["revision"],
        "timestamp_iso": cognitive["market_timestamp"],
        "primary_decision": cognitive["primary_decision"],
        "gemini_scout": cognitive.get("gemini_scout"),
        "sol_option_specialist": cognitive.get("sol_option_specialist"),
        "five_hypotheses": cognitive["five_hypotheses"],
        "bridge": bridge_status,
    }


@router.get("/shadow/state")
def get_shadow_state() -> Dict[str, Any]:
    """Retrieve runtime state and metrics for Live Multi-Model Shadow Orchestrator V1.3."""
    from src.oracle_sol import shadow_runtime
    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator, SOL_DISPATCH_ENABLED
    orchestrator = LiveShadowOrchestrator.get_instance()
    views = orchestrator.get_projected_views()
    sol_active = bool(orchestrator._sol_enabled and SOL_DISPATCH_ENABLED)
    gemini_dispatch_enabled = getattr(shadow_runtime, "GEMINI_DISPATCH_ENABLED", False)
    gemini_active = bool(getattr(orchestrator, "_gemini_enabled", False) and gemini_dispatch_enabled)
    return {
        "service": "LiveShadowOrchestrator",
        "version": "1.3.0",
        "sol_dispatch_enabled": sol_active,
        "gemini_dispatch_enabled": gemini_active,
        "latest_revision": orchestrator._latest_revision,
        "gemini_in_flight": False if not gemini_active else orchestrator._gemini_in_flight,
        "gemini_paused": not gemini_active,
        "gemini_pause_state": "PAUSED · INPUT/ARCHITECTURE HARDENING" if not gemini_active else "ACTIVE",
        "sol_in_flight": False if not sol_active else orchestrator._sol_in_flight,
        "sol_paused": not sol_active,
        "sol_pause_state": "PAUSED · COST STOP" if not sol_active else "ACTIVE",
        "sol_readiness_checklist": orchestrator._sol_readiness_checklist,
        "metrics": orchestrator.metrics,
        "gemini_scout": views.get("gemini_scout"),
        "sol_option_specialist": views.get("sol_option_specialist"),
    }


@router.post("/shadow/pause")
def pause_sol_dispatch(reason: str = "INPUT_HARDENING") -> Dict[str, Any]:
    """Pause Sol Option Specialist provider dispatch and cancel any pending queue."""
    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
    orchestrator = LiveShadowOrchestrator.get_instance()
    orchestrator.pause_sol(reason=reason)
    return {
        "status": "PAUSED",
        "model": "gpt-5.6-sol",
        "reason": reason,
        "sol_paused": True,
        "sol_pause_state": f"PAUSED · {reason.replace('_', ' ')}",
    }


@router.post("/shadow/resume")
def resume_sol_dispatch() -> Dict[str, Any]:
    """Resume Sol Option Specialist provider dispatch."""
    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
    orchestrator = LiveShadowOrchestrator.get_instance()
    orchestrator.resume_sol()
    return {
        "status": "ACTIVE",
        "model": "gpt-5.6-sol",
        "sol_paused": False,
        "sol_pause_state": "ACTIVE",
    }


@router.post("/shadow/gemini/pause")
def pause_gemini_dispatch(reason: str = "INPUT_ARCHITECTURE_HARDENING") -> Dict[str, Any]:
    """Pause Gemini Fast Scout provider dispatch and cancel any pending queue."""
    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
    orchestrator = LiveShadowOrchestrator.get_instance()
    orchestrator.pause_gemini(reason=reason)
    return {
        "status": "PAUSED",
        "model": "gemini-3.7-flash",
        "reason": reason,
        "gemini_paused": True,
        "gemini_pause_state": "PAUSED · INPUT/ARCHITECTURE HARDENING",
    }


@router.post("/shadow/gemini/resume")
def resume_gemini_dispatch() -> Dict[str, Any]:
    """Resume Gemini Fast Scout provider dispatch."""
    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
    orchestrator = LiveShadowOrchestrator.get_instance()
    orchestrator.resume_gemini()
    return {
        "status": "ACTIVE",
        "model": "gemini-3.7-flash",
        "gemini_paused": False,
        "gemini_pause_state": "ACTIVE",
    }
