from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime


@dataclass
class MarketContext:

    # Basic
    symbol: str
    timestamp: datetime

    # Core Engines
    indicators: Dict[str, Any] = field(default_factory=dict)

    kronos: Dict[str, Any] = field(default_factory=dict)

    structure_v1: Dict[str, Any] = field(default_factory=dict)

    structure_v2: Dict[str, Any] = field(default_factory=dict)

    liquidity: Dict[str, Any] = field(default_factory=dict)

    fvg: Dict[str, Any] = field(default_factory=dict)

    order_block: Dict[str, Any] = field(default_factory=dict)

    timeframe: Dict[str, Any] = field(default_factory=dict)

    # Brain Scores
    smart_score: float = 0.0

    confidence: float = 0.0

    regime: str = "UNKNOWN"

    # Oracle Features
    features: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)