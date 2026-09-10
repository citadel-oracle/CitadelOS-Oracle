"""Strict Data Contracts for Deterministic External Context Core.

Defines immutable normalized schemas for:
- ExternalEvent: Structured external news, policy, or regulatory events with cryptographic provenance.
- ExternalQuote: Global market prices (FX, commodities, equity indices, rates) with explicit EXACT vs PROXY labeling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class VerificationTier(str, Enum):
    TIER_A_OFFICIAL = "TIER_A_OFFICIAL"          # First-party government/regulator: RBI, SEBI, MoSPI
    TIER_B_FINANCIAL_NEWS = "TIER_B_FINANCIAL_NEWS"  # Institutional news: Marketaux / Bloomberg / Reuters feeds
    TIER_C_GLOBAL_RADAR = "TIER_C_GLOBAL_RADAR"      # Broad global radar: GDELT shock alerts
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class ExactOrProxy(str, Enum):
    EXACT = "EXACT"
    PROXY = "PROXY"


class DataAgeStatus(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    SESSION_LAST = "SESSION_LAST"


@dataclass(frozen=True)
class ExternalEvent:
    """An immutable, verified external event with cryptographic provenance."""

    event_id: str
    provider: str               # "rbi", "sebi", "mospi", "marketaux", "gdelt"
    source_name: str            # "Reserve Bank of India", "SEBI Press Releases", etc.
    source_url: str
    published_at: str           # ISO 8601 UTC
    retrieved_at: str           # ISO 8601 UTC
    event_type: str             # "REGULATORY_CIRCULAR", "MACRO_DATA", "FINANCIAL_NEWS", "GEOPOLITICAL_SHOCK"
    headline: str
    summary: str
    entities: List[str] = field(default_factory=list)
    country: str = "IN"         # "IN", "US", "GLOBAL", etc.
    market_tags: List[str] = field(default_factory=list)
    raw_hash: str = ""
    verification_tier: str = VerificationTier.TIER_B_FINANCIAL_NEWS.value
    freshness: str = "FRESH"    # "FRESH", "RECENT", "HISTORICAL"
    raw_artifact_ref: Optional[str] = None
    verification_status: str = "UNVERIFIED"
    verification_record: Dict[str, Any] = field(default_factory=dict)
    why_it_matters: Optional[str] = None
    category_context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        provider: str,
        source_name: str,
        source_url: str,
        published_at: str,
        event_type: str,
        headline: str,
        summary: str,
        entities: Optional[List[str]] = None,
        country: str = "IN",
        market_tags: Optional[List[str]] = None,
        verification_tier: str = VerificationTier.TIER_B_FINANCIAL_NEWS.value,
        raw_payload: Optional[str] = None,
        why_it_matters: Optional[str] = None,
        category_context: Optional[str] = None,
        verification_status: str = "UNVERIFIED",
        verification_record: Optional[Dict[str, Any]] = None,
    ) -> ExternalEvent:
        clean_headline = headline.strip()
        clean_url = source_url.strip()
        retrieved_at = datetime.now(timezone.utc).isoformat()
        
        # Deterministic event ID based on provider, published_at, and clean headline
        id_seed = f"{provider}:{published_at}:{clean_headline}:{clean_url}".encode("utf-8")
        event_id = f"ext_evt_{hashlib.sha256(id_seed).hexdigest()[:16]}"
        
        payload_seed = (raw_payload or f"{clean_headline}\n{summary}\n{clean_url}").encode("utf-8")
        raw_hash = hashlib.sha256(payload_seed).hexdigest()

        return cls(
            event_id=event_id,
            provider=provider,
            source_name=source_name,
            source_url=clean_url,
            published_at=published_at,
            retrieved_at=retrieved_at,
            event_type=event_type,
            headline=clean_headline,
            summary=summary.strip(),
            entities=entities or [],
            country=country,
            market_tags=market_tags or [],
            raw_hash=raw_hash,
            verification_tier=verification_tier,
            freshness="FRESH",
            raw_artifact_ref=None,
            verification_status=verification_status,
            verification_record=verification_record or {},
            why_it_matters=why_it_matters,
            category_context=category_context,
        )


@dataclass(frozen=True)
class ExternalQuote:
    """An immutable external market quote with explicit proxy/exact and session classification."""

    symbol: str                 # e.g. "USD/INR", "SPY", "QQQ", "TLT", "USO", "GLD", "BTC/USD"
    display_name: str           # e.g. "USD/INR", "S&P 500 (SPY)", "Nasdaq-100 (QQQ)"
    provider: str               # "twelve_data", etc.
    instrument_type: str        # "FOREX", "EQUITY_ETF", "COMMODITY_ETF", "CRYPTO", "BOND_ETF"
    exact_or_proxy: str         # "EXACT" or "PROXY"
    price: float
    change: float
    change_percent: float
    market_status: str          # "OPEN", "CLOSED", "AFTER_HOURS", "PRE_MARKET"
    provider_timestamp: str     # ISO 8601 UTC as reported by provider
    retrieved_at: str           # ISO 8601 UTC
    data_age: str               # "LIVE", "DELAYED", "SESSION_LAST"
    notes: Optional[str] = None
    cluster: str = "GLOBAL"     # "INDIA_LEAD", "US_RISK", "RATES_USD", "COMMODITIES", "ASIA", "SECONDARY"
    proxy_for: Optional[str] = None  # e.g. "FOR NASDAQ RISK", "FOR S&P RISK", "FOR USD", etc.
    raw_hash: str = ""
    verification_status: str = "UNVERIFIED"
    verification_record: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
