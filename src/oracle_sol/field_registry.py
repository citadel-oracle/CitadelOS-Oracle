"""Comprehensive VOB-Free Sensorium Field Registry & Lineage Catalog (P0.3 Hardened).

Authoritative registry of all 33 canonical VOB-free market features produced by CITADEL,
organized across 7 typed domains with exact ownership, lineage, and schema types.
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


# The authoritative registry of all 33 verified VOB-free canonical fields
SOL_VOB_FREE_FIELD_REGISTRY: Dict[str, FieldMetadata] = {
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
