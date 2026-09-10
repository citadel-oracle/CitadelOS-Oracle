"""Authoritative, restart-safe state for all CITADEL OS paper trading."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PaperStateError(RuntimeError):
    """Base error for deterministic paper-state failures."""


class PaperStateUnavailable(PaperStateError):
    """Persisted paper state is missing, malformed, or unavailable."""


class InvalidPaperEvent(PaperStateError):
    """A paper lifecycle event contains invalid fields."""


class DuplicatePaperEvent(PaperStateError):
    """A request or lifecycle event was already applied."""


class UnknownPaperPosition(PaperStateError):
    """A requested paper position does not exist."""


@dataclass(frozen=True)
class PaperPosition:
    position_id: str
    request_id: str
    instrument_id: Optional[str]
    symbol: str
    option_type: Optional[str]
    strike: Optional[float]
    expiry: Optional[str]
    side: str
    raw_quantity: int
    remaining_quantity: int
    lot_size: Optional[int]
    number_of_lots: Optional[float]
    entry_price: float
    mark_price: float
    stop_price: Optional[float]
    initial_stop_price: Optional[float]
    target_price: Optional[float]
    confidence: Optional[float]
    reason: str
    opened_at: str
    last_updated: str
    break_even_done: bool = False
    trailing_active: bool = False

    @property
    def unrealized_pnl(self) -> float:
        direction = 1 if self.side in {"BUY", "LONG"} else -1
        return round(
            (self.mark_price - self.entry_price)
            * self.remaining_quantity
            * direction,
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["unrealized_pnl"] = self.unrealized_pnl
        return value

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PaperPosition":
        if not isinstance(raw, Mapping):
            raise PaperStateUnavailable("Paper position is malformed")
        try:
            raw_quantity = _positive_int(raw.get("raw_quantity"), "raw_quantity")
            remaining = _positive_int(
                raw.get("remaining_quantity"), "remaining_quantity"
            )
            if remaining > raw_quantity:
                raise ValueError("remaining quantity exceeds original quantity")
            lot_size = _optional_positive_int(raw.get("lot_size"), "lot_size")
            expected_lots = (
                round(raw_quantity / lot_size, 6) if lot_size is not None else None
            )
            stored_lots = raw.get("number_of_lots")
            if stored_lots is not None and not math.isclose(
                _non_negative_number(stored_lots, "number_of_lots"),
                expected_lots,
            ):
                raise ValueError("number_of_lots is inconsistent")
            side = str(raw["side"]).upper()
            if side not in {"BUY", "SELL", "LONG", "SHORT"}:
                raise ValueError("invalid side")
            option_type = raw.get("option_type")
            if option_type is not None:
                option_type = str(option_type).upper()
                if option_type not in {"CE", "PE"}:
                    raise ValueError("invalid option type")
            expiry = raw.get("expiry")
            if expiry is not None:
                expiry = date.fromisoformat(str(expiry)).isoformat()
            position = cls(
                position_id=_required_text(raw.get("position_id"), "position_id"),
                request_id=_required_text(raw.get("request_id"), "request_id"),
                instrument_id=_optional_text(raw.get("instrument_id")),
                symbol=_required_text(raw.get("symbol"), "symbol"),
                option_type=option_type,
                strike=_optional_non_negative_number(raw.get("strike"), "strike"),
                expiry=expiry,
                side=side,
                raw_quantity=raw_quantity,
                remaining_quantity=remaining,
                lot_size=lot_size,
                number_of_lots=expected_lots,
                entry_price=_non_negative_number(raw.get("entry_price"), "entry_price"),
                mark_price=_non_negative_number(raw.get("mark_price"), "mark_price"),
                stop_price=_optional_non_negative_number(
                    raw.get("stop_price"), "stop_price"
                ),
                initial_stop_price=_optional_non_negative_number(
                    raw.get("initial_stop_price"), "initial_stop_price"
                ),
                target_price=_optional_non_negative_number(
                    raw.get("target_price"), "target_price"
                ),
                confidence=_optional_non_negative_number(
                    raw.get("confidence"), "confidence"
                ),
                reason=str(raw.get("reason") or ""),
                opened_at=_timestamp(raw.get("opened_at"), "opened_at"),
                last_updated=_timestamp(raw.get("last_updated"), "last_updated"),
                break_even_done=_boolean(
                    raw.get("break_even_done", False), "break_even_done"
                ),
                trailing_active=_boolean(
                    raw.get("trailing_active", False), "trailing_active"
                ),
            )
        except (KeyError, TypeError, ValueError, InvalidPaperEvent) as error:
            raise PaperStateUnavailable("Paper position is malformed") from error
        return position


@dataclass(frozen=True)
class PaperClosedTrade:
    close_event_id: str
    request_id: Optional[str]
    position_id: str
    instrument_id: Optional[str]
    symbol: str
    option_type: Optional[str]
    strike: Optional[float]
    expiry: Optional[str]
    side: str
    closed_quantity: int
    raw_quantity: int
    lot_size: Optional[int]
    number_of_lots: Optional[float]
    entry_price: float
    exit_price: float
    realized_pnl: float
    opened_at: str
    closed_at: str
    exit_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PaperClosedTrade":
        if not isinstance(raw, Mapping):
            raise PaperStateUnavailable("Closed paper trade is malformed")
        try:
            raw_quantity = _positive_int(raw.get("raw_quantity"), "raw_quantity")
            closed_quantity = _positive_int(
                raw.get("closed_quantity"), "closed_quantity"
            )
            if closed_quantity > raw_quantity:
                raise ValueError("closed quantity exceeds original quantity")
            lot_size = _optional_positive_int(raw.get("lot_size"), "lot_size")
            lots = round(closed_quantity / lot_size, 6) if lot_size else None
            stored_lots = raw.get("number_of_lots")
            if (lots is None and stored_lots is not None) or (
                lots is not None
                and (
                    stored_lots is None
                    or not math.isclose(
                        _non_negative_number(stored_lots, "number_of_lots"),
                        lots,
                    )
                )
            ):
                raise ValueError("number_of_lots is inconsistent")
            side = str(raw["side"]).upper()
            if side not in {"BUY", "SELL", "LONG", "SHORT"}:
                raise ValueError("invalid side")
            option_type = raw.get("option_type")
            if option_type is not None:
                option_type = str(option_type).upper()
                if option_type not in {"CE", "PE"}:
                    raise ValueError("invalid option type")
            expiry = raw.get("expiry")
            if expiry is not None:
                expiry = date.fromisoformat(str(expiry)).isoformat()
            return cls(
                close_event_id=_required_text(
                    raw.get("close_event_id"), "close_event_id"
                ),
                request_id=_optional_text(raw.get("request_id")),
                position_id=_required_text(raw.get("position_id"), "position_id"),
                instrument_id=_optional_text(raw.get("instrument_id")),
                symbol=_required_text(raw.get("symbol"), "symbol"),
                option_type=option_type,
                strike=_optional_non_negative_number(raw.get("strike"), "strike"),
                expiry=expiry,
                side=side,
                closed_quantity=closed_quantity,
                raw_quantity=raw_quantity,
                lot_size=lot_size,
                number_of_lots=lots,
                entry_price=_non_negative_number(raw.get("entry_price"), "entry_price"),
                exit_price=_non_negative_number(raw.get("exit_price"), "exit_price"),
                realized_pnl=_finite_number(raw.get("realized_pnl"), "realized_pnl"),
                opened_at=_timestamp(raw.get("opened_at"), "opened_at"),
                closed_at=_timestamp(raw.get("closed_at"), "closed_at"),
                exit_reason=str(raw.get("exit_reason") or ""),
            )
        except (KeyError, TypeError, ValueError, InvalidPaperEvent) as error:
            raise PaperStateUnavailable("Closed paper trade is malformed") from error


@dataclass(frozen=True)
class PaperRiskSnapshot:
    trading_date: str
    realized_pnl: float
    unrealized_pnl: float
    total_daily_pnl: float
    trades_taken: int
    consecutive_losses: int
    open_positions: int
    accepted_request_ids: tuple[str, ...]


@dataclass(frozen=True)
class PaperState:
    trading_date: str
    cash_balance: Optional[float]
    open_positions: tuple[PaperPosition, ...]
    closed_trades: tuple[PaperClosedTrade, ...]
    realized_pnl: float
    unrealized_pnl: float
    total_daily_pnl: float
    trades_taken: int
    consecutive_losses: int
    accepted_request_ids: tuple[str, ...]
    applied_event_ids: tuple[str, ...]
    last_updated: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "cash_balance": self.cash_balance,
            "open_positions": [item.to_dict() for item in self.open_positions],
            "closed_trades": [item.to_dict() for item in self.closed_trades],
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_daily_pnl": self.total_daily_pnl,
            "trades_taken": self.trades_taken,
            "consecutive_losses": self.consecutive_losses,
            "accepted_request_ids": list(self.accepted_request_ids),
            "applied_event_ids": list(self.applied_event_ids),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PaperState":
        if not isinstance(raw, Mapping):
            raise PaperStateUnavailable("Paper state payload is malformed")
        try:
            trading_date = date.fromisoformat(str(raw["trading_date"])).isoformat()
            positions_raw = raw.get("open_positions")
            closed_raw = raw.get("closed_trades")
            if not isinstance(positions_raw, list) or not isinstance(closed_raw, list):
                raise ValueError("position/trade collections must be lists")
            positions = tuple(PaperPosition.from_mapping(item) for item in positions_raw)
            closed = tuple(PaperClosedTrade.from_mapping(item) for item in closed_raw)
            if len({item.position_id for item in positions}) != len(positions):
                raise ValueError("duplicate open position")
            accepted = _string_tuple(raw.get("accepted_request_ids"), "accepted_request_ids")
            events = _string_tuple(raw.get("applied_event_ids"), "applied_event_ids")
            if len(set(accepted)) != len(accepted) or len(set(events)) != len(events):
                raise ValueError("duplicate persisted identifiers")
            realized = _finite_number(raw.get("realized_pnl"), "realized_pnl")
            unrealized = round(sum(item.unrealized_pnl for item in positions), 2)
            stored_unrealized = _finite_number(raw.get("unrealized_pnl"), "unrealized_pnl")
            stored_total = _finite_number(raw.get("total_daily_pnl"), "total_daily_pnl")
            if not math.isclose(stored_unrealized, unrealized, abs_tol=0.01):
                raise ValueError("unrealized P&L is inconsistent")
            if not math.isclose(stored_total, realized + unrealized, abs_tol=0.01):
                raise ValueError("total daily P&L is inconsistent")
            return cls(
                trading_date=trading_date,
                cash_balance=_optional_finite_number(raw.get("cash_balance"), "cash_balance"),
                open_positions=positions,
                closed_trades=closed,
                realized_pnl=round(realized, 2),
                unrealized_pnl=unrealized,
                total_daily_pnl=round(realized + unrealized, 2),
                trades_taken=_non_negative_int(raw.get("trades_taken"), "trades_taken"),
                consecutive_losses=_non_negative_int(
                    raw.get("consecutive_losses"), "consecutive_losses"
                ),
                accepted_request_ids=accepted,
                applied_event_ids=events,
                last_updated=_timestamp(raw.get("last_updated"), "last_updated"),
            )
        except (KeyError, TypeError, ValueError, InvalidPaperEvent) as error:
            raise PaperStateUnavailable("Paper state payload is malformed") from error


class PaperStateService:
    """Single owner for paper positions, lifecycle, P&L, and daily counters."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Optional[Path | str] = None,
        now_provider=None,
    ):
        default_path = os.getenv(
            "CITADEL_PAPER_STATE_PATH",
            str(PROJECT_ROOT / "logs" / "paper_state.json"),
        )
        self.path = Path(path or default_path)
        self.now_provider = now_provider or (lambda: datetime.now(IST))
        self._lock = Lock()

    def initialize(
        self,
        *,
        trading_date: Optional[date] = None,
        cash_balance: Optional[float] = None,
        closed_trades: Iterable[PaperClosedTrade] = (),
        realized_pnl: float = 0.0,
        trades_taken: int = 0,
        consecutive_losses: int = 0,
        accepted_request_ids: Iterable[str] = (),
        overwrite: bool = False,
    ) -> PaperState:
        with self._lock:
            if self.path.exists() and not overwrite:
                raise PaperStateUnavailable("Paper state already exists")
            now = self._now()
            state = PaperState(
                trading_date=(trading_date or now.date()).isoformat(),
                cash_balance=(
                    _finite_number(cash_balance, "cash_balance")
                    if cash_balance is not None
                    else None
                ),
                open_positions=(),
                closed_trades=tuple(closed_trades),
                realized_pnl=round(_finite_number(realized_pnl, "realized_pnl"), 2),
                unrealized_pnl=0.0,
                total_daily_pnl=round(_finite_number(realized_pnl, "realized_pnl"), 2),
                trades_taken=_non_negative_int(trades_taken, "trades_taken"),
                consecutive_losses=_non_negative_int(
                    consecutive_losses, "consecutive_losses"
                ),
                accepted_request_ids=tuple(accepted_request_ids),
                applied_event_ids=(),
                last_updated=now.isoformat(),
            )
            PaperState.from_mapping(state.to_dict())
            self._write_unlocked(state)
            return state

    def load(self, verified_date: Optional[date] = None) -> PaperState:
        with self._lock:
            return self._load_for_date_unlocked(verified_date or self._now().date())

    def open_position(
        self,
        *,
        position_id: str,
        request_id: str,
        event_id: str,
        symbol: str,
        side: str,
        raw_quantity: int,
        entry_price: float,
        instrument_id: Optional[str] = None,
        lot_size: Optional[int] = None,
        option_type: Optional[str] = None,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        confidence: Optional[float] = None,
        reason: str = "",
    ) -> PaperPosition:
        with self._lock:
            now = self._now()
            state = self._load_for_date_unlocked(now.date())
            self._reject_duplicates(state, request_id, event_id)
            if any(item.position_id == str(position_id) for item in state.open_positions):
                raise DuplicatePaperEvent("Position identifier already exists")
            quantity = _positive_int(raw_quantity, "raw_quantity")
            entry = _non_negative_number(entry_price, "entry_price")
            parsed_lot = _optional_positive_int(lot_size, "lot_size")
            side_value = str(side).upper()
            if side_value not in {"BUY", "SELL", "LONG", "SHORT"}:
                raise InvalidPaperEvent("side is invalid")
            option_value = str(option_type).upper() if option_type is not None else None
            if option_value not in {None, "CE", "PE"}:
                raise InvalidPaperEvent("option_type is invalid")
            expiry_value = date.fromisoformat(str(expiry)).isoformat() if expiry else None
            timestamp = now.isoformat()
            position = PaperPosition(
                position_id=_required_text(position_id, "position_id"),
                request_id=_required_text(request_id, "request_id"),
                instrument_id=_optional_text(instrument_id),
                symbol=_required_text(symbol, "symbol"),
                option_type=option_value,
                strike=_optional_non_negative_number(strike, "strike"),
                expiry=expiry_value,
                side=side_value,
                raw_quantity=quantity,
                remaining_quantity=quantity,
                lot_size=parsed_lot,
                number_of_lots=(
                    round(quantity / parsed_lot, 6) if parsed_lot else None
                ),
                entry_price=entry,
                mark_price=entry,
                stop_price=_optional_non_negative_number(stop_price, "stop_price"),
                initial_stop_price=_optional_non_negative_number(
                    stop_price, "stop_price"
                ),
                target_price=_optional_non_negative_number(
                    target_price, "target_price"
                ),
                confidence=_optional_non_negative_number(
                    confidence, "confidence"
                ),
                reason=str(reason or ""),
                opened_at=timestamp,
                last_updated=timestamp,
            )
            updated = replace(
                state,
                open_positions=state.open_positions + (position,),
                trades_taken=state.trades_taken + 1,
                accepted_request_ids=state.accepted_request_ids + (request_id,),
                applied_event_ids=state.applied_event_ids + (event_id,),
                last_updated=timestamp,
            )
            updated = self._recalculate(updated)
            self._write_unlocked(updated)
            return position

    def update_mark(
        self,
        position_id: str,
        mark_price: float,
        event_id: str,
        *,
        stop_price: Optional[float] = None,
        break_even_done: Optional[bool] = None,
        trailing_active: Optional[bool] = None,
    ) -> PaperPosition:
        with self._lock:
            now = self._now()
            state = self._load_for_date_unlocked(now.date())
            self._reject_event(state, event_id)
            price = _non_negative_number(mark_price, "mark_price")
            index = self._position_index(state, position_id)
            current = state.open_positions[index]
            updated_position = replace(
                current,
                mark_price=price,
                stop_price=(
                    _optional_non_negative_number(stop_price, "stop_price")
                    if stop_price is not None
                    else current.stop_price
                ),
                break_even_done=(
                    _boolean(break_even_done, "break_even_done")
                    if break_even_done is not None
                    else current.break_even_done
                ),
                trailing_active=(
                    _boolean(trailing_active, "trailing_active")
                    if trailing_active is not None
                    else current.trailing_active
                ),
                last_updated=now.isoformat(),
            )
            positions = list(state.open_positions)
            positions[index] = updated_position
            updated = replace(
                state,
                open_positions=tuple(positions),
                applied_event_ids=state.applied_event_ids + (event_id,),
                last_updated=now.isoformat(),
            )
            updated = self._recalculate(updated)
            self._write_unlocked(updated)
            return updated_position

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        event_id: str,
        *,
        close_quantity: Optional[int] = None,
        request_id: Optional[str] = None,
        exit_reason: str = "",
    ) -> PaperClosedTrade:
        with self._lock:
            now = self._now()
            state = self._load_for_date_unlocked(now.date())
            self._reject_event(state, event_id)
            if request_id and request_id in state.accepted_request_ids:
                raise DuplicatePaperEvent("Request identifier was already accepted")
            index = self._position_index(state, position_id)
            position = state.open_positions[index]
            quantity = (
                position.remaining_quantity
                if close_quantity is None
                else _positive_int(close_quantity, "close_quantity")
            )
            if quantity > position.remaining_quantity:
                raise InvalidPaperEvent("Close quantity exceeds open quantity")
            exit_value = _non_negative_number(exit_price, "exit_price")
            direction = 1 if position.side in {"BUY", "LONG"} else -1
            realized = round(
                (exit_value - position.entry_price) * quantity * direction,
                2,
            )
            remaining = position.remaining_quantity - quantity
            closed = PaperClosedTrade(
                close_event_id=_required_text(event_id, "event_id"),
                request_id=_optional_text(request_id),
                position_id=position.position_id,
                instrument_id=position.instrument_id,
                symbol=position.symbol,
                option_type=position.option_type,
                strike=position.strike,
                expiry=position.expiry,
                side=position.side,
                closed_quantity=quantity,
                raw_quantity=position.raw_quantity,
                lot_size=position.lot_size,
                number_of_lots=(
                    round(quantity / position.lot_size, 6)
                    if position.lot_size
                    else None
                ),
                entry_price=position.entry_price,
                exit_price=exit_value,
                realized_pnl=realized,
                opened_at=position.opened_at,
                closed_at=now.isoformat(),
                exit_reason=str(exit_reason or ""),
            )
            positions = list(state.open_positions)
            if remaining == 0:
                positions.pop(index)
            else:
                positions[index] = replace(
                    position,
                    remaining_quantity=remaining,
                    mark_price=exit_value,
                    last_updated=now.isoformat(),
                )
            losses = state.consecutive_losses
            if realized < 0:
                losses += 1
            elif realized > 0:
                losses = 0
            accepted = state.accepted_request_ids
            if request_id:
                accepted += (request_id,)
            updated = replace(
                state,
                open_positions=tuple(positions),
                closed_trades=state.closed_trades + (closed,),
                realized_pnl=round(state.realized_pnl + realized, 2),
                consecutive_losses=losses,
                accepted_request_ids=accepted,
                applied_event_ids=state.applied_event_ids + (event_id,),
                last_updated=now.isoformat(),
            )
            updated = self._recalculate(updated)
            self._write_unlocked(updated)
            return closed

    def reserve_request(self, request_id: str, verified_date: date) -> None:
        with self._lock:
            state = self._load_for_date_unlocked(verified_date)
            request_value = _required_text(request_id, "request_id")
            if request_value in state.accepted_request_ids:
                raise DuplicatePaperEvent("Request identifier was already accepted")
            updated = replace(
                state,
                accepted_request_ids=state.accepted_request_ids + (request_value,),
                last_updated=self._now().isoformat(),
            )
            self._write_unlocked(updated)

    def risk_snapshot(self, verified_date: date) -> PaperRiskSnapshot:
        state = self.load(verified_date)
        return PaperRiskSnapshot(
            trading_date=state.trading_date,
            realized_pnl=state.realized_pnl,
            unrealized_pnl=state.unrealized_pnl,
            total_daily_pnl=state.total_daily_pnl,
            trades_taken=state.trades_taken,
            consecutive_losses=state.consecutive_losses,
            open_positions=len(state.open_positions),
            accepted_request_ids=state.accepted_request_ids,
        )

    def journal_summary(self) -> dict[str, Any]:
        state = self.load()
        wins = sum(item.realized_pnl > 0 for item in state.closed_trades)
        losses = sum(item.realized_pnl < 0 for item in state.closed_trades)
        return {
            "total_closed": len(state.closed_trades),
            "wins": wins,
            "losses": losses,
            "net_points": round(
                sum(item.realized_pnl for item in state.closed_trades), 2
            ),
        }

    def recent_closed_trades(self, limit: int = 5) -> list[dict[str, Any]]:
        state = self.load()
        return [item.to_dict() for item in state.closed_trades[-max(0, int(limit)):]]

    def _load_for_date_unlocked(self, verified_date: date) -> PaperState:
        state = self._read_unlocked()
        state_date = date.fromisoformat(state.trading_date)
        if state_date == verified_date:
            return state
        if state_date > verified_date:
            raise PaperStateUnavailable(
                "Paper state date is later than verified trading date"
            )
        now = self._now()
        rolled = replace(
            state,
            trading_date=verified_date.isoformat(),
            realized_pnl=0.0,
            trades_taken=0,
            consecutive_losses=0,
            accepted_request_ids=(),
            last_updated=now.isoformat(),
        )
        rolled = self._recalculate(rolled)
        self._write_unlocked(rolled)
        return rolled

    def _read_unlocked(self) -> PaperState:
        if not self.path.exists():
            raise PaperStateUnavailable("Authoritative paper state file is missing")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PaperStateUnavailable("Authoritative paper state cannot be read") from error
        if not isinstance(document, Mapping) or document.get("schema_version") != self.SCHEMA_VERSION:
            raise PaperStateUnavailable("Authoritative paper state schema is invalid")
        return PaperState.from_mapping(document.get("state"))

    def _write_unlocked(self, state: PaperState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "state": state.to_dict(),
        }
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
            raise PaperStateUnavailable("Authoritative paper state cannot be persisted") from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _recalculate(state: PaperState) -> PaperState:
        unrealized = round(sum(item.unrealized_pnl for item in state.open_positions), 2)
        return replace(
            state,
            unrealized_pnl=unrealized,
            total_daily_pnl=round(state.realized_pnl + unrealized, 2),
        )

    @staticmethod
    def _reject_duplicates(state: PaperState, request_id: str, event_id: str) -> None:
        request_value = _required_text(request_id, "request_id")
        if request_value in state.accepted_request_ids:
            raise DuplicatePaperEvent("Request identifier was already accepted")
        PaperStateService._reject_event(state, event_id)

    @staticmethod
    def _reject_event(state: PaperState, event_id: str) -> None:
        event_value = _required_text(event_id, "event_id")
        if event_value in state.applied_event_ids:
            raise DuplicatePaperEvent("Lifecycle event was already applied")

    @staticmethod
    def _position_index(state: PaperState, position_id: str) -> int:
        for index, item in enumerate(state.open_positions):
            if item.position_id == str(position_id):
                return index
        raise UnknownPaperPosition(f"Unknown paper position: {position_id}")

    def _now(self) -> datetime:
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise PaperStateUnavailable("Verified timezone-aware clock unavailable")
        return value.astimezone(IST)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise InvalidPaperEvent(f"{field_name} is required")
    return str(value).strip()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise InvalidPaperEvent(f"{field_name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise InvalidPaperEvent(f"{field_name} must be numeric") from error
    if not math.isfinite(parsed):
        raise InvalidPaperEvent(f"{field_name} must be finite")
    return parsed


def _non_negative_number(value: Any, field_name: str) -> float:
    parsed = _finite_number(value, field_name)
    if parsed < 0:
        raise InvalidPaperEvent(f"{field_name} cannot be negative")
    return parsed


def _optional_non_negative_number(
    value: Any, field_name: str
) -> Optional[float]:
    return None if value is None else _non_negative_number(value, field_name)


def _optional_finite_number(value: Any, field_name: str) -> Optional[float]:
    return None if value is None else _finite_number(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidPaperEvent(f"{field_name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> Optional[int]:
    return None if value is None else _positive_int(value, field_name)


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidPaperEvent(f"{field_name} must be a non-negative integer")
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise InvalidPaperEvent(f"{field_name} must be boolean")
    return value


def _timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidPaperEvent(f"{field_name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidPaperEvent(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise InvalidPaperEvent(f"{field_name} must be timezone-aware")
    return parsed.isoformat()


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise InvalidPaperEvent(f"{field_name} must be a string list")
    return tuple(value)
