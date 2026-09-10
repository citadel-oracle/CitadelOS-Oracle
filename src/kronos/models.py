from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class KronosScores:
    bull_score: int = 0
    bear_score: int = 0
    neutral_score: int = 0
    trend_score: int = 0
    momentum_score: int = 0
    volatility_score: int = 0
    reasons: List[str] = field(default_factory=list)


@dataclass
class KronosResult:
    regime: str
    bias: str
    trade_mode: str
    risk_mode: str
    confidence: int
    allow_trade: bool
    bull_probability: int
    bear_probability: int
    neutral_probability: int
    scores: Dict
    reason: str