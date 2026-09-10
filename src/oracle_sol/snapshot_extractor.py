"""Canonical Full-Sensorium Snapshot Extractor for Sol Market Brain (P0.3B Hardened).

Extracts typed, strictly VOB-free SolEvidenceSnapshot instances across 7 canonical domains
with fail-closed projection boundary, zero financial recalculation, and canonical Fast-Lane identity.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from src.oracle_sol.contracts import (
    DataAvailability,
    SolEvidenceSnapshot,
    SystemStatus,
)
from src.oracle_sol.field_registry import (
    CONTRACT_PRICING_ALLOWED_KEYS,
    STRIKE_LADDER_ALLOWED_KEYS,
)
from src.oracle_sol.provenance_guard import (
    ProvenanceGuard,
    UnverifiedLineageError,
)

IST = ZoneInfo("Asia/Kolkata")


def _get_first_present(data: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if isinstance(data, Mapping) and k in data and data[k] is not None:
            return data[k]
    return None


def _extract_number(val: Any) -> Tuple[Optional[float], DataAvailability]:
    if val is None:
        return None, DataAvailability.UNAVAILABLE
    try:
        f = float(val)
        if f != f:  # NaN
            return None, DataAvailability.UNAVAILABLE
        if f == 0.0:
            return 0.0, DataAvailability.OBSERVED_ZERO
        return f, DataAvailability.AVAILABLE
    except (ValueError, TypeError):
        return None, DataAvailability.UNAVAILABLE


def _extract_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"true", "1", "yes"}:
            return True
        if v in {"false", "0", "no"}:
            return False
    return None


def extract_sol_evidence_snapshot(
    feeds: Mapping[str, Any],
    session_date: Optional[str] = None,
) -> SolEvidenceSnapshot:
    """Extract a VOB-free canonical SolEvidenceSnapshot from parent CITADEL feeds.

    VOB PROJECTION BOUNDARY:
    Parent feeds may contain unrelated VOB data for legacy engines elsewhere in CITADEL.
    This function projects ONLY approved Sol sensorium feeds, and enforces fail-closed
    VOB quarantine on all selected fields.
    """
    # Extract only approved Sol candidate sub-feeds
    oracle_feed = feeds.get("oracle") or {}
    oracle_data = oracle_feed.get("data") or {} if isinstance(oracle_feed, Mapping) else {}

    order_flow_feed = feeds.get("order_flow") or {}
    order_flow_data = order_flow_feed.get("data") or {} if isinstance(order_flow_feed, Mapping) else {}

    argus_feed = feeds.get("argus") or {}
    argus_data = argus_feed.get("data") or {} if isinstance(argus_feed, Mapping) else {}

    # Canonical Fast-Lane Identity & Timestamps
    canonical_snapshot_id = str(
        _get_first_present(feeds, "idempotency_key", "canonical_snapshot_id", "snapshot_id", "revision", "record_id")
        or _get_first_present(argus_feed, "idempotency_key", "snapshot_id")
        or _get_first_present(oracle_feed, "idempotency_key", "snapshot_id")
        or ""
    ) or None

    raw_ts = (
        _get_first_present(oracle_data, "source_timestamp", "timestamp_utc")
        or _get_first_present(argus_data, "source_timestamp", "fetched_at")
        or (argus_data.get("argus_market_snapshot", {}).get("futures", {}).get("source_timestamp") if isinstance(argus_data.get("argus_market_snapshot"), Mapping) else None)
    )

    if raw_ts:
        now_utc = str(raw_ts)
        try:
            # Parse IST time string
            dt_ts = datetime.fromisoformat(now_utc.replace("Z", "+00:00")).astimezone(IST)
            now_ist = dt_ts.strftime("%H:%M:%S")
            market_session_date = session_date or dt_ts.strftime("%Y-%m-%d")
            identity_quality = "CANONICAL_AUTHENTIC"
            replay_stable = True
        except Exception:
            now_ist = datetime.now(IST).strftime("%H:%M:%S")
            market_session_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")
            identity_quality = "CANONICAL_AUTHENTIC"
            replay_stable = True
    else:
        now_utc = datetime.now(timezone.utc).isoformat()
        now_ist = datetime.now(IST).strftime("%H:%M:%S")
        market_session_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")
        identity_quality = "DEGRADED"
        replay_stable = False

    availability_matrix: Dict[str, str] = {}

    # ── 1. Underlying Domain ──
    spot_raw = _get_first_present(oracle_data, "spot_ltp", "spot_price", "spot")
    if spot_raw is None:
        spot_raw = _get_first_present(argus_data, "spot_ltp", "spot")
    if spot_raw is None and isinstance(argus_data.get("argus_market_snapshot"), Mapping):
        spot_raw = _get_first_present(argus_data["argus_market_snapshot"].get("futures", {}), "spot")
    spot_val, spot_avail = _extract_number(spot_raw)
    availability_matrix["spot_ltp"] = spot_avail.value

    fut_raw = _get_first_present(oracle_data, "futures_ltp")
    if fut_raw is None:
        fut_raw = _get_first_present(order_flow_data, "futures_ltp")
    if fut_raw is None and isinstance(argus_data.get("futures"), Mapping):
        fut_raw = _get_first_present(argus_data["futures"], "ltp")
    if fut_raw is None and isinstance(argus_data.get("argus_market_snapshot"), Mapping):
        fut_raw = _get_first_present(argus_data["argus_market_snapshot"].get("futures", {}), "ltp")
    fut_val, fut_avail = _extract_number(fut_raw)
    availability_matrix["futures_ltp"] = fut_avail.value

    # Canonical basis (no local recalculation)
    basis_raw = _get_first_present(oracle_data, "futures_basis", "basis")
    if basis_raw is None and isinstance(argus_data.get("futures"), Mapping):
        basis_raw = _get_first_present(argus_data["futures"], "basis")
    if basis_raw is None and isinstance(argus_data.get("argus_market_snapshot"), Mapping):
        basis_raw = _get_first_present(argus_data["argus_market_snapshot"].get("futures", {}), "basis")
    futures_basis, basis_avail = _extract_number(basis_raw)
    availability_matrix["futures_basis"] = basis_avail.value

    vwap_raw = _get_first_present(oracle_data, "session_vwap", "vwap")
    vwap_val, vwap_avail = _extract_number(vwap_raw)
    availability_matrix["session_vwap"] = vwap_avail.value

    # Canonical spot-to-vwap distance
    spot_to_vwap_raw = _get_first_present(oracle_data, "spot_to_vwap_pts", "spot_to_vwap")
    spot_to_vwap_pts, vwap_dist_avail = _extract_number(spot_to_vwap_raw)
    availability_matrix["spot_to_vwap_pts"] = vwap_dist_avail.value

    # ── 2. Contract Context Domain ──
    active_expiry = _get_first_present(argus_data, "expiry")
    if active_expiry is None and isinstance(argus_data.get("underlying"), Mapping):
        active_expiry = _get_first_present(argus_data["underlying"], "expiry")
    if active_expiry is None and isinstance(argus_data.get("futures"), Mapping):
        active_expiry = _get_first_present(argus_data["futures"], "expiry")
    if active_expiry is None and isinstance(argus_data.get("argus_market_snapshot"), Mapping):
        active_expiry = _get_first_present(argus_data["argus_market_snapshot"].get("futures", {}), "expiry")
    availability_matrix["active_expiry"] = "AVAILABLE" if active_expiry else "UNAVAILABLE"

    atm_strike_raw = _get_first_present(oracle_data, "atm_strike")
    if atm_strike_raw is None:
        atm_strike_raw = _get_first_present(argus_data, "atm_strike")
    atm_strike_val, atm_strike_avail = _extract_number(atm_strike_raw)
    availability_matrix["atm_strike"] = atm_strike_avail.value

    futures_sid = str(
        _get_first_present(oracle_data, "futures_sid", "futures_security_id")
        or (argus_data.get("futures", {}).get("security_id") if isinstance(argus_data.get("futures"), Mapping) else None)
        or (argus_data.get("argus_market_snapshot", {}).get("futures", {}).get("security_id") if isinstance(argus_data.get("argus_market_snapshot"), Mapping) else None)
        or ""
    ) or None
    availability_matrix["futures_security_id"] = "AVAILABLE" if futures_sid else "UNAVAILABLE"

    # ── 3. Open Interest & Structural Activity Domain ──
    sudden_oi_raw = argus_data.get("sudden_oi") if isinstance(argus_data.get("sudden_oi"), Mapping) else {}
    sudden_oi_call = sudden_oi_raw.get("CALL") if isinstance(sudden_oi_raw.get("CALL"), Mapping) else None
    sudden_oi_put = sudden_oi_raw.get("PUT") if isinstance(sudden_oi_raw.get("PUT"), Mapping) else None
    availability_matrix["sudden_oi_call"] = "AVAILABLE" if sudden_oi_call else "UNAVAILABLE"
    availability_matrix["sudden_oi_put"] = "AVAILABLE" if sudden_oi_put else "UNAVAILABLE"

    strike_ladder: List[Dict[str, Any]] = []
    raw_chain_strikes = argus_data.get("chain_strikes") or oracle_data.get("strike_ladder") or argus_data.get("atm_window") or []
    if isinstance(raw_chain_strikes, list) and raw_chain_strikes:
        for item in raw_chain_strikes[:10]:
            if isinstance(item, Mapping):
                ProvenanceGuard.assert_vob_free_fail_closed(item)
                ce_leg = item.get("ce") if isinstance(item.get("ce"), Mapping) else {}
                pe_leg = item.get("pe") if isinstance(item.get("pe"), Mapping) else {}
                ce_closed_5m_oi = _get_first_present(item, "ce_closed_5m_oi")
                if ce_closed_5m_oi is None:
                    ce_closed_5m_oi = ce_leg.get("intraday_change_oi")
                pe_closed_5m_oi = _get_first_present(item, "pe_closed_5m_oi")
                if pe_closed_5m_oi is None:
                    pe_closed_5m_oi = pe_leg.get("intraday_change_oi")
                clean_item = {
                    "strike": _get_first_present(item, "strike"),
                    "relation_to_atm": _get_first_present(item, "relation_to_atm", "rel", "ce_moneyness"),
                    "ce_security_id": _get_first_present(item, "ce_security_id", "ce_sid") or (item.get("ce", {}).get("security_id") if isinstance(item.get("ce"), Mapping) else None),
                    "ce_ltp": _get_first_present(item, "ce_ltp") or (item.get("ce", {}).get("ltp") if isinstance(item.get("ce"), Mapping) else None),
                    "ce_fair_gap_pct": _get_first_present(item, "ce_fair_gap_pct"),
                    "ce_closed_5m_oi": ce_closed_5m_oi,
                    "ce_closed_15m_oi": _get_first_present(item, "ce_closed_15m_oi"),
                    "ce_structure": _get_first_present(item, "ce_structure") or (item.get("ce", {}).get("positioning") if isinstance(item.get("ce"), Mapping) else None),
                    "pe_security_id": _get_first_present(item, "pe_security_id", "pe_sid") or (item.get("pe", {}).get("security_id") if isinstance(item.get("pe"), Mapping) else None),
                    "pe_ltp": _get_first_present(item, "pe_ltp") or (item.get("pe", {}).get("ltp") if isinstance(item.get("pe"), Mapping) else None),
                    "pe_fair_gap_pct": _get_first_present(item, "pe_fair_gap_pct"),
                    "pe_closed_5m_oi": pe_closed_5m_oi,
                    "pe_closed_15m_oi": _get_first_present(item, "pe_closed_15m_oi"),
                    "pe_structure": _get_first_present(item, "pe_structure") or (item.get("pe", {}).get("positioning") if isinstance(item.get("pe"), Mapping) else None),
                }
                strike_ladder.append(clean_item)
    availability_matrix["strike_ladder"] = "AVAILABLE" if strike_ladder else "UNAVAILABLE"

    # ── 4. Order Flow Domain ──
    mlofi_raw = _get_first_present(order_flow_data, "mlofi", "current_mlofi")
    mlofi_val, mlofi_avail = _extract_number(mlofi_raw)
    availability_matrix["mlofi_5l"] = mlofi_avail.value

    flow_x_raw = _get_first_present(order_flow_data, "flow_x", "current_flow_x")
    current_flow_x, flow_x_avail = _extract_number(flow_x_raw)
    availability_matrix["current_flow_x"] = flow_x_avail.value

    mlofi_session_extreme = _extract_bool(
        _get_first_present(order_flow_data, "is_extreme", "mlofi_is_session_extreme")
    )
    availability_matrix["mlofi_session_extreme"] = (
        "AVAILABLE" if mlofi_session_extreme is not None else "UNAVAILABLE"
    )

    # ── 5. Pricing & Liquidity Domain ──
    def extract_contract_pricing(side: str) -> Optional[Dict[str, Any]]:
        raw_p = argus_data.get(f"{side.lower()}_pricing") or argus_data.get(f"{side.upper()}_pricing")
        if isinstance(raw_p, Mapping):
            ProvenanceGuard.assert_vob_free_fail_closed(raw_p)
            return dict(raw_p)
        return None

    ce_pricing = extract_contract_pricing("ce")
    pe_pricing = extract_contract_pricing("pe")
    availability_matrix["ce_pricing"] = "AVAILABLE" if ce_pricing else "UNAVAILABLE"
    availability_matrix["pe_pricing"] = "AVAILABLE" if pe_pricing else "UNAVAILABLE"

    # ── 6. Volatility & Straddle Domain ──
    atm_straddle_raw = _get_first_present(oracle_data, "atm_straddle_price", "straddle_price")
    if atm_straddle_raw is None and isinstance(argus_data.get("straddle"), Mapping):
        atm_straddle_raw = _get_first_present(argus_data["straddle"], "now")
    atm_straddle_val, atm_straddle_avail = _extract_number(atm_straddle_raw)
    availability_matrix["atm_straddle_price"] = atm_straddle_avail.value

    straddle_5m_raw = _get_first_present(argus_data, "straddle_change_5m", "straddle_5m")
    straddle_change_5m, straddle_5m_avail = _extract_number(straddle_5m_raw)
    availability_matrix["straddle_change_5m"] = straddle_5m_avail.value

    atm_iv_raw = _get_first_present(oracle_data, "atm_iv")
    atm_iv_val, atm_iv_avail = _extract_number(atm_iv_raw)
    availability_matrix["atm_iv"] = atm_iv_avail.value

    skew_25_raw = _get_first_present(oracle_data, "skew_25d")
    skew_25d, skew_25_avail = _extract_number(skew_25_raw)
    availability_matrix["skew_25d"] = skew_25_avail.value

    skew_10_raw = _get_first_present(oracle_data, "skew_10d")
    skew_10d, skew_10_avail = _extract_number(skew_10_raw)
    availability_matrix["skew_10d"] = skew_10_avail.value

    exp_move_raw = _get_first_present(oracle_data, "expected_move_pts", "expected_move")
    expected_move_pts, exp_move_avail = _extract_number(exp_move_raw)
    availability_matrix["expected_move_pts"] = exp_move_avail.value

    # ── 7. Positioning & GEX Domain ──
    gex_raw = _get_first_present(oracle_data, "net_gex_inr", "total_gex")
    net_gex_inr, gex_avail = _extract_number(gex_raw)
    availability_matrix["net_gex_inr"] = gex_avail.value

    high_gex_raw = _get_first_present(oracle_data, "highest_gex_strike", "high_gex_strike")
    highest_gex_strike, high_gex_avail = _extract_number(high_gex_raw)
    availability_matrix["highest_gex_strike"] = high_gex_avail.value

    zero_gex_raw = _get_first_present(oracle_data, "zero_gamma_level", "zero_gamma")
    zero_gamma_level, zero_gex_avail = _extract_number(zero_gex_raw)
    availability_matrix["zero_gamma_level"] = zero_gex_avail.value

    # Upstream latencies & health
    quote_age_ms, _ = _extract_number(_get_first_present(oracle_data, "dhan_quote_age_ms"))
    flow_age_ms, _ = _extract_number(_get_first_present(order_flow_data, "age_ms"))
    chain_age_ms, _ = _extract_number(_get_first_present(argus_data, "age_ms"))

    upstream_health = {
        "oracle_feed_ok": _extract_bool(oracle_feed.get("ok")),
        "order_flow_feed_ok": _extract_bool(order_flow_feed.get("ok")),
        "argus_feed_ok": _extract_bool(argus_feed.get("ok")),
        "dhan_connected": _extract_bool(oracle_data.get("dhan_connected")),
        "market_session_active": _extract_bool(oracle_data.get("market_open")),
        "producer_sources": {
            "market": {
                "source_id": oracle_data.get("source_id"),
                "source_timestamp": oracle_data.get("source_timestamp"),
                "provenance": oracle_data.get("source_provenance"),
            },
            "order_flow": {
                "source_id": order_flow_data.get("source_id"),
                "source_revision": order_flow_data.get("source_revision"),
                "source_timestamp": order_flow_data.get("source_timestamp"),
                "provenance": order_flow_data.get("source_provenance"),
            },
            "options": {
                "source_id": argus_data.get("source_id"),
                "source_timestamp": argus_data.get("option_intelligence_source_timestamp")
                or argus_data.get("source_timestamp"),
                "provenance": argus_data.get("source_provenance"),
            },
        },
    }

    if upstream_health["dhan_connected"] is False or (spot_val is None and fut_val is None):
        system_status = SystemStatus.UNAVAILABLE
    elif upstream_health["market_session_active"] is False:
        system_status = SystemStatus.OFF_MARKET
    elif upstream_health["oracle_feed_ok"] is False or upstream_health["order_flow_feed_ok"] is False:
        system_status = SystemStatus.DATA_DEGRADED
    elif upstream_health["dhan_connected"] is True and spot_val is not None:
        system_status = SystemStatus.HEALTHY
    else:
        system_status = SystemStatus.UNAVAILABLE

    source_hashes = {
        "oracle_feed_hash": ProvenanceGuard.compute_sha256(oracle_data),
        "order_flow_hash": ProvenanceGuard.compute_sha256(order_flow_data),
        "argus_feed_hash": ProvenanceGuard.compute_sha256(argus_data),
    }

    # Deterministic Replay-Stable Snapshot ID derived from canonical ID + evidence payload
    canonical_seed_dict = {
        "canonical_id": canonical_snapshot_id or "UNAVAILABLE",
        "timestamp_utc": now_utc,
        "spot": spot_val,
        "fut": fut_val,
        "basis": futures_basis,
        "atm": atm_strike_val,
        "mlofi": mlofi_val,
        "gex": net_gex_inr,
        "sudden_oi_call": sudden_oi_call,
        "sudden_oi_put": sudden_oi_put,
        "source_hashes": source_hashes,
    }
    canonical_seed_bytes = json.dumps(canonical_seed_dict, sort_keys=True, default=str).encode("utf-8")
    snapshot_id = f"snap_{hashlib.sha256(canonical_seed_bytes).hexdigest()[:32]}"

    snapshot = SolEvidenceSnapshot(
        snapshot_id=snapshot_id,
        canonical_snapshot_id=canonical_snapshot_id,
        market_session_date=market_session_date,
        identity_quality=identity_quality,
        replay_stable=replay_stable,
        timestamp_utc=now_utc,
        timestamp_ist=now_ist,
        system_status=system_status,
        upstream_source_health=upstream_health,
        dhan_quote_age_ms=quote_age_ms,
        order_flow_age_ms=flow_age_ms,
        option_chain_age_ms=chain_age_ms,
        spot_ltp=spot_val,
        futures_ltp=fut_val,
        futures_basis=futures_basis,
        session_vwap=vwap_val,
        spot_to_vwap_pts=spot_to_vwap_pts,
        active_expiry=active_expiry,
        atm_strike=atm_strike_val,
        futures_security_id=futures_sid,
        sudden_oi_call=sudden_oi_call,
        sudden_oi_put=sudden_oi_put,
        strike_ladder=strike_ladder,
        mlofi_5l=mlofi_val,
        current_flow_x=current_flow_x,
        mlofi_session_extreme=mlofi_session_extreme,
        ce_pricing=ce_pricing,
        pe_pricing=pe_pricing,
        atm_straddle_price=atm_straddle_val,
        straddle_change_5m=straddle_change_5m,
        atm_iv=atm_iv_val,
        skew_25d=skew_25d,
        skew_10d=skew_10d,
        expected_move_pts=expected_move_pts,
        net_gex_inr=net_gex_inr,
        highest_gex_strike=highest_gex_strike,
        zero_gamma_level=zero_gamma_level,
        domestic_indices=order_flow_data.get("domestic_indices") or {},
        availability_matrix=availability_matrix,
        source_hashes=source_hashes,
        vob_free_verified="ZERO_VOB_ALLOWLIST_CONFIRMED",
    )

    # Validate projected snapshot field-by-field against allowlist
    ProvenanceGuard.verify_field_level_allowlist(snapshot.to_dict(), strict=True)
    return snapshot
