"""Centralized, advisory-only configuration for ARGUS Tactical Edge."""

from __future__ import annotations


SCHEMA_VERSION = 2
HISTORY_LIMIT = 1200
ATM_BREADTH_STRIKES = 7

PRESSURE_WEIGHTS = {
    "open_interest": 0.20,
    "previous_oi_change": 0.15,
    "intraday_oi_change": 0.20,
    "premium_change": 0.15,
    "volume": 0.10,
    "bid_ask": 0.10,
    "iv_quality": 0.05,
    "spot_confirmation": 0.05,
}

PRESSURE_BALANCED_DELTA = 7.0
PRESSURE_DIRECTIONAL_DELTA = 18.0
BREADTH_CONFIRMATION_SCORE = 55.0
HIGH_CONVICTION_EVIDENCE_QUALITY = 70.0

REGIME_BALANCED_LIMIT = 35.0
REGIME_EXIT_LIMIT = 15.0
REGIME_CONFIRMATION_SNAPSHOTS = 3
REGIME_CONFIRMATION_SECONDS = 10.0
EXTREME_BREAK_PRESSURE_DELTA = 30.0
EXTREME_BREAK_BREADTH_CONFIRMATIONS = 5

REGIME_WEIGHTS = {
    "pressure_context": 10.0,
    "breadth": 25.0,
    "ose_structure": 40.0,
    "persistence": 25.0,
}

DATA_QUALITY_WEIGHTS = {
    "coverage": 0.55,
    "freshness": 0.25,
    "completeness": 0.20,
}

SETUP_CLASSES = (
    "STANDARD_DIRECTIONAL",
    "HIGH_CONVICTION",
    "GAMMA_BLAST",
)

ENTRY_STATES = (
    "CONTEXT",
    "WAIT",
    "ESCAPE",
    "ACCEPTANCE",
    "RETEST",
    "REJECTION",
    "RESUMPTION",
    "READY",
    "INVALIDATED",
)

GAMMA_UNAVAILABLE_REASON = "AUTHORITATIVE_DIRECT_GREEKS_UNAVAILABLE"
