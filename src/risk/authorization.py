"""Central fail-closed authorization for every Dhan broker mutation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from src.execution.paper_state import (
    DuplicatePaperEvent,
    PaperStateService,
    PaperStateUnavailable,
)


IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReasonCode(str, Enum):
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    KILL_SWITCH_UNKNOWN = "KILL_SWITCH_UNKNOWN"
    KILL_SWITCH_CORRUPT = "KILL_SWITCH_CORRUPT"
    LIVE_TRADING_DISABLED = "LIVE_TRADING_DISABLED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_STOP = "INVALID_STOP"
    INVALID_RISK = "INVALID_RISK"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
    MAX_TRADES_REACHED = "MAX_TRADES_REACHED"
    MAX_CONSECUTIVE_LOSSES_REACHED = "MAX_CONSECUTIVE_LOSSES_REACHED"
    PER_TRADE_RISK_EXCEEDED = "PER_TRADE_RISK_EXCEEDED"
    MAX_POSITION_SIZE_EXCEEDED = "MAX_POSITION_SIZE_EXCEEDED"
    MAX_OPEN_POSITIONS_REACHED = "MAX_OPEN_POSITIONS_REACHED"
    VOLATILITY_LIMIT_EXCEEDED = "VOLATILITY_LIMIT_EXCEEDED"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    STATE_UNAVAILABLE = "STATE_UNAVAILABLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ALLOWED = "ALLOWED"
    PAPER_ONLY_REQUIRED = "PAPER_ONLY_REQUIRED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"


class RiskConfigurationError(ValueError):
    """Raised when required risk limits cannot be loaded safely."""


class RiskStateUnavailable(RuntimeError):
    """Raised when persisted risk state is missing or malformed."""


@dataclass(frozen=True)
class RiskLimits:
    live_trading_enabled: bool
    max_daily_loss: float
    max_trades_per_day: int
    max_consecutive_losses: int
    max_risk_per_trade: float
    max_position_quantity: int
    max_open_positions: int
    max_market_data_age_seconds: float
    max_volatility: Optional[float]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RiskLimits":
        if not isinstance(raw, Mapping):
            raise RiskConfigurationError("Risk settings must be a mapping")
        if type(raw.get("live_trading_enabled")) is not bool:
            raise RiskConfigurationError("live_trading_enabled must be boolean")

        return cls(
            live_trading_enabled=raw["live_trading_enabled"],
            max_daily_loss=_positive_float(raw, "max_daily_loss"),
            max_trades_per_day=_positive_int(raw, "max_trades_per_day"),
            max_consecutive_losses=_positive_int(
                raw, "max_consecutive_losses"
            ),
            max_risk_per_trade=_positive_float(raw, "max_risk_per_trade"),
            max_position_quantity=_positive_int(
                raw, "max_position_quantity"
            ),
            max_open_positions=_positive_int(raw, "max_open_positions"),
            max_market_data_age_seconds=_positive_float(
                raw, "max_market_data_age_seconds"
            ),
            max_volatility=_optional_positive_float(raw, "max_volatility"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: str
    timestamp: str
    actor: str


@dataclass(frozen=True)
class KillSwitchProjection:
    enabled: bool
    state: str
    reason: str
    activated_at: Optional[str]
    deactivated_at: Optional[str]
    updated_at: Optional[str]
    source: str
    schema_version: int
    persistence_health: str
    last_valid_state: Optional[str]
    warnings: tuple[str, ...]

    @property
    def active(self) -> Optional[bool]:
        return True if self.state == "ACTIVE" else False if self.state == "INACTIVE" else None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


@dataclass(frozen=True)
class RiskAuthorizationRequest:
    operation: str
    method: str
    endpoint: str
    request_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    stop_price: Optional[float] = None
    market_data_timestamp: Optional[datetime] = None
    volatility: Optional[float] = None

    @classmethod
    def from_broker_mutation(
        cls,
        method: str,
        endpoint: str,
        payload: Optional[Mapping[str, Any]] = None,
        risk_context: Optional[Mapping[str, Any]] = None,
    ) -> "RiskAuthorizationRequest":
        body = payload if isinstance(payload, Mapping) else {}
        context = risk_context if isinstance(risk_context, Mapping) else {}
        normalized_method = str(method).upper()
        normalized_endpoint = str(endpoint)

        if normalized_method == "POST" and normalized_endpoint == "/orders":
            operation = "PLACE"
        elif normalized_endpoint.endswith("/cancel") or normalized_method == "DELETE":
            operation = "CANCEL"
        elif normalized_method in {"PUT", "PATCH"}:
            operation = "MODIFY"
        else:
            operation = "UNKNOWN"

        return cls(
            operation=operation,
            method=normalized_method,
            endpoint=normalized_endpoint,
            request_id=_first(context, "request_id", "requestId"),
            symbol=_first(
                context,
                "symbol",
            )
            or _first(body, "tradingSymbol", "securityId"),
            side=_first(context, "side")
            or _first(body, "transactionType", "side"),
            quantity=_number_or_none(_first(body, "quantity")),
            price=_number_or_none(_first(body, "price")),
            stop_price=_number_or_none(
                _first(context, "stop_price", "stopPrice")
                or _first(body, "triggerPrice", "stopLoss", "stop_price")
            ),
            market_data_timestamp=_datetime_or_none(
                _first(
                    context,
                    "market_data_timestamp",
                    "marketDataTimestamp",
                )
            ),
            volatility=_number_or_none(_first(context, "volatility")),
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "method": self.method,
            "endpoint": self.endpoint,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class AuthorizationDecision:
    decision: str
    reason_code: str
    reason: str
    calculated_risk: dict[str, Any]
    active_limits: dict[str, Any]
    timestamp: str
    request_id: Optional[str]
    kill_switch_active: Optional[bool]

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExactPaperAuthorizationRequest:
    """Exact, narrow Phase-5 request. It cannot describe a broker mutation."""

    request_id: str
    condition_id: str
    condition_hash: str
    decision_id: str
    decision_hash: str
    revalidation_id: str
    revalidation_hash: str
    paper_order_request_id: str
    paper_order_request_hash: str
    symbol: str
    instrument_id: str
    side: str
    quantity: int
    executable_price_low: float
    executable_price_high: float
    price: float
    stop_price: float
    estimated_maximum_loss: float
    market_data_timestamp: datetime
    expires_at: datetime
    idempotency_key: str
    paper_only: bool = True
    live_trading_enabled: bool = False
    broker_submission: bool = False
    advisory_only: bool = True

    def __post_init__(self) -> None:
        required = (
            self.request_id, self.condition_id, self.condition_hash, self.decision_id,
            self.decision_hash, self.revalidation_id, self.revalidation_hash,
            self.paper_order_request_id, self.paper_order_request_hash, self.symbol,
            self.instrument_id, self.idempotency_key,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("exact paper authorization lineage is required")
        if self.side != "BUY" or type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("invalid exact paper quantity/side")
        if not (0 < self.executable_price_low <= self.price <= self.executable_price_high):
            raise ValueError("price outside exact executable band")
        if not (0 < self.stop_price < self.price):
            raise ValueError("invalid exact paper stop")
        expected = (self.price - self.stop_price) * self.quantity
        if not math.isclose(expected, self.estimated_maximum_loss, rel_tol=1e-6, abs_tol=0.01):
            raise ValueError("exact paper risk mismatch")
        if self.market_data_timestamp.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("timezone-aware authorization timestamps required")
        if self.expires_at <= self.market_data_timestamp:
            raise ValueError("authorization expiry must follow market data")
        if self.paper_only is not True or self.live_trading_enabled or self.broker_submission or self.advisory_only is not True:
            raise ValueError("unsafe paper authorization request")

    @property
    def content_hash(self) -> str:
        payload = asdict(self)
        payload["market_data_timestamp"] = self.market_data_timestamp.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "operation": "PAPER_PLACE", "request_id": self.request_id,
            "condition_id": self.condition_id, "decision_id": self.decision_id,
            "revalidation_id": self.revalidation_id,
            "paper_order_request_id": self.paper_order_request_id,
            "request_hash": self.content_hash, "symbol": self.symbol,
            "instrument_id": self.instrument_id, "side": self.side,
            "quantity": self.quantity, "paper_only": True,
            "live_trading_enabled": False, "broker_submission": False,
        }


@dataclass(frozen=True)
class ExactPaperAuthorizationDecision:
    authorization_id: str
    decision: str
    reason_code: str
    reason: str
    request_id: str
    request_hash: str
    paper_order_request_hash: str
    authorized_quantity: int
    authorized_price_band: tuple[float, float]
    authorized_stop: float
    authorized_maximum_loss: float
    issued_at: str
    expires_at: str
    one_time: bool = True
    paper_only: bool = True
    live_trading_enabled: bool = False
    broker_submission: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "content_hash": self.content_hash}


class RiskControlStore:
    """Independent atomic local document for the emergency kill switch."""

    VERSION = 1

    def __init__(self, path: Optional[Path | str] = None):
        default_path = os.getenv(
            "CITADEL_RISK_STATE_PATH",
            str(PROJECT_ROOT / "logs" / "risk_control_state.json"),
        )
        self.path = Path(path or default_path)
        self._lock = Lock()

    def initialize(
        self,
        kill_switch_active: bool = True,
        reason: str = "Safe initialization",
        actor: str = "system",
        overwrite: bool = False,
    ) -> None:
        with self._lock:
            if self.path.exists() and not overwrite:
                raise RiskStateUnavailable("Risk state already exists")
            document = {
                "version": self.VERSION,
                "kill_switch": self._kill_payload(
                    kill_switch_active, reason, actor
                ),
            }
            self._write_unlocked(document)

    def activate(self, reason: str, actor: str) -> KillSwitchState:
        if not str(reason).strip() or not str(actor).strip():
            raise ValueError("Kill-switch activation requires reason and actor")
        with self._lock:
            if self.path.exists():
                document = self._read_unlocked()
            else:
                document = {
                    "version": self.VERSION,
                    "kill_switch": {},
                }
            document["kill_switch"] = self._kill_payload(True, reason, actor)
            self._write_unlocked(document)
            return self._parse_kill_switch(document["kill_switch"])

    def deactivate(self, reason: str, actor: str) -> KillSwitchState:
        if not str(reason).strip() or not str(actor).strip():
            raise ValueError("Kill-switch deactivation requires reason and actor")
        with self._lock:
            document = self._read_unlocked()
            document["kill_switch"] = self._kill_payload(False, reason, actor)
            self._write_unlocked(document)
            return self._parse_kill_switch(document["kill_switch"])

    def current_kill_switch(self) -> KillSwitchState:
        with self._lock:
            document = self._read_unlocked()
            return self._parse_kill_switch(document.get("kill_switch"))

    def projection(self) -> KillSwitchProjection:
        if not self.path.exists():
            return self._unavailable_projection("UNKNOWN", "KILL_SWITCH_STATE_MISSING", "MISSING")
        try:
            state = self.current_kill_switch()
        except RiskStateUnavailable:
            return self._unavailable_projection("CORRUPT", "KILL_SWITCH_STATE_CORRUPT", "CORRUPT")
        name = "ACTIVE" if state.active else "INACTIVE"
        return KillSwitchProjection(
            enabled=True, state=name, reason=state.reason,
            activated_at=state.timestamp if state.active else None,
            deactivated_at=state.timestamp if not state.active else None,
            updated_at=state.timestamp, source="RISK_CONTROL_STORE", schema_version=self.VERSION,
            persistence_health="HEALTHY", last_valid_state=name, warnings=(),
        )

    def ensure_metadata(self) -> KillSwitchProjection:
        """Upgrade a valid document without changing its logical state."""
        with self._lock:
            document = self._read_unlocked()
            state = self._parse_kill_switch(document.get("kill_switch"))
            payload = dict(document["kill_switch"])
            name = "ACTIVE" if state.active else "INACTIVE"
            payload.update({
                "state": name, "updated_at": state.timestamp,
                "activated_at": state.timestamp if state.active else None,
                "deactivated_at": state.timestamp if not state.active else None,
                "source": "RISK_CONTROL_STORE", "schema_version": self.VERSION,
                "last_valid_state": name, "warnings": [],
            })
            document["kill_switch"] = payload
            self._write_unlocked(document)
        return self.projection()

    @classmethod
    def _unavailable_projection(cls, state, reason, health):
        return KillSwitchProjection(
            enabled=True, state=state, reason=reason, activated_at=None,
            deactivated_at=None, updated_at=None, source="RISK_CONTROL_STORE",
            schema_version=cls.VERSION, persistence_health=health,
            last_valid_state=None, warnings=(reason,),
        )

    @staticmethod
    def _kill_payload(active: bool, reason: str, actor: str) -> dict[str, Any]:
        return {
            "active": bool(active),
            "reason": str(reason).strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": str(actor).strip(),
        }

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            raise RiskStateUnavailable("Risk control state file is missing")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RiskStateUnavailable("Risk control state cannot be read") from error
        if not isinstance(document, dict) or document.get("version") != self.VERSION:
            raise RiskStateUnavailable("Risk control state schema is invalid")
        self._parse_kill_switch(document.get("kill_switch"))
        return document

    @staticmethod
    def _parse_kill_switch(raw: Any) -> KillSwitchState:
        if not isinstance(raw, Mapping) or type(raw.get("active")) is not bool:
            raise RiskStateUnavailable("Kill-switch state is malformed")
        reason = raw.get("reason")
        timestamp = raw.get("timestamp")
        actor = raw.get("actor")
        if not all(isinstance(value, str) and value for value in (reason, timestamp, actor)):
            raise RiskStateUnavailable("Kill-switch metadata is malformed")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise RiskStateUnavailable("Kill-switch timestamp is malformed") from error
        return KillSwitchState(raw["active"], reason, timestamp, actor)

    def _write_unlocked(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            raise RiskStateUnavailable("Risk control state cannot be persisted") from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


class RiskAuditLogger:
    """Append-only, non-secret authorization decision audit."""

    def __init__(self, path: Optional[Path | str] = None):
        default_path = os.getenv(
            "CITADEL_RISK_AUDIT_PATH",
            str(PROJECT_ROOT / "logs" / "risk_authorization_audit.jsonl"),
        )
        self.path = Path(path or default_path)
        self._lock = Lock()

    def write(
        self,
        decision: AuthorizationDecision | ExactPaperAuthorizationDecision,
        request: RiskAuthorizationRequest | ExactPaperAuthorizationRequest,
    ) -> None:
        record = decision.to_dict()
        record["request"] = request.audit_metadata()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise RiskStateUnavailable("Risk audit cannot be persisted") from error


class RiskAuthorizationService:
    """Authoritative deterministic ALLOW/DENY service for broker mutations."""

    def __init__(
        self,
        config_provider: Optional[Callable[[], Mapping[str, Any]]] = None,
        store: Optional[RiskControlStore] = None,
        paper_state: Optional[PaperStateService] = None,
        audit_logger: Optional[RiskAuditLogger] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ):
        self.config_provider = config_provider or self._load_project_settings
        self.store = store or RiskControlStore()
        self.paper_state = paper_state or PaperStateService()
        self.audit_logger = audit_logger or RiskAuditLogger()
        self.now_provider = now_provider or (lambda: datetime.now(IST))

    def authorize(
        self, request: RiskAuthorizationRequest
    ) -> AuthorizationDecision:
        limits: Optional[RiskLimits] = None
        calculated: dict[str, Any] = {}
        kill_switch_active: Optional[bool] = None

        try:
            try:
                limits = RiskLimits.from_mapping(self.config_provider())
            except RiskConfigurationError as error:
                return self._deny(
                    request,
                    ReasonCode.CONFIGURATION_ERROR,
                    str(error),
                    calculated,
                    None,
                    kill_switch_active,
                )

            # Preserve the original fail-closed live flag as the first runtime gate.
            if not limits.live_trading_enabled:
                return self._deny(
                    request,
                    ReasonCode.LIVE_TRADING_DISABLED,
                    "live_trading_enabled must be true",
                    calculated,
                    limits,
                    kill_switch_active,
                )

            validation = self._validate_request(request, limits)
            if validation is not None:
                code, reason, calculated = validation
                return self._deny(
                    request,
                    code,
                    reason,
                    calculated,
                    limits,
                    kill_switch_active,
                )
            if request.operation in {"PLACE", "MODIFY"}:
                calculated["per_trade_risk"] = round(
                    abs(request.price - request.stop_price) * request.quantity,
                    2,
                )

            kill_switch = self.store.projection()
            kill_switch_active = kill_switch.active
            if kill_switch.state == "ACTIVE":
                return self._deny(
                    request,
                    ReasonCode.KILL_SWITCH_ACTIVE,
                    f"Kill switch active: {kill_switch.reason}",
                    calculated,
                    limits,
                    True,
                )
            if kill_switch.state in {"UNKNOWN", "CORRUPT"}:
                code = ReasonCode.KILL_SWITCH_UNKNOWN if kill_switch.state == "UNKNOWN" else ReasonCode.KILL_SWITCH_CORRUPT
                return self._deny(request, code, kill_switch.reason, calculated, limits, kill_switch_active)

            now = self._now()
            state = self.paper_state.risk_snapshot(now.date())
            calculated.update(
                {
                    "realized_pnl": state.realized_pnl,
                    "unrealized_pnl": state.unrealized_pnl,
                    "total_daily_pnl": state.total_daily_pnl,
                    "trades_taken": state.trades_taken,
                    "consecutive_losses": state.consecutive_losses,
                    "open_positions": state.open_positions,
                }
            )

            market_age = (now - request.market_data_timestamp).total_seconds()
            calculated["market_data_age_seconds"] = round(market_age, 3)
            if market_age < 0 or market_age > limits.max_market_data_age_seconds:
                return self._deny(
                    request,
                    ReasonCode.STALE_MARKET_DATA,
                    "Market data timestamp is stale or invalid",
                    calculated,
                    limits,
                    False,
                )

            if request.request_id and request.request_id in state.accepted_request_ids:
                return self._deny(
                    request,
                    ReasonCode.DUPLICATE_REQUEST,
                    "Request identifier was already accepted",
                    calculated,
                    limits,
                    False,
                )

            if state.total_daily_pnl <= -limits.max_daily_loss:
                return self._deny(
                    request,
                    ReasonCode.DAILY_LOSS_LIMIT_REACHED,
                    "Maximum daily loss has been reached",
                    calculated,
                    limits,
                    False,
                )
            if state.trades_taken >= limits.max_trades_per_day:
                return self._deny(
                    request,
                    ReasonCode.MAX_TRADES_REACHED,
                    "Maximum trades per day has been reached",
                    calculated,
                    limits,
                    False,
                )
            if state.consecutive_losses >= limits.max_consecutive_losses:
                return self._deny(
                    request,
                    ReasonCode.MAX_CONSECUTIVE_LOSSES_REACHED,
                    "Maximum consecutive losses has been reached",
                    calculated,
                    limits,
                    False,
                )
            if state.open_positions >= limits.max_open_positions:
                return self._deny(
                    request,
                    ReasonCode.MAX_OPEN_POSITIONS_REACHED,
                    "Maximum open positions has been reached",
                    calculated,
                    limits,
                    False,
                )
            if request.operation in {"PLACE", "MODIFY"}:
                if request.quantity > limits.max_position_quantity:
                    return self._deny(
                        request,
                        ReasonCode.MAX_POSITION_SIZE_EXCEEDED,
                        "Maximum position quantity has been exceeded",
                        calculated,
                        limits,
                        False,
                    )
                if calculated["per_trade_risk"] > limits.max_risk_per_trade:
                    return self._deny(
                        request,
                        ReasonCode.PER_TRADE_RISK_EXCEEDED,
                        "Maximum risk per trade has been exceeded",
                        calculated,
                        limits,
                        False,
                    )

            if limits.max_volatility is not None:
                if request.volatility is None:
                    return self._deny(
                        request,
                        ReasonCode.INVALID_RISK,
                        "Volatility is required by active configuration",
                        calculated,
                        limits,
                        False,
                    )
                calculated["volatility"] = request.volatility
                if request.volatility > limits.max_volatility:
                    return self._deny(
                        request,
                        ReasonCode.VOLATILITY_LIMIT_EXCEEDED,
                        "Maximum volatility threshold has been exceeded",
                        calculated,
                        limits,
                        False,
                    )

            if request.request_id:
                try:
                    self.paper_state.reserve_request(request.request_id, now.date())
                except DuplicatePaperEvent:
                    return self._deny(
                        request,
                        ReasonCode.DUPLICATE_REQUEST,
                        "Request identifier was already accepted",
                        calculated,
                        limits,
                        False,
                    )

            return self._finalize(
                AuthorizationDecision(
                    decision="ALLOW",
                    reason_code=ReasonCode.ALLOWED.value,
                    reason="All configured risk checks passed",
                    calculated_risk=calculated,
                    active_limits=limits.to_dict(),
                    timestamp=now.isoformat(),
                    request_id=request.request_id,
                    kill_switch_active=False,
                ),
                request,
            )
        except (RiskStateUnavailable, PaperStateUnavailable) as error:
            return self._deny(
                request,
                ReasonCode.STATE_UNAVAILABLE,
                str(error),
                calculated,
                limits,
                kill_switch_active,
            )
        except Exception:
            return self._deny(
                request,
                ReasonCode.INTERNAL_ERROR,
                "Risk authorization failed internally",
                calculated,
                limits,
                kill_switch_active,
            )

    def authorize_exact_paper(
        self, request: ExactPaperAuthorizationRequest
    ) -> ExactPaperAuthorizationDecision:
        """Authorize one exact paper order without weakening the live gate.

        The existing ``authorize`` method remains the only broker-mutation path and
        still fails first when live trading is disabled.  This method has no broker
        endpoint or submission capability.
        """
        if not isinstance(request, ExactPaperAuthorizationRequest):
            raise TypeError("exact paper authorization request type is required")
        now = self._now()
        reason = ReasonCode.ALLOWED
        explanation = "All exact paper risk checks passed"
        allowed = True
        limits = None
        try:
            limits = RiskLimits.from_mapping(self.config_provider())
            if limits.live_trading_enabled:
                allowed, reason, explanation = False, ReasonCode.PAPER_ONLY_REQUIRED, "Phase-5 requires live_trading_enabled=false"
            elif request.live_trading_enabled or request.broker_submission or not request.paper_only:
                allowed, reason, explanation = False, ReasonCode.PAPER_ONLY_REQUIRED, "Paper-only declaration is required"
            elif now >= request.expires_at.astimezone(now.tzinfo):
                allowed, reason, explanation = False, ReasonCode.AUTHORIZATION_EXPIRED, "Paper authorization request expired"
            elif request.paper_order_request_hash == request.revalidation_hash or request.decision_hash == request.revalidation_hash:
                allowed, reason, explanation = False, ReasonCode.LINEAGE_MISMATCH, "Distinct immutable lineage hashes are required"
            kill_switch = self.store.projection()
            if allowed and kill_switch.state != "INACTIVE":
                allowed, reason, explanation = False, (ReasonCode.KILL_SWITCH_ACTIVE if kill_switch.state == "ACTIVE" else ReasonCode.KILL_SWITCH_UNKNOWN), "Kill switch is not proven inactive"
            state = self.paper_state.risk_snapshot(now.date())
            age = (now - request.market_data_timestamp.astimezone(now.tzinfo)).total_seconds()
            if allowed and (age < 0 or age > limits.max_market_data_age_seconds):
                allowed, reason, explanation = False, ReasonCode.STALE_MARKET_DATA, "Market data is stale"
            if allowed and state.total_daily_pnl <= -limits.max_daily_loss:
                allowed, reason, explanation = False, ReasonCode.DAILY_LOSS_LIMIT_REACHED, "Maximum daily loss reached"
            if allowed and state.trades_taken >= limits.max_trades_per_day:
                allowed, reason, explanation = False, ReasonCode.MAX_TRADES_REACHED, "Maximum trades reached"
            if allowed and state.open_positions >= limits.max_open_positions:
                allowed, reason, explanation = False, ReasonCode.MAX_OPEN_POSITIONS_REACHED, "Maximum open positions reached"
            if allowed and request.quantity > limits.max_position_quantity:
                allowed, reason, explanation = False, ReasonCode.MAX_POSITION_SIZE_EXCEEDED, "Maximum position quantity exceeded"
            if allowed and request.estimated_maximum_loss > limits.max_risk_per_trade:
                allowed, reason, explanation = False, ReasonCode.PER_TRADE_RISK_EXCEEDED, "Maximum risk per trade exceeded"
            reservation = f"paper-auth:{request.idempotency_key}"
            if allowed and reservation in state.accepted_request_ids:
                allowed, reason, explanation = False, ReasonCode.DUPLICATE_REQUEST, "Paper authorization already issued"
            if allowed:
                self.paper_state.reserve_request(reservation, now.date())
        except (ValueError, RiskConfigurationError) as error:
            allowed, reason, explanation = False, ReasonCode.INVALID_REQUEST, str(error)
        except DuplicatePaperEvent:
            allowed, reason, explanation = False, ReasonCode.DUPLICATE_REQUEST, "Paper authorization already issued"
        except (RiskStateUnavailable, PaperStateUnavailable) as error:
            allowed, reason, explanation = False, ReasonCode.STATE_UNAVAILABLE, str(error)
        authorization_id = "pauth_" + hashlib.sha256(f"{request.content_hash}|{now.isoformat()}|{allowed}".encode()).hexdigest()[:24]
        decision = ExactPaperAuthorizationDecision(
            authorization_id=authorization_id,
            decision="ALLOW" if allowed else "DENY", reason_code=reason.value,
            reason=explanation, request_id=request.request_id,
            request_hash=request.content_hash,
            paper_order_request_hash=request.paper_order_request_hash,
            authorized_quantity=request.quantity if allowed else 0,
            authorized_price_band=(request.executable_price_low, request.executable_price_high),
            authorized_stop=request.stop_price,
            authorized_maximum_loss=request.estimated_maximum_loss,
            issued_at=now.isoformat(), expires_at=request.expires_at.isoformat(),
        )
        # Existing logger remains the risk audit authority; the request contains no secret.
        self.audit_logger.write(decision, request)
        return decision

    def _validate_request(
        self,
        request: RiskAuthorizationRequest,
        limits: RiskLimits,
    ) -> Optional[tuple[ReasonCode, str, dict[str, Any]]]:
        calculated: dict[str, Any] = {}
        if not isinstance(request, RiskAuthorizationRequest):
            return ReasonCode.INVALID_REQUEST, "Request type is invalid", calculated
        if request.operation not in {"PLACE", "MODIFY", "CANCEL"}:
            return ReasonCode.INVALID_REQUEST, "Mutation operation is unsupported", calculated
        if request.market_data_timestamp is None:
            return (
                ReasonCode.STALE_MARKET_DATA,
                "Market data timestamp is required",
                calculated,
            )
        if request.market_data_timestamp.tzinfo is None:
            return (
                ReasonCode.STALE_MARKET_DATA,
                "Market data timestamp must be timezone-aware",
                calculated,
            )

        if request.operation in {"PLACE", "MODIFY"}:
            if request.quantity is None or request.quantity <= 0 or not float(
                request.quantity
            ).is_integer():
                return (
                    ReasonCode.INVALID_QUANTITY,
                    "Quantity must be a positive whole number",
                    calculated,
                )
            if request.price is None or request.price <= 0:
                return ReasonCode.INVALID_PRICE, "Price must be positive", calculated
            side = str(request.side or "").upper()
            if side not in {"BUY", "SELL"}:
                return ReasonCode.INVALID_REQUEST, "Side must be BUY or SELL", calculated
            if request.stop_price is None or request.stop_price <= 0:
                return ReasonCode.INVALID_STOP, "Stop price must be positive", calculated
            if (side == "BUY" and request.stop_price >= request.price) or (
                side == "SELL" and request.stop_price <= request.price
            ):
                return (
                    ReasonCode.INVALID_STOP,
                    "Stop price is invalid for the requested side",
                    calculated,
                )

            risk = abs(request.price - request.stop_price) * request.quantity
            if not math.isfinite(risk) or risk <= 0:
                return ReasonCode.INVALID_RISK, "Per-trade risk is invalid", calculated
            calculated["per_trade_risk"] = round(risk, 2)

        if request.volatility is not None and (
            not math.isfinite(request.volatility) or request.volatility < 0
        ):
            return ReasonCode.INVALID_RISK, "Volatility is invalid", calculated
        return None

    def _deny(
        self,
        request: RiskAuthorizationRequest,
        code: ReasonCode,
        reason: str,
        calculated: dict[str, Any],
        limits: Optional[RiskLimits],
        kill_switch_active: Optional[bool],
    ) -> AuthorizationDecision:
        decision = AuthorizationDecision(
            decision="DENY",
            reason_code=code.value,
            reason=reason,
            calculated_risk=dict(calculated),
            active_limits=limits.to_dict() if limits is not None else {},
            timestamp=self._safe_now().isoformat(),
            request_id=getattr(request, "request_id", None),
            kill_switch_active=kill_switch_active,
        )
        return self._finalize(decision, request)

    def _finalize(
        self,
        decision: AuthorizationDecision,
        request: RiskAuthorizationRequest,
    ) -> AuthorizationDecision:
        try:
            self.audit_logger.write(decision, request)
            return decision
        except Exception:
            if not decision.allowed:
                return decision
            return AuthorizationDecision(
                decision="DENY",
                reason_code=ReasonCode.STATE_UNAVAILABLE.value,
                reason="Risk audit could not be persisted",
                calculated_risk=decision.calculated_risk,
                active_limits=decision.active_limits,
                timestamp=self._safe_now().isoformat(),
                request_id=decision.request_id,
                kill_switch_active=decision.kill_switch_active,
            )

    def _now(self) -> datetime:
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RiskStateUnavailable("Verified timezone-aware clock unavailable")
        return value.astimezone(IST)

    def _safe_now(self) -> datetime:
        try:
            return self._now()
        except Exception:
            return datetime.now(timezone.utc)

    @staticmethod
    def _load_project_settings() -> Mapping[str, Any]:
        settings_path = PROJECT_ROOT / "config" / "settings.json"
        try:
            value = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RiskConfigurationError("Risk settings cannot be loaded") from error
        if not isinstance(value, Mapping):
            raise RiskConfigurationError("Risk settings must be a mapping")
        return value


def _positive_float(raw: Mapping[str, Any], key: str) -> float:
    value = _finite_number(raw.get(key))
    if value <= 0:
        raise RiskConfigurationError(f"{key} must be positive")
    return value


def _optional_positive_float(
    raw: Mapping[str, Any], key: str
) -> Optional[float]:
    value = raw.get(key)
    if value is None:
        return None
    parsed = _finite_number(value)
    if parsed <= 0:
        raise RiskConfigurationError(f"{key} must be positive or null")
    return parsed


def _positive_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RiskConfigurationError(f"{key} must be a positive integer")
    return value


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Expected non-negative integer")
    return value


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise RiskConfigurationError("Boolean is not a numeric risk value")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise RiskConfigurationError("Risk value is not numeric") from error
    if not math.isfinite(parsed):
        raise RiskConfigurationError("Risk value must be finite")
    return parsed


def _number_or_none(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _datetime_or_none(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None
