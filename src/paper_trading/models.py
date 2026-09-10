"""Typed paper-only runtime contracts."""

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolvedOptionContract:
    security_id: str
    exchange_segment: str
    underlying: str
    option_type: str
    strike: float
    expiry: str
    lot_size: int
    ltp: float
    top_ask_price: Optional[float]
    top_ask_quantity: Optional[int]
    top_bid_price: Optional[float]
    top_bid_quantity: Optional[int]
    instrument_source: str
    quote_source: str

    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class PaperRiskDecision:
    decision: str
    reason_code: str
    reason: str
    request_id: str
    quantity: int
    lot_size: int
    number_of_lots: int
    maximum_loss: float
    limits: dict
    timestamp: str
    live_trading_enabled: bool = False
    broker_authorization: bool = False

    @property
    def allowed(self): return self.decision == "ALLOW"
    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class SimulatedFill:
    fill_id: str
    intent_id: str
    timestamp: str
    quantity: int
    price: float
    reference_price: float
    reference_source: str
    fill_model: str
    partial: bool
    paper_only: bool = True
    broker_submission: bool = False

    def to_dict(self): return asdict(self)
