"""Typed contracts for the CITADEL Strategies command plane."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class DeploymentPath(str, Enum):
    WORKSPACE_OBSERVE = "WORKSPACE_OBSERVE"
    SIMPLE_SIGNAL_ONLY = "SIMPLE_SIGNAL_ONLY"
    SIMPLE_PAPER = "SIMPLE_PAPER"
    ORACLE_SHADOW = "ORACLE_SHADOW"
    ORACLE_PAPER = "ORACLE_PAPER"
    REPLAY = "REPLAY"
    BACKTEST = "BACKTEST"
    ORACLE_DEVELOPMENT_REFERENCE = "ORACLE_DEVELOPMENT_REFERENCE"
    LIVE_DISABLED = "LIVE_DISABLED"


class AggregationMode(str, Enum):
    ANY = "ANY"
    ALL = "ALL"
    MAJORITY = "MAJORITY"
    WEIGHTED = "WEIGHTED"
    PRIMARY_PLUS_CONFIRMATION = "PRIMARY_PLUS_CONFIRMATION"
    HIGHEST_TIMEFRAME_PRIORITY = "HIGHEST_TIMEFRAME_PRIORITY"


class ConflictPolicy(str, Enum):
    INDEPENDENT_EXECUTION = "INDEPENDENT_EXECUTION"
    ONE_TRADE_PER_INSTRUMENT = "ONE_TRADE_PER_INSTRUMENT"
    ONE_TRADE_PER_STRATEGY = "ONE_TRADE_PER_STRATEGY"
    HIGHEST_SCORE_WINS = "HIGHEST_SCORE_WINS"
    HIGHEST_PRIORITY_WINS = "HIGHEST_PRIORITY_WINS"
    EARLIEST_SIGNAL_WINS = "EARLIEST_SIGNAL_WINS"
    REQUIRE_AGREEMENT = "REQUIRE_AGREEMENT"
    BLOCK_OPPOSING_DIRECTION = "BLOCK_OPPOSING_DIRECTION"
    USER_DEFINED_CAPITAL_ALLOCATION = "USER_DEFINED_CAPITAL_ALLOCATION"


class RuntimeState(str, Enum):
    DRAFT = "DRAFT"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    OBSERVING = "OBSERVING"
    WAITING_FOR_DATA = "WAITING_FOR_DATA"
    WAITING_FOR_TRIGGER = "WAITING_FOR_TRIGGER"
    SIGNAL_READY = "SIGNAL_READY"
    CONTRACT_SELECTION = "CONTRACT_SELECTION"
    MISSION_READY = "MISSION_READY"
    ORDER_WORKING = "ORDER_WORKING"
    MISSION_ACTIVE = "MISSION_ACTIVE"
    POSITION_ACTIVE = "POSITION_ACTIVE"
    GUARDIAN_ACTIVE = "GUARDIAN_ACTIVE"
    EXITED = "EXITED"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class PrimeDependencyMode(str, Enum):
    PRIME_INDEPENDENT = "PRIME_INDEPENDENT"
    PRIME_ASSISTED = "PRIME_ASSISTED"
    PRIME_REQUIRED = "PRIME_REQUIRED"


class CandidateState(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    NO_SETUP = "NO_SETUP"
    NEAR_TRIGGER = "NEAR_TRIGGER"
    CANDIDATE = "CANDIDATE"
    BLOCKED_DATA = "BLOCKED_DATA"
    BLOCKED_CONTRACT = "BLOCKED_CONTRACT"
    BLOCKED_ENTRY = "BLOCKED_ENTRY"
    BLOCKED_RISK = "BLOCKED_RISK"
    BLOCKED_PRIME = "BLOCKED_PRIME"
    SHADOW_SIGNAL = "SHADOW_SIGNAL"


class PrimeRelationship(str, Enum):
    ALIGNED = "ALIGNED"
    CONFLICTED = "CONFLICTED"
    HOLD = "HOLD"
    NOT_AVAILABLE = "NOT_AVAILABLE"


INTELLIGENCE_MODES = (
    "IGNORE",
    "DISPLAY_ONLY",
    "CONFIDENCE_MODIFIER",
    "CONTRACT_PREFERENCE",
    "ENTRY_WARNING",
    "GUARDIAN_ADVISORY",
    "HARD_REQUIREMENT",
)

TIMEFRAME_ROLES = (
    "entry",
    "signal",
    "price_action",
    "vob",
    "context",
    "confirmation",
    "regime",
    "guardian",
    "exit",
)


@dataclass(frozen=True)
class StrategyContract:
    strategy_id: str
    name: str
    version: str
    family: str
    description: str
    supported_instruments: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    parameter_schema: Mapping[str, Any]
    default_configuration: Mapping[str, Any]
    signal_logic: str
    direction_logic: str
    invalidation_logic: str
    target_logic: str
    execution_compatibility: tuple[str, ...]
    guardian_compatibility: bool
    source_module: str

    def __post_init__(self) -> None:
        required_text = {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "family": self.family,
            "description": self.description,
            "signal_logic": self.signal_logic,
            "direction_logic": self.direction_logic,
            "invalidation_logic": self.invalidation_logic,
            "target_logic": self.target_logic,
            "source_module": self.source_module,
        }
        missing = [key for key, value in required_text.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"STRATEGY_CONTRACT_MISSING:{','.join(sorted(missing))}")
        if not self.strategy_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("STRATEGY_ID_INVALID")
        for field_name, values in (
            ("supported_instruments", self.supported_instruments),
            ("supported_timeframes", self.supported_timeframes),
            ("required_inputs", self.required_inputs),
            ("execution_compatibility", self.execution_compatibility),
        ):
            if not values:
                raise ValueError(f"STRATEGY_CONTRACT_EMPTY:{field_name}")
        invalid_paths = sorted(set(self.execution_compatibility) - {item.value for item in DeploymentPath})
        if invalid_paths:
            raise ValueError(f"STRATEGY_EXECUTION_PATH_INVALID:{','.join(invalid_paths)}")

    @property
    def version_key(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parameter_schema"] = deepcopy(dict(self.parameter_schema))
        value["default_configuration"] = deepcopy(dict(self.default_configuration))
        value["registration_state"] = "DRAFT"
        value["enabled"] = False
        return value


def canonical_configuration_hash(configuration: Mapping[str, Any]) -> str:
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(value)))


def default_configuration(contract: StrategyContract) -> dict[str, Any]:
    instruments = list(contract.supported_instruments)
    timeframes = list(contract.supported_timeframes)
    instrument = instruments[0]
    timeframe = timeframes[0]
    return {
        "schema_version": 1,
        "strategy_id": contract.strategy_id,
        "strategy_version": contract.version,
        "market": {
            "instrument": instrument,
            "segment": "NSE_INDEX_OPTIONS",
            "expiry_type": "WEEKLY",
            "expiry_date": None,
            "dte": None,
            "option_sides": ["CALL", "PUT"],
            "moneyness": "ATM",
            "strike_offset": 0,
            "delta_range": [None, None],
            "premium_range": [None, None],
            "minimum_oi": None,
            "minimum_volume": None,
            "maximum_spread": None,
            "liquidity_rules": [],
        },
        "timeframes": {
            "roles": {role: [timeframe] for role in TIMEFRAME_ROLES},
            "aggregation": AggregationMode.PRIMARY_PLUS_CONFIRMATION.value,
            "weights": {},
            "stale_data_threshold_seconds": 20,
        },
        "position": {
            "fixed_lots": 1,
            "maximum_lots": 1,
            "capital": 100000,
            "fixed_rupee_risk": 500,
            "capital_percentage_risk": None,
            "premium_budget": None,
            "maximum_open_positions": 1,
            "maximum_concurrent_instances": 1,
        },
        "session": {
            "first_entry_time": "09:20",
            "last_entry_time": "15:15",
            "square_off_time": "15:28",
            "cooldown_seconds": 300,
            "re_entry": False,
            "maximum_trades_per_day": 1,
            "daily_loss_limit": 500,
            "daily_profit_lock": None,
            "expiry_day_restrictions": [],
            "opening_volatility_restrictions": [],
            "custom_no_trade_windows": [],
        },
        "entry": {
            "strategy_trigger": True,
            "price_action_requirement": "REQUIRED",
            "vob_requirement": "REQUIRED",
            "breakout": False,
            "retest": False,
            "rejection": False,
            "candle_close_confirmation": True,
            "momentum_requirement": None,
            "pullback_depth": None,
            "minimum_score": 70,
            "minimum_rr": 1.5,
            "conflict_behaviour": "FAIL_CLOSED",
        },
        "exit": {
            "structural_invalidation": True,
            "premium_stop_loss": None,
            "percentage_stop_loss": None,
            "target": None,
            "trailing_stop": False,
            "breakeven": False,
            "partial_exit": False,
            "opposite_signal_exit": False,
            "vob_failure_exit": False,
            "time_exit": True,
            "session_exit": True,
            "maximum_holding_duration_seconds": None,
        },
        "guardian": {
            "enabled": True,
            "timeframe": timeframe,
            "breakeven_trigger": None,
            "trailing_policy": "DISABLED",
            "partial_exit_policy": "DISABLED",
            "risk_reduction": True,
            "invalidation_response": "EXIT",
            "time_based_protection": True,
            "emergency_exit": True,
            "advisory_mode": True,
            "execution_mode": "PAPER_ONLY",
        },
        "decision": {
            "weights": {"price_action": 50, "vob": 25, "strategy_trigger": 25},
            "intelligence": {
                key: "DISPLAY_ONLY"
                for key in ("argus", "ose", "gamma", "oi", "pressure", "breadth", "iv")
            },
        },
        "conflict": {
            "policy": ConflictPolicy.ONE_TRADE_PER_INSTRUMENT.value,
            "priority": 100,
            "capital_allocation": None,
        },
        "execution": {
            "path": DeploymentPath.WORKSPACE_OBSERVE.value,
            "enabled": False,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "advisory_only": True,
        },
        "strategy_parameters": deepcopy(dict(contract.default_configuration)),
    }


def validate_configuration(configuration: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(configuration))
    required_sections = {
        "market", "timeframes", "position", "session", "entry", "exit",
        "guardian", "decision", "conflict", "execution",
    }
    missing = sorted(required_sections - set(value))
    if missing:
        raise ValueError(f"CONFIGURATION_SECTIONS_MISSING:{','.join(missing)}")
    execution = value["execution"]
    path = DeploymentPath(str(execution.get("path")))
    if execution.get("paper_only") is not True:
        raise ValueError("PAPER_ONLY_REQUIRED")
    if execution.get("live_trading_enabled") is not False:
        raise ValueError("LIVE_TRADING_MUST_REMAIN_DISABLED")
    if execution.get("broker_submission") is not False:
        raise ValueError("BROKER_SUBMISSION_MUST_REMAIN_DISABLED")
    if path is DeploymentPath.LIVE_DISABLED and execution.get("enabled") is True:
        raise ValueError("LIVE_DISABLED_CANNOT_BE_ENABLED")
    position = value["position"]
    for key in ("fixed_lots", "maximum_lots", "maximum_open_positions", "maximum_concurrent_instances"):
        item = position.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"CONFIGURATION_POSITIVE_INTEGER_REQUIRED:{key}")
    if position["fixed_lots"] > position["maximum_lots"]:
        raise ValueError("FIXED_LOTS_EXCEEDS_MAXIMUM")
    weights = value["decision"].get("weights") or {}
    if set(weights) != {"price_action", "vob", "strategy_trigger"}:
        raise ValueError("DECISION_WEIGHT_KEYS_INVALID")
    if sum(weights.values()) != 100 or any(isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0 for item in weights.values()):
        raise ValueError("DECISION_WEIGHTS_MUST_TOTAL_100")
    for mode in (value["decision"].get("intelligence") or {}).values():
        if mode not in INTELLIGENCE_MODES:
            raise ValueError(f"INTELLIGENCE_MODE_INVALID:{mode}")
    AggregationMode(str(value["timeframes"].get("aggregation")))
    ConflictPolicy(str(value["conflict"].get("policy")))
    roles = value["timeframes"].get("roles")
    if not isinstance(roles, dict) or any(role not in roles or not isinstance(roles[role], list) or not roles[role] for role in TIMEFRAME_ROLES):
        raise ValueError("TIMEFRAME_ROLES_INCOMPLETE")
    return value


def aggregate_timeframe_votes(
    votes: Mapping[str, str],
    mode: AggregationMode,
    *,
    weights: Mapping[str, float] | None = None,
    primary: str | None = None,
    required_timeframes: Sequence[str] | None = None,
    stale_timeframes: Sequence[str] | None = None,
) -> dict[str, Any]:
    normalized = {str(key): str(value).upper() for key, value in sorted(votes.items())}
    allowed = {"BULLISH", "BEARISH", "NEUTRAL"}
    required = tuple(sorted({str(item) for item in (required_timeframes or ())}))
    stale = tuple(sorted({str(item) for item in (stale_timeframes or ())}))
    missing = tuple(item for item in required if item not in normalized)
    if missing or stale:
        return {
            "mode": mode.value,
            "votes": normalized,
            "consensus": "UNAVAILABLE",
            "missing_timeframes": list(missing),
            "stale_timeframes": list(stale),
            "reason": "TIMEFRAME_DATA_MISSING" if missing else "TIMEFRAME_DATA_STALE",
        }
    if not normalized or set(normalized.values()) - allowed:
        raise ValueError("TIMEFRAME_VOTES_INVALID")
    bullish = sum(value == "BULLISH" for value in normalized.values())
    bearish = sum(value == "BEARISH" for value in normalized.values())
    if mode is AggregationMode.ALL:
        consensus = next(iter(set(normalized.values()))) if len(set(normalized.values())) == 1 else "CONFLICT"
    elif mode is AggregationMode.ANY:
        consensus = "BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL"
        if bullish and bearish:
            consensus = "CONFLICT"
    elif mode is AggregationMode.MAJORITY:
        consensus = "BULLISH" if bullish > len(normalized) / 2 else "BEARISH" if bearish > len(normalized) / 2 else "NEUTRAL"
    elif mode is AggregationMode.WEIGHTED:
        supplied = weights or {}
        if set(supplied) != set(normalized):
            raise ValueError("TIMEFRAME_WEIGHTS_INCOMPLETE")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
            for value in supplied.values()
        ):
            raise ValueError("TIMEFRAME_WEIGHTS_INVALID")
        score = sum(float(supplied[key]) * (1 if value == "BULLISH" else -1 if value == "BEARISH" else 0) for key, value in normalized.items())
        consensus = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
    elif mode is AggregationMode.PRIMARY_PLUS_CONFIRMATION:
        if primary not in normalized:
            raise ValueError("PRIMARY_TIMEFRAME_REQUIRED")
        confirmations = [value for key, value in normalized.items() if key != primary]
        consensus = normalized[primary] if any(value == normalized[primary] for value in confirmations) else "WAITING_CONFIRMATION"
    else:
        highest = max(normalized, key=_timeframe_seconds)
        consensus = normalized[highest]
    return {"mode": mode.value, "votes": normalized, "consensus": consensus}


def _timeframe_seconds(value: str) -> int:
    text = str(value).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if len(text) < 2 or text[-1] not in units or not text[:-1].isdigit():
        raise ValueError(f"TIMEFRAME_VALUE_INVALID:{value}")
    return int(text[:-1]) * units[text[-1]]
