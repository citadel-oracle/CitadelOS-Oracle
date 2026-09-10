"""Comprehensive VOB-Free Sensorium Field Registry & Lineage Catalog (P0.3 Hardened).

Authoritative registry of the canonical VOB-free market features currently exposed to
Sol, organized across 7 typed domains with ownership, lineage, and schema types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class FieldLineageType(str, Enum):
    CANONICAL_RAW = "CANONICAL_RAW"
    CANONICAL_DERIVED = "CANONICAL_DERIVED"


@dataclass(frozen=True)
class FieldMetadata:
    field_path: str
    domain: str
    canonical_owner: str
    source_module: str
    lineage_type: FieldLineageType
    vob_dependency: bool
    description: str
    type_name: str
    security_id_required: bool = False
    expiry_required: bool = False


# The authoritative registry of the currently supported VOB-free canonical fields.
SOL_VOB_FREE_FIELD_REGISTRY: Dict[str, FieldMetadata] = {
    "pcr_oi": FieldMetadata(
        field_path="pcr_oi", domain="oi", canonical_owner="OptionChainEngine",
        source_module="src/argus/option_chain_engine.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED, vob_dependency=False,
        description="Total put OI divided by total call OI; positioning context, not standalone direction.",
        type_name="Optional[float]",
    ),
    # ── 1. Underlying Domain ──
    "spot_ltp": FieldMetadata(
        field_path="spot_ltp",
        domain="underlying",
        canonical_owner="DhanMarketDataGateway",
        source_module="src/broker/dhan_client.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Underlying NIFTY index spot last traded price",
        type_name="Optional[float]",
    ),
    "futures_ltp": FieldMetadata(
        field_path="futures_ltp",
        domain="underlying",
        canonical_owner="DhanMarketDataGateway",
        source_module="src/broker/dhan_client.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Active near-month NIFTY futures last traded price",
        type_name="Optional[float]",
        security_id_required=True,
        expiry_required=True,
    ),
    "futures_basis": FieldMetadata(
        field_path="futures_basis",
        domain="underlying",
        canonical_owner="OracleDevService",
        source_module="src/oracle_development/oracle_dev_service.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Futures basis spread (futures_ltp - spot_ltp)",
        type_name="Optional[float]",
    ),
    "session_vwap": FieldMetadata(
        field_path="session_vwap",
        domain="underlying",
        canonical_owner="StrategyLabVWAP",
        source_module="src/strategy_lab/core/vwap.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Intraday session volume-weighted average price",
        type_name="Optional[float]",
    ),
    "spot_to_vwap_pts": FieldMetadata(
        field_path="spot_to_vwap_pts",
        domain="underlying",
        canonical_owner="StrategyLabVWAP",
        source_module="src/oracle_development/oracle_dev_service.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Distance in index points between Spot and Session VWAP",
        type_name="Optional[float]",
    ),
    "domestic_indices": FieldMetadata(
        field_path="domestic_indices",
        domain="underlying",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/service.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Domestic index spot prices (NIFTY, BANKNIFTY, MIDCPNIFTY)",
        type_name="Dict[str, float]",
    ),

    # ── 2. Contract Context Domain ──
    "active_expiry": FieldMetadata(
        field_path="active_expiry",
        domain="contract_context",
        canonical_owner="OptionChainEngine",
        source_module="src/argus/option_chain_engine.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Authoritative active weekly option expiry string",
        type_name="Optional[str]",
        expiry_required=True,
    ),
    "atm_strike": FieldMetadata(
        field_path="atm_strike",
        domain="contract_context",
        canonical_owner="OptionChainEngine",
        source_module="src/argus/option_chain_engine.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Authoritative active ATM strike from canonical contract resolver",
        type_name="Optional[float]",
    ),
    "futures_security_id": FieldMetadata(
        field_path="futures_security_id",
        domain="contract_context",
        canonical_owner="DhanMarketDataGateway",
        source_module="src/broker/dhan_client.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Dhan security ID of active near-month futures contract",
        type_name="Optional[str]",
        security_id_required=True,
    ),

    # ── 3. Open Interest & Structural Activity Domain ──
    "sudden_oi_call": FieldMetadata(
        field_path="sudden_oi_call",
        domain="oi",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Call-side sudden closed OI surge metrics and percentiles",
        type_name="Optional[Dict[str, Any]]",
    ),
    "sudden_oi_put": FieldMetadata(
        field_path="sudden_oi_put",
        domain="oi",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Put-side sudden closed OI surge metrics and percentiles",
        type_name="Optional[Dict[str, Any]]",
    ),
    "strike_ladder": FieldMetadata(
        field_path="strike_ladder",
        domain="oi",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Authoritative strike ladder with 5M/15M closed OI deltas and fair value gaps",
        type_name="List[Dict[str, Any]]",
        security_id_required=True,
        expiry_required=True,
    ),

    # ── 4. Order Flow Domain ──
    "mlofi_5l": FieldMetadata(
        field_path="mlofi_5l",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/service.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="5-Level Multi-Level Order Flow Imbalance (MLOFI)",
        type_name="Optional[float]",
    ),
    "current_flow_x": FieldMetadata(
        field_path="current_flow_x",
        domain="flow",
        canonical_owner="ResolverEngine",
        source_module="src/oracle/resolver_engine.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Multiplier of order flow aggression relative to session baseline",
        type_name="Optional[float]",
    ),
    "mlofi_session_extreme": FieldMetadata(
        field_path="mlofi_session_extreme",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/service.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Whether MLOFI is at intraday session extreme aggressor pressure",
        type_name="Optional[bool]",
    ),

    # ── 5. Options Pricing & Liquidity Domain ──
    "ce_pricing": FieldMetadata(
        field_path="ce_pricing",
        domain="pricing",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Active ATM/ITM Call contract pricing, fair value, spread and depth",
        type_name="Optional[Dict[str, Any]]",
        security_id_required=True,
    ),
    "pe_pricing": FieldMetadata(
        field_path="pe_pricing",
        domain="pricing",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Active ATM/ITM Put contract pricing, fair value, spread and depth",
        type_name="Optional[Dict[str, Any]]",
        security_id_required=True,
    ),

    # ── 6. Volatility & Straddle Domain ──
    "atm_straddle_price": FieldMetadata(
        field_path="atm_straddle_price",
        domain="volatility",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="ATM Call + Put combined premium straddle cost",
        type_name="Optional[float]",
    ),
    "straddle_change_5m": FieldMetadata(
        field_path="straddle_change_5m",
        domain="volatility",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="5-minute change in ATM straddle premium",
        type_name="Optional[float]",
    ),
    "atm_iv": FieldMetadata(
        field_path="atm_iv",
        domain="volatility",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Black-76 inverted implied volatility via bisection",
        type_name="Optional[float]",
    ),
    "skew_25d": FieldMetadata(
        field_path="skew_25d",
        domain="volatility",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="25-Delta Put-Call Implied Volatility skew spread",
        type_name="Optional[float]",
    ),
    "skew_10d": FieldMetadata(
        field_path="skew_10d",
        domain="volatility",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="10-Delta OTM Wing Implied Volatility skew spread",
        type_name="Optional[float]",
    ),
    "expected_move_pts": FieldMetadata(
        field_path="expected_move_pts",
        domain="volatility",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="1-Day expected move in underlying index points",
        type_name="Optional[float]",
    ),
    "india_vix": FieldMetadata(
        field_path="india_vix",
        domain="volatility",
        canonical_owner="UpstoxMarketInfoService",
        source_module="src/oracle/market_info_service.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="India VIX real-time volatility index value from canonical Upstox feed",
        type_name="Optional[float]",
    ),
    "india_vix_context": FieldMetadata(
        field_path="india_vix_context",
        domain="volatility",
        canonical_owner="UpstoxMarketInfoService",
        source_module="src/oracle/market_info_service.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="India VIX regime context label (e.g. RISING VOL, SUBDUED VOL)",
        type_name="Optional[str]",
    ),

    # ── 7. Positioning & GEX Domain ──
    "net_gex_inr": FieldMetadata(
        field_path="net_gex_inr",
        domain="positioning",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Aggregate dealer Gamma Exposure across active strikes in INR",
        type_name="Optional[float]",
    ),
    "highest_gex_strike": FieldMetadata(
        field_path="highest_gex_strike",
        domain="positioning",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Strike with highest concentrated dealer gamma",
        type_name="Optional[float]",
    ),
    "zero_gamma_level": FieldMetadata(
        field_path="zero_gamma_level",
        domain="positioning",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Zero-Gamma transition inflection level in spot points",
        type_name="Optional[float]",
    ),
    "buyer_absorption": FieldMetadata(
        field_path="buyer_absorption",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Buyer absorption metric (aggressive buys absorbed by passive asks)",
        type_name="Optional[float]",
    ),
    "seller_absorption": FieldMetadata(
        field_path="seller_absorption",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Seller absorption metric (aggressive sells absorbed by passive bids)",
        type_name="Optional[float]",
    ),
    "failed_aggression": FieldMetadata(
        field_path="failed_aggression",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Magnitude of aggressive order flow that failed to advance price",
        type_name="Optional[float]",
    ),
    "price_response_efficiency": FieldMetadata(
        field_path="price_response_efficiency",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Efficiency of price advancement per unit of aggressive volume",
        type_name="Optional[float]",
    ),
    "continuation_efficiency": FieldMetadata(
        field_path="continuation_efficiency",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Continuation efficiency of directional order flow",
        type_name="Optional[float]",
    ),
    "cvd": FieldMetadata(
        field_path="cvd",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/service.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Cumulative Volume Delta across the active trading session",
        type_name="Optional[int]",
    ),
    "bid_depletion": FieldMetadata(
        field_path="bid_depletion",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Cumulative bid quantity depletion count",
        type_name="Optional[int]",
    ),
    "ask_depletion": FieldMetadata(
        field_path="ask_depletion",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Cumulative ask quantity depletion count",
        type_name="Optional[int]",
    ),
    "bid_refill": FieldMetadata(
        field_path="bid_refill",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Cumulative bid quantity refill count",
        type_name="Optional[int]",
    ),
    "ask_refill": FieldMetadata(
        field_path="ask_refill",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_RAW,
        vob_dependency=False,
        description="Cumulative ask quantity refill count",
        type_name="Optional[int]",
    ),
    "order_flow_response_state": FieldMetadata(
        field_path="order_flow_response_state",
        domain="flow",
        canonical_owner="OrderFlowService",
        source_module="src/order_flow/features.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Discrete order flow response regime (BUYERS_ABSORBED, SELLERS_ABSORBED, etc.)",
        type_name="Optional[str]",
    ),
    "total_net_gex_inr_cr": FieldMetadata(
        field_path="total_net_gex_inr_cr",
        domain="positioning",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Total Net Gamma Exposure across all strikes in Crores INR",
        type_name="Optional[float]",
    ),
    "dealer_regime": FieldMetadata(
        field_path="dealer_regime",
        domain="positioning",
        canonical_owner="OptionIntelligenceEngine",
        source_module="src/oracle/option_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Dealer gamma regime (LONG_GAMMA_PIN vs SHORT_GAMMA_AMPLIFY)",
        type_name="Optional[str]",
    ),
    "straddle_change_15m": FieldMetadata(
        field_path="straddle_change_15m",
        domain="volatility",
        canonical_owner="OptionBuyerIntelligence",
        source_module="src/oracle/option_buyer_intelligence.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="15-minute change in ATM straddle premium",
        type_name="Optional[float]",
    ),
    "ose_ssi_score": FieldMetadata(
        field_path="ose_ssi_score",
        domain="structure",
        canonical_owner="OptionsStructureEngine",
        source_module="src/ose/engine.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Options Structure Engine Structural Strength Index (0-100)",
        type_name="Optional[int]",
    ),
    "ose_decision_window": FieldMetadata(
        field_path="ose_decision_window",
        domain="structure",
        canonical_owner="OptionsStructureEngine",
        source_module="src/ose/engine.py",
        lineage_type=FieldLineageType.CANONICAL_DERIVED,
        vob_dependency=False,
        description="Options Structure Engine Decision Window state (INSIDE DEMAND/SUPPLY, ROOM AVAILABLE, etc.)",
        type_name="Optional[str]",
    ),
}


@dataclass(frozen=True)
class SurfaceFieldMetadata:
    """One exact browser leaf mapped to one canonical backend value."""

    field_id: str
    endpoint: str
    backend_path: str
    display_kind: str = "TEXT"
    availability_path: Optional[str] = None
    vob_free: bool = True


# The browser truth auditor and React semantic attributes share these IDs.
# This extends the existing Sol registry; it is not a competing market registry.
SOL_SURFACE_FIELD_REGISTRY: Dict[str, SurfaceFieldMetadata] = {
    "sol.provider.status": SurfaceFieldMetadata(
        "sol.provider.status", "/v1/oracle/sol/state", "provider_telemetry.provider_status"
    ),
    "sol.brain.worker": SurfaceFieldMetadata(
        "sol.brain.worker", "/v1/oracle/sol/state", "health_strip.brain_worker", "PLAIN_STATUS"
    ),
    "sol.reasoning.status": SurfaceFieldMetadata(
        "sol.reasoning.status", "/v1/oracle/sol/state", "health_strip.reasoning_state", "PLAIN_STATUS"
    ),
    "sol.data.status": SurfaceFieldMetadata(
        "sol.data.status", "/v1/oracle/sol/state", "health_strip.data_stream", "PLAIN_STATUS"
    ),
    "sol.analysis.last_time": SurfaceFieldMetadata(
        "sol.analysis.last_time", "/v1/oracle/sol/state", "health_strip.last_analysis_time"
    ),
    "sol.reading.futures": SurfaceFieldMetadata(
        "sol.reading.futures", "/v1/oracle/sol/state", "reading_domains.futures.status", "STATUS_DOT"
    ),
    "sol.reading.options_oi": SurfaceFieldMetadata(
        "sol.reading.options_oi", "/v1/oracle/sol/state", "reading_domains.options_oi.status", "STATUS_DOT"
    ),
    "sol.reading.flow": SurfaceFieldMetadata(
        "sol.reading.flow", "/v1/oracle/sol/state", "reading_domains.flow.status", "STATUS_DOT"
    ),
    "sol.reading.volatility": SurfaceFieldMetadata(
        "sol.reading.volatility", "/v1/oracle/sol/state", "reading_domains.volatility.status", "STATUS_DOT"
    ),
    "sol.reading.external": SurfaceFieldMetadata(
        "sol.reading.external", "/v1/oracle/sol/state", "reading_domains.external.status", "STATUS_DOT"
    ),
    "sol.events.pending_count": SurfaceFieldMetadata(
        "sol.events.pending_count", "/v1/oracle/sol/state", "health_strip.pending_events_count", "INTEGER"
    ),
    "market.spot.ltp": SurfaceFieldMetadata(
        "market.spot.ltp", "/v1/oracle/sol/state", "snapshot.spot_ltp", "PRICE_2",
        "snapshot.availability_matrix.spot_ltp"
    ),
    "market.future.basis": SurfaceFieldMetadata(
        "market.future.basis", "/v1/oracle/sol/state", "snapshot.futures_basis", "SIGNED_2",
        "snapshot.availability_matrix.futures_basis"
    ),
    "vol.atm_iv": SurfaceFieldMetadata(
        "vol.atm_iv", "/v1/oracle/sol/state", "snapshot.atm_iv", "PERCENT_1",
        "snapshot.availability_matrix.atm_iv"
    ),
    "vol.skew_25d": SurfaceFieldMetadata(
        "vol.skew_25d", "/v1/oracle/sol/state", "snapshot.skew_25d", "SIGNED_2",
        "snapshot.availability_matrix.skew_25d"
    ),
    "sol.spark.status": SurfaceFieldMetadata(
        "sol.spark.status", "/v1/oracle/sol/state", "external_context.radar.status"
    ),
    "sol.spark.last_scan": SurfaceFieldMetadata(
        "sol.spark.last_scan", "/v1/oracle/sol/state", "external_context.radar.last_scan_ist"
    ),
    "obi.ce.fair_price": SurfaceFieldMetadata("obi.ce.fair_price", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.fair_price", "PRICE_2"),
    "obi.pe.fair_price": SurfaceFieldMetadata("obi.pe.fair_price", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.fair_price", "PRICE_2"),
    "obi.straddle.price": SurfaceFieldMetadata("obi.straddle.price", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.straddle.now", "PRICE_2"),
    "expected_move_pts": SurfaceFieldMetadata("expected_move_pts", "/v1/oracle/sol/state", "snapshot.expected_move_pts"),
    "obi.ce.time_lost_today": SurfaceFieldMetadata("obi.ce.time_lost_today", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.time_lost_today", "SIGNED_MONEY_2"),
    "obi.ce.time_value_left": SurfaceFieldMetadata("obi.ce.time_value_left", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.time_value_left", "MONEY_2"),
    "obi.ce.time_loss_expected": SurfaceFieldMetadata("obi.ce.time_loss_expected", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.time_loss_expected", "SIGNED_MONEY_2"),
    "obi.ce.actual_change": SurfaceFieldMetadata("obi.ce.actual_change", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.actual_change", "SIGNED_MONEY_2"),
    "obi.ce.total_buy_quantity": SurfaceFieldMetadata("obi.ce.total_buy_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.market_pressure.total_buy_quantity", "QTY"),
    "obi.ce.total_sell_quantity": SurfaceFieldMetadata("obi.ce.total_sell_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.market_pressure.total_sell_quantity", "QTY"),
    "obi.ce.last_trade_quantity": SurfaceFieldMetadata("obi.ce.last_trade_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.market_pressure.last_trade_quantity", "QTY"),
    "obi.ce.average_trade_price": SurfaceFieldMetadata("obi.ce.average_trade_price", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.market_pressure.average_trade_price", "MONEY_2"),
    "obi.ce.ask": SurfaceFieldMetadata("obi.ce.ask", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.ask", "MONEY_2"),
    "obi.ce.bid": SurfaceFieldMetadata("obi.ce.bid", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.bid", "MONEY_2"),
    "obi.ce.spread": SurfaceFieldMetadata("obi.ce.spread", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.spread", "MONEY_2"),
    "obi.ce.best_bid": SurfaceFieldMetadata("obi.ce.best_bid", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.best_bid", "LEVEL"),
    "obi.ce.best_ask": SurfaceFieldMetadata("obi.ce.best_ask", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.best_ask", "LEVEL"),
    "obi.ce.biggest_buy_level": SurfaceFieldMetadata("obi.ce.biggest_buy_level", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.biggest_buy_level", "LEVEL"),
    "obi.ce.biggest_sell_level": SurfaceFieldMetadata("obi.ce.biggest_sell_level", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.biggest_sell_level", "LEVEL"),
    "obi.ce.five_level_buy_quantity": SurfaceFieldMetadata("obi.ce.five_level_buy_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.five_level_buy_quantity", "QTY"),
    "obi.ce.five_level_sell_quantity": SurfaceFieldMetadata("obi.ce.five_level_sell_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.CE.book.five_level_sell_quantity", "QTY"),
    "obi.pe.time_lost_today": SurfaceFieldMetadata("obi.pe.time_lost_today", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.time_lost_today", "SIGNED_MONEY_2"),
    "obi.pe.time_value_left": SurfaceFieldMetadata("obi.pe.time_value_left", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.time_value_left", "MONEY_2"),
    "obi.pe.time_loss_expected": SurfaceFieldMetadata("obi.pe.time_loss_expected", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.time_loss_expected", "SIGNED_MONEY_2"),
    "obi.pe.actual_change": SurfaceFieldMetadata("obi.pe.actual_change", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.actual_change", "SIGNED_MONEY_2"),
    "obi.pe.total_buy_quantity": SurfaceFieldMetadata("obi.pe.total_buy_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.market_pressure.total_buy_quantity", "QTY"),
    "obi.pe.total_sell_quantity": SurfaceFieldMetadata("obi.pe.total_sell_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.market_pressure.total_sell_quantity", "QTY"),
    "obi.pe.last_trade_quantity": SurfaceFieldMetadata("obi.pe.last_trade_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.market_pressure.last_trade_quantity", "QTY"),
    "obi.pe.average_trade_price": SurfaceFieldMetadata("obi.pe.average_trade_price", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.market_pressure.average_trade_price", "MONEY_2"),
    "obi.pe.ask": SurfaceFieldMetadata("obi.pe.ask", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.ask", "MONEY_2"),
    "obi.pe.bid": SurfaceFieldMetadata("obi.pe.bid", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.bid", "MONEY_2"),
    "obi.pe.spread": SurfaceFieldMetadata("obi.pe.spread", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.spread", "MONEY_2"),
    "obi.pe.best_bid": SurfaceFieldMetadata("obi.pe.best_bid", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.best_bid", "LEVEL"),
    "obi.pe.best_ask": SurfaceFieldMetadata("obi.pe.best_ask", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.best_ask", "LEVEL"),
    "obi.pe.biggest_buy_level": SurfaceFieldMetadata("obi.pe.biggest_buy_level", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.biggest_buy_level", "LEVEL"),
    "obi.pe.biggest_sell_level": SurfaceFieldMetadata("obi.pe.biggest_sell_level", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.biggest_sell_level", "LEVEL"),
    "obi.pe.five_level_buy_quantity": SurfaceFieldMetadata("obi.pe.five_level_buy_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.five_level_buy_quantity", "QTY"),
    "obi.pe.five_level_sell_quantity": SurfaceFieldMetadata("obi.pe.five_level_sell_quantity", "/v1/oracle/fast-lane", "feeds.option_buyer_intelligence.data.PE.book.five_level_sell_quantity", "QTY"),
}

# Allowlisted nested keys inside strike_ladder elements
STRIKE_LADDER_ALLOWED_KEYS: Set[str] = {
    "strike",
    "relation_to_atm",
    "ce_security_id",
    "ce_ltp",
    "ce_fair_gap_pct",
    "ce_closed_5m_oi",
    "ce_closed_15m_oi",
    "ce_structure",
    "pe_security_id",
    "pe_ltp",
    "pe_fair_gap_pct",
    "pe_closed_5m_oi",
    "pe_closed_15m_oi",
    "pe_structure",
}

# Allowlisted keys inside contract pricing dictionaries (ce_pricing / pe_pricing)
CONTRACT_PRICING_ALLOWED_KEYS: Set[str] = {
    "security_id",
    "strike",
    "option_type",
    "expiry",
    "ltp",
    "best_bid_price",
    "best_ask_price",
    "spread",
    "iv",
    "fair_iv",
    "fair_price",
    "fair_gap_pct",
    "time_value",
    "holding_decay_per_min",
    "depth_levels",
    "depth_imbalance",
    "source_timestamp",
}
