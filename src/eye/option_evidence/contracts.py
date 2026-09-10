"""Core Data Structures & Data Models for Eye Engine Phase E4A Option Evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Sequence, Dict, Any
from src.eye.contracts import PriceAtom, InstrumentIdentity, AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance


class QuoteState(str, Enum):
    TWO_SIDED_VALID = "TWO_SIDED_VALID"
    LOCKED = "LOCKED"
    CROSSED = "CROSSED"
    BID_ONLY = "BID_ONLY"
    ASK_ONLY = "ASK_ONLY"
    NO_QUOTE = "NO_QUOTE"
    ZERO_BID = "ZERO_BID"
    ZERO_ASK = "ZERO_ASK"
    STALE_TWO_SIDED = "STALE_TWO_SIDED"
    INVALID_PRICE = "INVALID_PRICE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class PriceReference(str, Enum):
    LAST_TRADED_PRICE = "LAST_TRADED_PRICE"
    BEST_BID = "BEST_BID"
    BEST_ASK = "BEST_ASK"
    MIDPOINT = "MIDPOINT"
    MICROPRICE_RESEARCH = "MICROPRICE_RESEARCH"
    PREVIOUS_CLOSE = "PREVIOUS_CLOSE"
    AVERAGE_TRADED_PRICE = "AVERAGE_TRADED_PRICE"


class GreekType(str, Enum):
    DELTA = "DELTA"
    GAMMA = "GAMMA"
    THETA = "THETA"
    VEGA = "VEGA"
    RHO = "RHO"


class GreekSource(str, Enum):
    VENDOR = "VENDOR"
    EXCHANGE_REFERENCE = "EXCHANGE_REFERENCE"
    INDEPENDENT_MODEL = "INDEPENDENT_MODEL"


class MoneynessState(str, Enum):
    ITM = "ITM"
    ATM = "ATM"
    OTM = "OTM"
    UNKNOWN = "UNKNOWN"


class AlignmentState(str, Enum):
    ALIGNED = "ALIGNED"
    DIVERGENT = "DIVERGENT"
    MIXED = "MIXED"
    INDETERMINATE = "INDETERMINATE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


@dataclass(frozen=True)
class GreekObservation:
    contract_key: str
    greek_type: GreekType
    value: float
    unit: str  # e.g., "PER_RUPEE", "PER_DAY", "PER_IV_PCT"
    source: GreekSource
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    underlying_input: Optional[float] = None
    strike_input: Optional[float] = None
    rate_input: Optional[float] = None
    volatility_input: Optional[float] = None
    time_to_expiry_input: Optional[float] = None
    price_reference_used: Optional[PriceReference] = None
    calculated_at: Optional[datetime] = None
    available_at: Optional[datetime] = None
    validity_state: str = "VALID"
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ImpliedVolatilityObservation:
    contract_key: str
    source: SourceType
    value: float  # e.g., 0.155 for 15.5%
    unit: str = "PERCENTAGE"
    price_reference: PriceReference = PriceReference.MIDPOINT
    underlying_reference: Optional[float] = None
    interest_rate_reference: Optional[float] = None
    time_to_expiry_convention: str = "ACT_365"
    model_id: Optional[str] = None
    calculated_at: Optional[datetime] = None
    available_at: Optional[datetime] = None
    validity_state: str = "VALID"
    solver_status: str = "SUCCESS"
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class OptionMarketObservation:
    observation_id: str
    contract: OptionContractIdentity
    provenance: SourceProvenance
    observed_at: datetime
    available_at: datetime
    evaluation_as_of: datetime
    received_at: datetime
    parsed_at: datetime
    exchange_timestamp: Optional[datetime] = None
    last_trade_timestamp: Optional[datetime] = None
    last_price: Optional[PriceAtom] = None
    best_bid: Optional[PriceAtom] = None
    best_ask: Optional[PriceAtom] = None
    bid_quantity: Optional[int] = None
    ask_quantity: Optional[int] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    previous_open_interest: Optional[int] = None
    average_price: Optional[PriceAtom] = None
    vendor_iv: Optional[ImpliedVolatilityObservation] = None
    vendor_greeks: Sequence[GreekObservation] = ()
    underlying_price_reference: Optional[float] = None
    quote_state: QuoteState = QuoteState.NO_QUOTE
    is_fresh: bool = True
    completeness: str = "COMPLETE"
    raw_fingerprint: str = ""
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SetupOptionEvidenceLink:
    schema_version: str
    setup_key: str
    setup_record_id: str
    setup_id: str
    setup_version: str
    setup_family: str
    underlying_symbol: str
    setup_direction: str
    setup_timeframe: str
    setup_confirmation_timestamp: datetime
    setup_availability_watermark: datetime
    contract_key: str
    option_type: str
    observation_ids: Sequence[str]
    underlying_observation_ids: Sequence[str]
    evidence_window_start: datetime
    evidence_window_end: datetime
    source_data_revision: int
    link_status: str
    availability: str
    quality_diagnostics: Dict[str, Any]
    authority: AuthorityType = AuthorityType.OBSERVATION_ONLY
    probability_status: ProbabilityStatus = ProbabilityStatus.NOT_ESTABLISHED
