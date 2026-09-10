"""Explicit canonical Oracle producer projection for the Sol evidence boundary.

This module performs structural selection only.  It does not calculate market
metrics, classify direction, consult VOB, or fill absent values with guesses.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _argus_data(projection: Any) -> Mapping[str, Any]:
    outer = _mapping(projection)
    nested = _mapping(outer.get("data"))
    # cached_argus_projection is a status envelope whose data member is the
    # canonical ARGUS payload.  Recorded frames may already be that payload.
    return nested if nested else outer


def _selected(source: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    return {key: source.get(key) for key in keys if source.get(key) is not None}


def _closed_oi_by_security(sudden_side: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = sudden_side.get("strikes")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("security_id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("security_id") is not None
    }


def _strike_ladder(
    rows: Any,
    call_oi: Mapping[str, Any],
    put_oi: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    call_by_sid = _closed_oi_by_security(call_oi)
    put_by_sid = _closed_oi_by_security(put_oi)
    projected: list[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ce = _mapping(row.get("ce") or row.get("CE"))
        pe = _mapping(row.get("pe") or row.get("PE"))
        ce_closed = call_by_sid.get(str(ce.get("security_id") or ""), {})
        pe_closed = put_by_sid.get(str(pe.get("security_id") or ""), {})
        projected.append(
            {
                "strike": row.get("strike"),
                "relation_to_atm": row.get("ce_moneyness"),
                "ce_security_id": ce.get("security_id"),
                "ce_ltp": ce.get("ltp"),
                "ce_closed_5m_oi": ce_closed.get("oi_delta_5m"),
                "ce_structure": ce_closed.get("state"),
                "pe_security_id": pe.get("security_id"),
                "pe_ltp": pe.get("ltp"),
                "pe_closed_5m_oi": pe_closed.get("oi_delta_5m"),
                "pe_structure": pe_closed.get("state"),
            }
        )
    return projected


def _atm_pricing(
    rows: Any,
    atm_strike: Any,
    side: str,
    expiry: Any,
    source_timestamp: Any,
) -> Optional[Dict[str, Any]]:
    if not isinstance(rows, list) or atm_strike is None:
        return None
    for row in rows:
        if not isinstance(row, Mapping) or row.get("strike") != atm_strike:
            continue
        leg = _mapping(row.get(side.lower()) or row.get(side.upper()))
        if not leg or leg.get("security_id") is None:
            return None
        return {
            "security_id": leg.get("security_id"),
            "strike": row.get("strike"),
            "option_type": side.upper(),
            "expiry": expiry,
            "ltp": leg.get("ltp"),
            "best_bid_price": leg.get("top_bid_price"),
            "best_ask_price": leg.get("top_ask_price"),
            "iv": leg.get("iv"),
            "source_timestamp": source_timestamp,
        }
    return None


def project_canonical_oracle_to_sol_feeds(
    *,
    argus_projection: Any,
    order_flow_projection: Any = None,
    futures_chart_projection: Any = None,
    option_buyer_projection: Any = None,
    options_structure_projection: Any = None,
    transport_health: Any = None,
    market_info: Any = None,
) -> Dict[str, Any]:
    """Select real producer-owned facts into the normalized Sol input shape."""

    argus = _argus_data(argus_projection)
    underlying = _mapping(argus.get("underlying"))
    futures = _mapping(argus.get("futures"))
    rows = argus.get("atm_window")

    flow = _mapping(order_flow_projection)
    family_values = _mapping(flow.get("family_values"))
    book_pressure = _mapping(family_values.get("BOOK_PRESSURE"))
    response_quality = _mapping(family_values.get("RESPONSE_QUALITY"))
    chart = _mapping(futures_chart_projection)
    forming_candle = _mapping(chart.get("forming_candle"))

    option_buyer = _mapping(option_buyer_projection)
    sudden_oi = _mapping(option_buyer.get("sudden_oi"))
    sudden_call = _mapping(sudden_oi.get("CALL"))
    sudden_put = _mapping(sudden_oi.get("PUT"))
    straddle_dict = _mapping(option_buyer.get("straddle"))
    option_intelligence = _mapping(option_buyer.get("option_intelligence"))
    volatility = _mapping(option_intelligence.get("volatility_opportunity"))
    skew = _mapping(option_intelligence.get("iv_skew"))
    gex = _mapping(option_intelligence.get("gex"))

    ose = _mapping(options_structure_projection)
    ose_ssi = _mapping(ose.get("ssi"))
    ose_dec = _mapping(ose.get("decision_window"))

    transport = _mapping(transport_health)
    market_open = str(underlying.get("market_state") or "").upper() == "OPEN"
    upstox_healthy = (
        transport.get("UPSTOX_WS_CONNECTED") is True
        or transport.get("UPSTOX_STATE") == "HEALTHY"
        or transport.get("CANONICAL_SOURCE") == "UPSTOX"
    )
    if market_open:
        dhan_connected = (
            transport.get("BASKET_HEALTH") in {"FULLY_FRESH", "PARTIALLY_RECEIVING"}
            and int(transport.get("CURRENTLY_RECEIVING_INSTRUMENTS") or 0) > 0
        ) or upstox_healthy
    else:
        dhan_connected = transport.get("WS_CONNECTED") is True or upstox_healthy

    source_timestamp = (
        underlying.get("source_event_time")
        or futures.get("source_timestamp")
        or underlying.get("fetched_at")
    )
    option_timestamp = option_buyer.get("source_timestamp") or source_timestamp
    chart_timestamp = forming_candle.get("source_timestamp") or chart.get("source_timestamp")
    flow_timestamp = flow.get("generated_at") or _mapping(flow.get("flow_pulse")).get("source_timestamp")
    canonical_snapshot_id = flow.get("snapshot_id")

    atm_strike = underlying.get("atm_strike")
    option_expiry = underlying.get("expiry")

    # Net GEX: preserve both raw producer unit (Crores) and Sol contract (INR)
    gex_cr = gex.get("total_net_gex_inr_cr")

    spot_val = underlying.get("ltp")
    vwap_val = forming_candle.get("vwap")

    oracle_data = {
        "pcr_oi": _mapping(argus.get("totals")).get("pcr"),
        "spot_ltp": spot_val,
        "futures_ltp": futures.get("ltp"),
        "futures_basis": futures.get("basis"),
        "session_vwap": vwap_val,
        "spot_to_vwap_pts": None,
        "atm_strike": atm_strike,
        "futures_sid": futures.get("security_id"),
        "source_timestamp": source_timestamp,
        "dhan_connected": dhan_connected,
        "market_open": market_open,
        "atm_iv": volatility.get("atm_iv"),
        "skew_25d": skew.get("skew_25d_spread"),
        "skew_10d": skew.get("skew_10d_spread"),
        "expected_move_pts": None,
        # The producer exposes total_net_gex_inr_cr, while Sol's contract says
        # INR. No unit conversion or relabeling belongs in this adapter.
        "net_gex_inr": None,
        "total_net_gex_inr_cr": gex_cr,
        "dealer_regime": gex.get("dealer_regime"),
        "highest_gex_strike": gex.get("highest_gex_strike"),
        "zero_gamma_level": gex.get("zero_gamma_strike"),
        "atm_straddle_price": straddle_dict.get("now"),
        "straddle_change_5m": straddle_dict.get("change_5m"),
        "straddle_change_15m": straddle_dict.get("change_15m"),
        "ose_ssi_score": ose_ssi.get("score"),
        "ose_decision_window": ose_dec.get("state"),
        "india_vix": _mapping(market_info).get("india_vix"),
        "india_vix_context": _mapping(market_info).get("india_vix_context"),
        "source_id": canonical_snapshot_id,
        "source_provenance": "ARGUS_UNDERLYING_FUTURES + FUTURES_CHART + OPTION_INTELLIGENCE",
        "chart_source_timestamp": chart_timestamp,
    }

    order_flow_data = {
        "mlofi": book_pressure.get("mlofi"),
        "flow_x": None,
        "buyer_absorption": response_quality.get("buyer_absorption"),
        "seller_absorption": response_quality.get("seller_absorption"),
        "failed_aggression": response_quality.get("failed_aggression"),
        "price_response_efficiency": response_quality.get("price_response_efficiency"),
        "continuation_efficiency": response_quality.get("continuation_efficiency"),
        "cvd": flow.get("cvd"),
        "bid_depletion": book_pressure.get("bid_depletion"),
        "ask_depletion": book_pressure.get("ask_depletion"),
        "bid_refill": book_pressure.get("bid_refill"),
        "ask_refill": book_pressure.get("ask_refill"),
        "order_flow_response_state": response_quality.get("state"),
        "is_extreme": None,
        "age_ms": None,
        "source_timestamp": flow_timestamp,
        "source_id": flow.get("snapshot_id"),
        "source_revision": flow.get("revision"),
        "source_provenance": "ORDER_FLOW_SERVICE_LATEST_PROJECTION",
    }

    argus_normalized = {
        "source_timestamp": source_timestamp,
        "source_id": canonical_snapshot_id,
        "source_provenance": "CANONICAL_ARGUS_DHAN_OPTION_CHAIN",
        "expiry": option_expiry,
        "atm_strike": atm_strike,
        "futures": _selected(
            futures,
            "ltp",
            "spot",
            "basis",
            "expiry",
            "security_id",
            "source_timestamp",
            "status",
        ),
        "chain_strikes": _strike_ladder(rows, sudden_call, sudden_put),
        "sudden_oi": {
            "CALL": dict(sudden_call) if sudden_call else None,
            "PUT": dict(sudden_put) if sudden_put else None,
        },
        "ce_pricing": _atm_pricing(rows, atm_strike, "CE", option_expiry, source_timestamp),
        "pe_pricing": _atm_pricing(rows, atm_strike, "PE", option_expiry, source_timestamp),
        "option_intelligence_source_timestamp": option_timestamp,
    }

    argus_ok = bool(underlying.get("ltp") is not None or futures.get("ltp") is not None)
    flow_ok = bool(flow.get("snapshot_id") and flow_timestamp)
    return {
        "canonical_snapshot_id": canonical_snapshot_id,
        "revision": flow.get("revision"),
        "oracle": {"ok": argus_ok, "data": oracle_data},
        "order_flow": {"ok": flow_ok, "data": order_flow_data},
        "argus": {"ok": argus_ok, "data": argus_normalized},
    }
