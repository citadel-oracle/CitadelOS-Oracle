"""Contracts for isolated Strategy Lab deployments.

These contracts describe research runtimes only.  They do not expose a broker,
Production AEGIS, Production Risk, or either existing Paper State.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Sequence


class StrategyInputType(str, Enum):
    PINE_SCRIPT = "TRADINGVIEW_PINE_SCRIPT"
    PYTHON = "PYTHON_STRATEGY"
    MANUAL_RULES = "MANUAL_RULE_STRATEGY"
    JSON_CONFIG = "JSON_CONFIGURATION"
    GIT_REPOSITORY = "GIT_REPOSITORY"
    ZIP_PACKAGE = "ZIP_PACKAGE"
    AI_GENERATED = "AI_GENERATED_STRATEGY"


class StrategyAdapter(Protocol):
    """A future strategy compiler must produce this narrow adapter."""

    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class PaperExecutionPort(Protocol):
    """Isolated paper-only execution port owned by one research runtime."""

    def process(
        self,
        *,
        evaluation: Mapping[str, Any],
        context: Mapping[str, Any],
        workspace: Any,
    ) -> Mapping[str, Any]:
        ...


class OptionResolutionPort(Protocol):
    """Authoritative option resolver used before the paper OMS boundary."""

    def resolve(self, argus_response: Mapping[str, Any], signal: str, **configuration: Any) -> Any:
        ...

    def quote_existing(self, argus_response: Mapping[str, Any], contract: str) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    name: str
    version: str
    author: str
    input_type: StrategyInputType
    supported_markets: Sequence[str]
    supported_timeframes: Sequence[str]
    rr: Optional[float]
    risk_model: str
    status: str = "REGISTERED"
    deployment_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    parameters: Mapping[str, Any] = field(default_factory=dict)
    source_reference: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.strategy_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("strategy_id must contain only letters, numbers, hyphens, or underscores")
        if not self.name.strip() or not self.version.strip() or not self.author.strip():
            raise ValueError("strategy name, version, and author are required")
        if not self.supported_markets or not self.supported_timeframes:
            raise ValueError("at least one market and timeframe are required")

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["input_type"] = self.input_type.value
        value["supported_markets"] = [str(item).upper() for item in self.supported_markets]
        value["supported_timeframes"] = [str(item) for item in self.supported_timeframes]
        value["parameters"] = dict(self.parameters)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrategyMetadata":
        return cls(
            strategy_id=str(value["strategy_id"]),
            name=str(value["name"]),
            version=str(value["version"]),
            author=str(value["author"]),
            input_type=StrategyInputType(str(value["input_type"])),
            supported_markets=list(value.get("supported_markets") or []),
            supported_timeframes=list(value.get("supported_timeframes") or []),
            rr=float(value["rr"]) if value.get("rr") is not None else None,
            risk_model=str(value.get("risk_model") or "UNSPECIFIED"),
            status=str(value.get("status") or "REGISTERED"),
            deployment_date=str(value.get("deployment_date") or datetime.now(timezone.utc).isoformat()),
            parameters=dict(value.get("parameters") or {}),
            source_reference=value.get("source_reference"),
        )


@dataclass(frozen=True)
class DeploymentRequest:
    metadata: StrategyMetadata
    adapter: StrategyAdapter
    context_provider: Callable[[], Mapping[str, Any]]
    execution: Optional[PaperExecutionPort] = None
    option_resolver: Optional[OptionResolutionPort] = None
    scheduler_interval_seconds: float = 5.0
    activation_enabled: bool = True
    activation_reason: Optional[str] = None


def deployment_capabilities() -> Dict[str, Any]:
    """Truthful adapter surface: architecture exists; parsers do not."""

    adapters = []
    for input_type in StrategyInputType:
        adapters.append(
            {
                "input_type": input_type.value,
                "deployment_interface": "READY",
                "compiler_or_parser": (
                    "ADAPTER_INJECTION_READY"
                    if input_type == StrategyInputType.PYTHON
                    else "NOT_IMPLEMENTED"
                ),
            }
        )
    return {
        "status": "ARCHITECTURE_READY",
        "adapters": adapters,
        "pine_parser_implemented": False,
        "automatic_strategy_generation": False,
        "broker_execution_supported": False,
        "paper_only": True,
    }
