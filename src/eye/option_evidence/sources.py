"""Source Classifications & Provenance Contracts for Eye Engine Phase E4A Option Evidence."""

from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class SourceType(str, Enum):
    DHAN_INSTRUMENT_MASTER = "DHAN_INSTRUMENT_MASTER"
    DHAN_OPTION_CHAIN = "DHAN_OPTION_CHAIN"
    DHAN_MARKET_QUOTE = "DHAN_MARKET_QUOTE"
    DHAN_WEBSOCKET_TICKER = "DHAN_WEBSOCKET_TICKER"
    DHAN_WEBSOCKET_QUOTE = "DHAN_WEBSOCKET_QUOTE"
    DHAN_WEBSOCKET_FULL = "DHAN_WEBSOCKET_FULL"
    DHAN_FULL_MARKET_DEPTH = "DHAN_FULL_MARKET_DEPTH"
    DHAN_EXACT_INTRADAY_HISTORY = "DHAN_EXACT_INTRADAY_HISTORY"
    DHAN_ROLLING_EXPIRED_OPTIONS = "DHAN_ROLLING_EXPIRED_OPTIONS"
    LOCAL_EXACT_CONTRACT_HISTORY = "LOCAL_EXACT_CONTRACT_HISTORY"
    NSE_REFERENCE_METADATA = "NSE_REFERENCE_METADATA"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    LIVE_MUTABLE_SOURCE = "LIVE_MUTABLE_SOURCE"
    IMMUTABLE_SNAPSHOT_SOURCE = "IMMUTABLE_SNAPSHOT_SOURCE"


class DataClassification(str, Enum):
    EXACT_OPTION_QUOTE = "EXACT_OPTION_QUOTE"
    EXACT_OPTION_TICK = "EXACT_OPTION_TICK"
    EXACT_OPTION_CANDLE = "EXACT_OPTION_CANDLE"
    OPTION_CHAIN_SNAPSHOT = "OPTION_CHAIN_SNAPSHOT"
    ROLLING_MONEYNESS_PROXY = "ROLLING_MONEYNESS_PROXY"
    UNDERLYING_SPOT_CANDLE = "UNDERLYING_SPOT_CANDLE"
    INSTRUMENT_MASTER_METADATA = "INSTRUMENT_MASTER_METADATA"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    UNSAFE_OR_AMBIGUOUS = "UNSAFE_OR_AMBIGUOUS"
    SEALED_HOLDOUT = "SEALED_HOLDOUT"

    # Backward compatibility aliases
    EXACT_CONTRACT_TICK = "EXACT_OPTION_TICK"
    EXACT_CONTRACT_QUOTE = "EXACT_OPTION_QUOTE"
    EXACT_CONTRACT_CANDLE = "EXACT_OPTION_CANDLE"


@dataclass(frozen=True)
class SourceProvenance:
    source_type: SourceType
    data_classification: DataClassification
    source_version: str = "1.0.0"
    source_sequence: Optional[int] = None
    source_timestamp: Optional[datetime] = None
    exchange_timestamp: Optional[datetime] = None
    received_at: Optional[datetime] = None
    parsed_at: Optional[datetime] = None
    source_revision: int = 1
    raw_fingerprint: str = ""
