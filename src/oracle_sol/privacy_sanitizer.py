"""CITADEL Oracle — Deterministic Privacy Sanitizer.

Enforces zero-leak boundary for non-ZDR model routing (Experiential gpt-5.6-luna).
Retains strictly public market observables and opaque identifiers required for
provenance citation, while stripping all internal engine state, developer hashes,
credentials, user identifiers, positions, orders, proprietary weights, and filesystem paths.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.contracts import MarketEvent

logger = logging.getLogger(__name__)


class PrivacyViolationError(ValueError):
    """Raised when an outbound payload contains prohibited internal or identifying terms."""
    pass


# Allowed public market fields in supporting_values
ALLOWED_SUPPORTING_KEYS = {
    "before_spot",
    "after_spot",
    "spot_delta",
    "before_futures",
    "after_futures",
    "futures_delta",
    "before_basis",
    "after_basis",
    "basis_delta",
    "basis",
    "before_iv",
    "after_iv",
    "iv_delta",
    "skew_10d",
    "skew_25d",
    "before_straddle",
    "after_straddle",
    "straddle_delta",
    "session_vwap",
    "spot_to_vwap_pts",
    "5m_oi_delta",
    "closed_5m_oi",
    "structure",
    "diffs",
    "ce_ltp",
    "pe_ltp",
    "ce_iv",
    "pe_iv",
    "call_oi",
    "put_oi",
    "pcr",
    "pcr_oi",
    "oi",
    "ce_oi",
    "pe_oi",
    "change_oi",
    "intraday_change_oi",
    "oi_velocity",
    "oi_acceleration",
    "oi_concentration",
    "total_net_gex_inr_cr",
    "dealer_regime",
    "zero_gamma_level",
    "buildup",
    "oi_buildup",
    "before_5m_oi", "after_5m_oi", "before_structure", "after_structure",
    "option_type", "strike",
    "before_15m_oi", "after_15m_oi", "expected_move_pts",
}

# Nested quote endpoints are a separate contract, not an arbitrary dictionary.
_QUOTE_FIELDS = {
    "best_ask_price", "best_bid_price", "expiry", "iv", "ltp",
    "option_type", "security_id", "source_timestamp", "strike",
}

# Public observations only: no composite score, strategy state or VOB lineage.
CURRENT_CONTEXT_FIELDS = (
    "spot_price", "futures_price", "basis", "session_vwap", "atm_strike",
    "ce_atm_premium", "pe_atm_premium", "ce_atm_security_id", "pe_atm_security_id",
    "straddle_price", "straddle_change_15m", "atm_iv", "skew_25d", "skew_10d",
    "pcr_oi", "total_net_gex_inr_cr", "zero_gamma", "dealer_regime",
    "flow_net_delta", "cvd", "mlofi_5l",
)


def _public_value(value: Any, path: Tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        allowed = (
            {"ce_pricing", "pe_pricing"} if path == ("diffs",) else
            {"before", "after"} if len(path) == 2 and path[0] == "diffs" else
            _QUOTE_FIELDS if len(path) == 3 and path[0] == "diffs" else set()
        )
        if set(value) - allowed:
            raise PrivacyViolationError("Unreviewed nested evidence field; outbound packet blocked")
        return {key: _public_value(item, (*path, key)) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise PrivacyViolationError("Unreviewed evidence value type; outbound packet blocked")

# Explicitly stripped internal keys
STRIPPED_KEYS = {
    "summary",
    "provenance_hash",
    "before_state",
    "after_state",
    "chronology_mode",
    "canonical_snapshot_id",
    "ose_ssi_score",
    "ose_decision_window",
    "vob_state",
    "vob_touch_count",
    "vob_sweep",
    "order_flow_response_state",
}

# Prohibited privacy regex patterns (case-insensitive)
PROHIBITED_PATTERNS = [
    # Credentials & Secrets
    r"\bdhan\b",
    r"\bclient_id\b",
    r"\baccess_token\b",
    r"\bbroker_secret\b",
    r"\bapi_key\b",
    r"\bkeychain\b",
    # User / Account identification
    r"\bayush\b",
    r"\buser_id\b",
    r"\baccount_id\b",
    r"\baccount_number\b",
    # Positions, PnL, Margin, Orders
    r"\bposition\b",
    r"\bpnl\b",
    r"\bmargin\b",
    r"\border_placement\b",
    r"\btrade_id\b",
    r"\border_id\b",
    r"\bplace_order\b",
    r"\bbuy_order\b",
    r"\bsell_order\b",
    r"\bmodify_order\b",
    r"\bcancel_order\b",
    r"\bbroker_submission\b",
    r"\bexecute_trade\b",
    # Proprietary formulas / weights / strategies
    r"\bweight\b",
    r"\bformula\b",
    r"\bproprietary\b",
    r"\bstrategy_id\b",
    r"\bose_ssi_score\b",
    # Filesystem paths
    r"/Users/",
    r"/home/",
    r"\.py\b",
    r"\.jsonl\b",
    # VOB internals
    r"\bvob_state\b",
    r"\bvob_touch_count\b",
    r"\bvob_sweep\b",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROHIBITED_PATTERNS]


def sanitize_event(event: Any) -> Dict[str, Any]:
    """Sanitize a single MarketEvent or event dictionary to strictly public fields."""
    if hasattr(event, "to_dict"):
        raw = event.to_dict()
    elif isinstance(event, dict):
        raw = event
    elif hasattr(event, "__dict__"):
        raw = event.__dict__
    else:
        raw = dict(event)

    sup = raw.get("supporting_values") or {}
    clean_sup: Dict[str, Any] = {}
    if isinstance(sup, dict):
        for k, v in sup.items():
            if k in STRIPPED_KEYS:
                continue
            if k not in ALLOWED_SUPPORTING_KEYS:
                raise PrivacyViolationError("Unreviewed evidence field; outbound packet blocked")
            clean_sup[k] = _public_value(v, (k,))

    return {
        "event_id": raw.get("event_id"),
        "event_type": raw.get("event_type"),
        "instrument": raw.get("instrument"),
        "strike": raw.get("strike"),
        "expiry": raw.get("expiry"),
        "security_id": raw.get("security_id"),
        "timestamp_ist": raw.get("timestamp_ist"),
        "timestamp_utc": raw.get("timestamp_utc"),
        "supporting_values": clean_sup,
    }


def verify_sanitized_payload(payload_str: str) -> Tuple[bool, Optional[str]]:
    """Verify that a sanitized JSON string contains zero prohibited or private terms."""
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(payload_str)
        if match:
            matched_term = match.group(0)
            return False, f"Prohibited term detected: '{matched_term}' (pattern: {pattern.pattern})"
    return True, None


def sanitize_brain_packet(
    packet: BrainPacket,
    unseen_events: Optional[Sequence[Any]] = None,
    decision_cutoff_ist: Optional[str] = None,
) -> Dict[str, Any]:
    """Compiles an audited, privacy-safe compact packet for Luna reasoning."""
    events_to_sanitize: List[Any] = []
    if unseen_events:
        events_to_sanitize = list(unseen_events)
    elif packet.unseen_events_summary:
        events_to_sanitize = list(packet.unseen_events_summary)

    # Group events into phases by timestamp_ist
    events_by_ts: Dict[str, List[Dict[str, Any]]] = {}
    last_utc = None
    for ev in events_to_sanitize:
        san = sanitize_event(ev)
        ts = san.get("timestamp_ist") or "unknown"
        events_by_ts.setdefault(ts, []).append(san)
        if san.get("timestamp_utc"):
            last_utc = max(last_utc or "", san["timestamp_utc"])

    timeline: List[Dict[str, Any]] = []
    for ts, evs in events_by_ts.items():
        utc_val = evs[0].get("timestamp_utc") if evs else None
        timeline.append({
            "timestamp_ist": ts,
            "timestamp_utc": utc_val,
            "events": evs,
        })

    # Sort timeline by timestamp_ist / utc
    timeline.sort(key=lambda item: item.get("timestamp_ist") or "")

    cutoff_ist = decision_cutoff_ist
    if not cutoff_ist and timeline:
        last_ts = timeline[-1].get("timestamp_ist")
        if last_ts and last_ts != "unknown":
            cutoff_ist = last_ts
    if not cutoff_ist or cutoff_ist == "unknown":
        if packet.compiled_at:
            try:
                from zoneinfo import ZoneInfo
                dt = datetime.fromisoformat(packet.compiled_at.replace("Z", "+00:00"))
                cutoff_ist = dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
            except Exception:
                pass
    if not cutoff_ist:
        raise PrivacyViolationError("Recorded evidence cutoff unavailable")

    sanitized_packet = {
        "schema_version": "luna-context-v2",
        "evidence_state": "FROZEN_AS_OF_CUTOFF",
        "evidence_frontier": list(packet.unseen_event_ids),
        "packet_id": f"luna_sanitized_{packet.session_id}_{packet.revision}",
        "session_date": packet.session_id,
        "decision_cutoff_ist": cutoff_ist,
        "frozen_at_utc": last_utc or packet.compiled_at,
        "revision": packet.revision,
        "known_missing_inputs": [
            "order_book_micro_depth",
            "5_level_mlofi",
        ],
        "timeline": timeline,
    }
    current = {}
    for key in CURRENT_CONTEXT_FIELDS:
        evidence_id = f"metric:{key}"
        source = packet.evidence_registry.get(evidence_id, {})
        value = packet.canonical_state.get(key) if source else None
        available = source.get("availability") in ("RECORDED", "AVAILABLE", "EXACT", "VERIFIED")
        source_age_seconds = None
        try:
            stamp = datetime.fromisoformat(str(source.get("timestamp")).replace("Z", "+00:00"))
            from zoneinfo import ZoneInfo
            local_stamp = stamp.astimezone(ZoneInfo("Asia/Kolkata"))
            available = available and stamp.tzinfo is not None and local_stamp.date().isoformat() == packet.session_id and local_stamp.strftime("%H:%M:%S") <= cutoff_ist
            if available:
                cutoff_time = datetime.fromisoformat(f"{packet.session_id}T{cutoff_ist}").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                source_age_seconds = (cutoff_time - stamp).total_seconds()
        except (ValueError, TypeError):
            available = False
        if not available:
            value = None
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise PrivacyViolationError("Unreviewed current-context type")
        current[key] = {
            "value": value, "evidence_id": evidence_id if available else None,
            "source_time": source.get("timestamp") if available else None,
            "availability": source.get("availability") if available else "UNAVAILABLE",
            "source_age_seconds_at_cutoff": source_age_seconds,
        }
    sanitized_packet["current_facts"] = current
    # User-approved compact context, explicitly an assertion rather than a fact.
    prior = packet.previous_thesis or {}
    previous = None
    if prior.get("session_id") == packet.session_id:
        previous = {"kind": "PREVIOUS_MODEL_ASSERTION_NOT_CANONICAL_FACT"}
        for key in ("state", "thesis_evolution", "opportunity_maturity", "counter_case", "unresolved_context"):
            value = prior.get(key)
            if value is not None and not isinstance(value, str):
                raise PrivacyViolationError("Invalid previous-context field")
            words = value.split() if value else []
            previous[key] = " ".join(words[:40]) + (" …" if len(words) > 40 else "") if words else None
    sanitized_packet["previous_model_view"] = previous
    sanitized_packet["previous_model_view_availability"] = "RECORDED_ASSERTION" if previous else "NO_SAME_SESSION_ACCEPTED_VIEW"
    specialist_context = getattr(packet, "specialist_context", [])
    allowed_context_keys = {"kind", "model_id", "receipt_id", "revision", "session_date", "decision_cutoff", "headline", "bullets", "missing_evidence", "packet_hash"}
    for finding in specialist_context:
        if not isinstance(finding, dict) or set(finding) - allowed_context_keys:
            raise PrivacyViolationError("Unreviewed specialist-context field")
        if finding.get("session_date") != packet.session_id or str(finding.get("decision_cutoff", "99")) > cutoff_ist:
            raise PrivacyViolationError("Specialist context outside input cutoff")
        for key, value in finding.items():
            if key in {"bullets", "missing_evidence"}:
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise PrivacyViolationError("Invalid specialist-context list")
            elif value is not None and not isinstance(value, (str, int)):
                raise PrivacyViolationError("Invalid specialist-context scalar")
    sanitized_packet["specialist_context"] = specialist_context
    sanitized_packet["known_missing_inputs"] = [key for key, fact in current.items() if fact["value"] is None]

    # Strict fail-closed privacy verification before returning
    serialized = json.dumps(sanitized_packet, sort_keys=True)
    valid, reason = verify_sanitized_payload(serialized)
    if not valid:
        logger.critical("Privacy violation in sanitized packet: %s", reason)
        raise PrivacyViolationError(f"Sanitization failed closed: {reason}")

    return sanitized_packet
