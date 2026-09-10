"""Read-only cockpit projection. Attempts are not accepted theses or fresh responses."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.oracle_sol.evidence_gate import EvidenceGate


def _time(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def project_cognitive_decision(active, previous, live_status: Dict[str, Any],
                               snapshot: Dict[str, Any], now: Optional[datetime] = None):
    """Select one committed revision; never merge another attempt's prose/state into it.

    Uses existing scheduler freshness windows (30/90 seconds), not trading gates.
    No provider, scheduler, quota mutation, or persistent writes are performed here.
    """
    now = now or datetime.now(timezone.utc)
    node = active.to_dict() if active else {}
    from src.oracle_sol.luna_input_receipt import valid_binding
    retained = node.get("semantic_validation") or {}
    receipt = retained.get("input_receipt")
    bound = valid_binding(receipt, retained.get("response"), node.get("session_id"), node.get("input_revision"), node.get("model"))
    validation = EvidenceGate.revalidate_retained(node) if node else None
    rejected = bool(validation and not validation.is_valid)
    historical = node if rejected else None
    if rejected:
        # Preserve the durable node in history only. No rejected prose or direction
        # may populate primary reasons, last-valid model cards, or comparisons.
        node = {key: node.get(key) for key in ("thesis_id", "session_id", "input_revision", "created_at", "input_hash", "model")}
    session = snapshot.get("market_session_date") or live_status.get("session_id")
    session_matches = bool(node and session and node.get("session_id") == session)
    closed = (
        snapshot.get("system_status") in ("OFF_MARKET", "MARKET_CLOSED", "SESSION_LAST")
        or live_status.get("status") in ("SESSION_LAST", "MARKET_CLOSED")
        or live_status.get("market_status") in ("SESSION_LAST", "MARKET_CLOSED")
    )
    models = live_status.get("models") or {}
    outputs = {"qwen": node.get("qwen_observation") or {}, "gpt": {} if rejected else node,
               "gemini": node.get("gemini_review") or {}}
    result = {}
    for role, key, date_key in (("qwen", "qwen", "observed_at"),
                                ("gpt", "gpt_oss", "created_at"),
                                ("gemini", "gemini", "reviewed_at")):
        output = outputs[role]
        attempt = models.get(key) or {}
        timestamp = output.get(date_key)
        finished = _time(timestamp)
        age = (now - finished).total_seconds() if finished else None
        revision = output.get("input_revision")
        status = "UNAVAILABLE" if not output else "LAST_KNOWN"
        reason = "NO_ACCEPTED_OUTPUT" if not output else None
        if output:
            if not session_matches:
                status, reason = "STALE", "PRIOR_SESSION"
            elif revision != node.get("input_revision"):
                status, reason = "STALE", "REVISION_MISMATCH"
            elif age is None or age < 0:
                status, reason = "STALE", "TIMESTAMP_UNAVAILABLE_OR_FUTURE"
            elif closed:
                status, reason = "SESSION_LAST", "MARKET_CLOSED"
            else:
                status = "CURRENT" if age < 60 else "STALE" if age < 180 else "OUTDATED"
        attempt_session = live_status.get("session_id")
        attempted_revision = attempt.get("input_revision")
        same_session_attempt = not attempt_session or not node or attempt_session == node.get("session_id")
        newer_attempt = (same_session_attempt and isinstance(attempted_revision, int) and
                           (not isinstance(revision, int) or attempted_revision >= revision))
        if newer_attempt and attempt.get("status") in (
            "UNAVAILABLE", "RATE_LIMITED", "QUOTA_BLOCKED", "OUTPUT_INVALID", "TIMEOUT"):
            status, reason = attempt["status"], attempt.get("error_category") or attempt["status"]
        elif role == "gpt" and newer_attempt and attempted_revision != revision:
            status, reason = "OUTPUT_UNVALIDATED", "LATEST_ATTEMPT_NOT_COMMITTED"
        if rejected and (role == "gpt" or (historical or {}).get("qwen_observation" if role == "qwen" else "gemini_review")):
            status, reason = "REJECTED", "LEGACY_ANALYSIS_REJECTED_BY_CURRENT_SEMANTIC_FIREWALL"
        elif role == "gpt" and status == "CURRENT" and live_status.get("inference_in_flight"):
            status, reason = "UPDATING", "LAST_ACCEPTED_READ"
        # The response identity belongs to this output, never to a newer attempt.
        telemetry = output.get("telemetry") or {}
        result[role] = {
            "model_id": output.get("model_name") or output.get("model") or attempt.get("model_id"),
            "status": status, "reason": reason, "last_success": timestamp,
            "age_seconds": age if age is not None and age >= 0 else None,
            "analyzed_revision": revision, "output": output or None,
            "response_id": telemetry.get("provider_request_id") or telemetry.get("request_id") or
                           (node.get("thesis_id") if role == "gpt" else None),
            "telemetry": {k: attempt.get(k) for k in (
                "status", "http_status", "error_category", "input_revision", "completed_at",
                "latency_ms", "prompt_tokens", "completion_tokens", "total_tokens")},
        }
    import re
    _BRACKETED_TOKEN_RE = re.compile(
        r'\[\s*(?:(?:metric|rel|coverage|sensor|provenance|fact|evidence):|evt_|token:)[^\]]*\]',
        re.IGNORECASE,
    )

    def _clean_human_prose(text: Any) -> Any:
        if not isinstance(text, str):
            return text
        cleaned = _BRACKETED_TOKEN_RE.sub('', text)
        cleaned = re.sub(r'\s+([.,;:!?])', r'\1', cleaned)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        return cleaned

    # Presentation projects accepted interpretation; it never supplies a strategy.
    what_changed = node.get("what_changed")
    if isinstance(what_changed, str) and what_changed.startswith("Revision ") and "analyzed." in what_changed:
        what_changed = None
    elif what_changed:
        what_changed = _clean_human_prose(what_changed)
    clean_invalids = node.get("invalidation_conditions") or []
    conclusions = (node.get("semantic_validation") or {}).get("response", {}).get("conclusions")
    if isinstance(conclusions, list):
        clean_invalids = [c["claim"] for c in conclusions if c.get("purpose") == "contradiction"]
    clean_invalids = [_clean_human_prose(x) for x in clean_invalids if x]
    missing_confirmation = [c["claim"] for c in (conclusions or []) if c.get("purpose") == "missing_confirmation"]
    missing_confirmation = [_clean_human_prose(x) for x in missing_confirmation if x]
    clean_watch = [_clean_human_prose(x) for x in (node.get("watch_next") or []) if x]
    raw_opt = node.get("option_buyer_side")
    opt_side = raw_opt if (raw_opt and str(raw_opt).strip() != "") else None
    raw_prem = node.get("premium_confirmation")
    prem_conf = raw_prem if (raw_prem and str(raw_prem).strip() != "") else None
    raw_rw = node.get("reversal_watch_data")
    reversal_watch = raw_rw if (isinstance(raw_rw, dict) and bool(raw_rw)) else None
    evolution = node.get("thesis_evolution")
    maturity = node.get("opportunity_maturity")

    raw_why_now = node.get("why_now") or ([node["market_story"]] if node.get("market_story") else [])
    clean_why_now = [_clean_human_prose(x) for x in raw_why_now if x]

    # Primary display uses only the accepted node. An uncommitted attempt remains diagnostic.
    decision = {
        "state": node.get("state"), "entry_window": node.get("entry_window"),
        "why_now": clean_why_now,
        "what_changed": what_changed, "setup_family": node.get("setup_family"),
        "reversal_watch": reversal_watch,
        "option_buyer_side": opt_side,
        "premium_confirmation": prem_conf,
        "watch_next": clean_watch,
        "view_breaks_if": clean_invalids,
        "missing_confirmation": missing_confirmation,
        "thesis_evolution": evolution,
        "opportunity_maturity": maturity,
        # No guessed tension level or default consensus from missing peer observations.
        "model_tension": None, "agreement_status": "UNAVAILABLE",
        "previous_state": previous.state if previous and not rejected and previous.session_id == node.get("session_id")
            and EvidenceGate.revalidate_retained(previous.to_dict()).is_valid else None,
    }
    matching_status = (live_status.get("input_revision") == node.get("input_revision") and
                       live_status.get("input_hash") == node.get("input_hash"))
    if matching_status and not rejected:
        stored_decision = live_status.get("decision") or {}
        stored_tension = stored_decision.get("model_tension")
        if stored_tension and "ALIGNED: Solitary" in stored_tension:
            stored_tension = "NO CHALLENGER READ: Solitary production cognitive analyst"
        decision["model_tension"] = stored_tension
        decision["agreement_status"] = stored_decision.get("agreement_status", "UNAVAILABLE")

    # Project Shadow Specialist Views (V1.3 Live Multi-Model Shadow)
    shadow_views: Dict[str, Any] = {}
    try:
        import json
        with open("data/sol_shadow/live_shadow_status.json", "r", encoding="utf-8") as sf:
            sdata = json.load(sf)
            for role_key in ("gemini_scout", "sol_option_specialist"):
                raw_s = sdata.get(role_key)
                from src.oracle_sol.shadow_specialists import validated_specialist_view
                if validated_specialist_view(raw_s):
                    s_dt = _time(raw_s.get("updated_at"))
                    s_age = (now - s_dt).total_seconds() if s_dt else None
                    luna_rev = node.get("input_revision")
                    luna_receipt_id = (receipt.get("parent_receipt_id") or receipt.get("receipt_id")) if (bound and not rejected and isinstance(receipt, dict)) else None
                    matches_disk_frontier = (
                        raw_s.get("receipt_id") == sdata.get("latest_receipt_id")
                        and raw_s.get("session_date") == sdata.get("session_date") == session
                        and (sdata.get("latest_revision") is None or raw_s.get("revision") == sdata.get("latest_revision"))
                    )
                    matches_luna_revision = (luna_rev is None or raw_s.get("revision") == luna_rev)
                    matches_luna_receipt = (luna_receipt_id is None or raw_s.get("receipt_id") == luna_receipt_id)
                    not_unsupported = not raw_s.get("unsupported_inference_flag")
                    same_frontier = matches_disk_frontier and matches_luna_revision and matches_luna_receipt and not_unsupported
                    s_status = "CURRENT" if same_frontier and s_age is not None and 0 <= s_age < 60 else "STALE" if s_age is not None and s_age < 180 else "OUTDATED"
                    from src.oracle_sol.shadow_runtime import (
                        is_sol_option_specialist_enabled,
                        is_gemini_fast_scout_enabled,
                    )
                    is_paused = (
                        bool(not is_sol_option_specialist_enabled() or sdata.get("sol_paused") or raw_s.get("paused"))
                        if role_key == "sol_option_specialist"
                        else bool(not is_gemini_fast_scout_enabled() or sdata.get("gemini_paused") or raw_s.get("paused"))
                        if role_key == "gemini_scout"
                        else False
                    )
                    if is_paused and s_status == "CURRENT":
                        s_status = "STALE"
                    pause_reason = (
                        "INPUT_ARCHITECTURE_HARDENING"
                        if role_key == "gemini_scout"
                        else "INPUT_HARDENING"
                    )
                    display_status = (
                        "PAUSED · INPUT/ARCHITECTURE HARDENING"
                        if role_key == "gemini_scout"
                        else "PAUSED · INPUT HARDENING"
                    )
                    shadow_views[role_key] = {
                        **raw_s,
                        "age_seconds": s_age,
                        "status": s_status,
                        **({
                            "in_flight": False,
                            "paused": True,
                            "pause_reason": pause_reason,
                            "display_status": display_status,
                        } if is_paused else {}),
                    }
    except Exception:
        pass

    if not shadow_views:
        try:
            from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
            if LiveShadowOrchestrator._instance is not None:
                shadow_views = LiveShadowOrchestrator._instance.get_projected_views(now)
        except Exception:
            pass

    return {
        "response_observed_at": now.isoformat(),
        "revision": node.get("input_revision"), "market_timestamp": node.get("created_at"),
        "market_status": snapshot.get("system_status") or live_status.get("market_status") or ("SESSION_LAST" if closed else "UNAVAILABLE"), "session_id": node.get("session_id") or session,
        "primary_decision": decision, **result,
        "gemini_scout": shadow_views.get("gemini_scout"),
        "sol_option_specialist": shadow_views.get("sol_option_specialist"),
        "accepted_input_receipt": receipt if bound and not rejected else None,
        "input_receipt_status": "BOUND" if bound and not rejected else "LEGACY_INPUT_NOT_RECORDED",
        "retained_validation": {"status": validation.status if validation else "UNAVAILABLE",
            "reason": validation.error_details if validation else "NO_ACCEPTED_OUTPUT"},
        "historical_rejected_thesis": historical,
        "five_hypotheses": node.get("five_hypotheses") or {},
        "evidence_gate": {"last_commit_id": node.get("thesis_id"),
                          "last_commit_revision": node.get("input_revision")},
        "paper_only": True, "live_trading": False, "broker_submission": False,
        "execution_influence": 0, "ai_vob_influence": 0,
    }
