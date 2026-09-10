"""Fail-closed shared Strategy Lab risk infrastructure.

No sizing, strategy rules, execution decisions or production Risk formulas are
implemented here.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ._state import encode_state, write_state


@dataclass(frozen=True)
class SharedRiskPolicy:
    capital_allocation: float
    risk_allocation: float
    daily_loss_limit: float
    max_concurrent_trades: int
    currency: str = "INR"

    def __post_init__(self) -> None:
        if self.capital_allocation <= 0:
            raise ValueError("capital_allocation must be positive")
        if self.risk_allocation < 0 or self.daily_loss_limit < 0:
            raise ValueError("risk limits cannot be negative")
        if self.max_concurrent_trades < 1:
            raise ValueError("max_concurrent_trades must be positive")


@dataclass
class SharedRiskState:
    allocated_capital: float = 0.0
    allocated_risk: float = 0.0
    daily_realized_pnl: float = 0.0
    concurrent_trades: int = 0


@dataclass(frozen=True)
class SharedRiskDecision:
    authorized: bool
    reason: str


class SharedRiskEngine:
    SCHEMA_VERSION = 1

    def __init__(self, policy: Optional[SharedRiskPolicy] = None) -> None:
        self.policy = policy
        self.state = SharedRiskState()

    def evaluate(self, *, requested_capital: float, requested_risk: float) -> SharedRiskDecision:
        if self.policy is None:
            return SharedRiskDecision(False, "RISK_CONFIGURATION_ABSENT")
        if requested_capital < 0 or requested_risk < 0:
            return SharedRiskDecision(False, "INVALID_RISK_REQUEST")
        if self.state.concurrent_trades >= self.policy.max_concurrent_trades:
            return SharedRiskDecision(False, "MAX_CONCURRENT_TRADES")
        if -self.state.daily_realized_pnl >= self.policy.daily_loss_limit:
            return SharedRiskDecision(False, "DAILY_LOSS_LIMIT")
        if self.state.allocated_capital + requested_capital > self.policy.capital_allocation:
            return SharedRiskDecision(False, "CAPITAL_ALLOCATION")
        if self.state.allocated_risk + requested_risk > self.policy.risk_allocation:
            return SharedRiskDecision(False, "RISK_ALLOCATION")
        return SharedRiskDecision(True, "AUTHORIZED")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "policy": None if self.policy is None else asdict(self.policy),
            "state": asdict(self.state),
        }

    def serialize(self) -> str:
        return encode_state(self.snapshot())

    @classmethod
    def deserialize(cls, payload: str) -> "SharedRiskEngine":
        value = json.loads(payload)
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported shared risk state schema")
        policy_value = value.get("policy")
        engine = cls(None if policy_value is None else SharedRiskPolicy(**policy_value))
        engine.state = SharedRiskState(**value.get("state", {}))
        return engine

    def save(self, path: Path) -> None:
        write_state(path, self.serialize())

    @classmethod
    def load(cls, path: Path) -> "SharedRiskEngine":
        return cls.deserialize(Path(path).read_text(encoding="utf-8"))
