"""Authoritative Dhan option resolution for live execution preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional

from src.paper_trading.contracts import ContractResolutionError, DhanInstrumentMaster
from src.paper_trading.models import ResolvedOptionContract


@dataclass(frozen=True)
class UnderlyingDefinition:
    symbol: str
    security_id: str
    exchange_segment: str = "IDX_I"


DEFAULT_UNDERLYINGS = {
    "NIFTY": UnderlyingDefinition("NIFTY", "13"),
    "BANKNIFTY": UnderlyingDefinition("BANKNIFTY", "25"),
}


class DhanOptionResolver:
    """Resolve ATM +/- two strikes using active Dhan expiries and option chain."""

    OFFSETS = {-2, -1, 0, 1, 2}

    def __init__(self, client, instrument_master=None, underlyings=None, clock=None):
        self.client = client
        self.instrument_master = instrument_master or DhanInstrumentMaster()
        self.underlyings = dict(DEFAULT_UNDERLYINGS)
        self.underlyings.update({str(key).upper(): value for key, value in (underlyings or {}).items()})
        self.clock = clock or date.today

    def resolve(
        self,
        *,
        underlying: str,
        option_type: str,
        strike_offset: int = 0,
        expiry_kind: str = "WEEKLY",
        expiry: Optional[str] = None,
    ) -> ResolvedOptionContract:
        symbol = str(underlying).upper()
        definition = self.underlyings.get(symbol)
        if definition is None:
            raise ContractResolutionError(f"underlying {symbol} requires authoritative Dhan metadata")
        if strike_offset not in self.OFFSETS or isinstance(strike_offset, bool):
            raise ContractResolutionError("strike offset must be between ATM-2 and ATM+2")
        option_type = str(option_type).upper()
        if option_type not in {"CE", "PE"}:
            raise ContractResolutionError("option type must be CE or PE")
        selected_expiry = expiry or self._expiry(definition, expiry_kind)
        response = self.client.get_option_chain(definition.exchange_segment, definition.security_id, selected_expiry)
        data = response.get("data") if isinstance(response, Mapping) else None
        chain = data.get("oc") if isinstance(data, Mapping) else None
        underlying_ltp = data.get("last_price") if isinstance(data, Mapping) else None
        if not isinstance(chain, Mapping) or not chain:
            raise ContractResolutionError("authoritative Dhan option chain is unavailable")
        try:
            strikes = sorted(float(value) for value in chain)
            atm_index = min(range(len(strikes)), key=lambda index: (abs(strikes[index] - float(underlying_ltp)), strikes[index]))
            strike = strikes[atm_index + strike_offset]
        except (TypeError, ValueError, IndexError):
            raise ContractResolutionError("requested authoritative strike is unavailable") from None
        row = chain.get(f"{strike:.6f}") or chain.get(str(strike))
        if not isinstance(row, Mapping):
            row = next((item for key, item in chain.items() if abs(float(key) - strike) < 0.001), None)
        leg = row.get(option_type.lower()) if isinstance(row, Mapping) else None
        if not isinstance(leg, Mapping) or leg.get("security_id") is None:
            raise ContractResolutionError("resolved option leg is unavailable")
        master = self.instrument_master.resolve(
            security_id=leg["security_id"],
            expiry=selected_expiry,
            strike=strike,
            option_type=option_type,
            underlying=symbol,
        )
        ltp = _positive(leg.get("last_price", leg.get("ltp")))
        if ltp is None:
            raise ContractResolutionError("resolved option quote is unavailable")
        return ResolvedOptionContract(
            str(master["security_id"]),
            str(master["exchange_segment"]),
            symbol,
            option_type,
            strike,
            selected_expiry,
            int(master["lot_size"]),
            ltp,
            _positive(leg.get("top_ask_price")),
            _integer(leg.get("top_ask_quantity")),
            _positive(leg.get("top_bid_price")),
            _integer(leg.get("top_bid_quantity")),
            str(master["source"]),
            "DHAN_OPTION_CHAIN",
        )

    def _expiry(self, definition: UnderlyingDefinition, expiry_kind: str) -> str:
        response = self.client.get_option_expiries(definition.exchange_segment, definition.security_id)
        values = response.get("data") if isinstance(response, Mapping) else None
        today = self.clock()
        if isinstance(today, datetime):
            today = today.date()
        active = sorted((_date(value), str(value)) for value in values or [] if _date(value) >= today)
        if not active:
            raise ContractResolutionError("active Dhan expiry is unavailable")
        kind = str(expiry_kind).upper()
        if kind == "WEEKLY":
            return active[0][1]
        if kind != "MONTHLY":
            raise ContractResolutionError("expiry kind must be WEEKLY or MONTHLY")
        rows = self.instrument_master._rows(definition.symbol)
        monthly = {
            str(self.instrument_master._text(row, "SM_EXPIRY_DATE", "SEM_EXPIRY_DATE") or "")[:10]
            for row in rows
            if str(self.instrument_master._text(row, "EXPIRY_FLAG", "SEM_EXPIRY_FLAG") or "").upper() == "M"
        }
        match = next((text for _, text in active if text in monthly), None)
        if not match:
            raise ContractResolutionError("authoritative monthly expiry is unavailable")
        return match


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return date.min


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> Optional[int]:
    try:
        number = int(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None
