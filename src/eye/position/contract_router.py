"""Canonical contract alignment for EYE's Analyzer-only paper boundary.

This module never synthesizes expiry, strike, security ID, lot size, or an
OpenAlgo symbol.  Those are all instrument-master facts and a missing fact is
an explicit no-contract result rather than a plausible-looking order target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class ResolvedContract:
    raw_symbol: str
    underlying: str
    exchange: str
    expiry: str
    strike: float
    option_type: str
    openalgo_symbol: str
    dhan_security_id: str
    lot_size: int
    alignment_status: str
    preferred_option_type: str
    opening_action: str
    routing_reason: str


class ContractRouter:
    """Resolve only against caller-supplied canonical instrument metadata."""

    def __init__(self, instrument_rows: Iterable[Mapping[str, Any]] = ()) -> None:
        self._rows = tuple(dict(row) for row in instrument_rows if isinstance(row, Mapping))

    def resolve_contract(
        self,
        chart_symbol: str,
        eye_direction: str,
        spot_price: float,
        *,
        session_date: str | None = None,
        expiry: str | None = None,
    ) -> Optional[ResolvedContract]:
        raw = str(chart_symbol).strip().upper()
        direction = str(eye_direction).strip().upper()
        preferred = "CE" if direction == "BULLISH" else "PE" if direction == "BEARISH" else None
        if preferred is None or not self._rows:
            return None

        exact = self._exact_row(raw)
        if exact is not None:
            option_type = self._option_type(exact)
            if option_type not in {"CE", "PE"}:
                return None
            return self._from_row(
                raw=raw,
                row=exact,
                preferred=preferred,
                aligned=option_type == preferred,
                reason=(
                    f"Exact canonical option chart {option_type} aligns with EYE {direction}."
                    if option_type == preferred
                    else f"Exact canonical option chart {option_type} is contrary to EYE {direction}."
                ),
            )

        underlying = raw.split(":")[-1]
        rows = [
            row for row in self._rows
            if self._underlying(row) == underlying and self._option_type(row) == preferred
        ]
        target_expiry = expiry or self._first_expiry(rows, session_date)
        if not target_expiry:
            return None
        eligible = [row for row in rows if self._expiry(row) == target_expiry]
        if not eligible or not self._positive_number(spot_price):
            return None
        row = min(
            eligible,
            key=lambda candidate: abs(float(self._strike(candidate)) - float(spot_price)),
        )
        return self._from_row(
            raw=raw,
            row=row,
            preferred=preferred,
            aligned=True,
            reason=(
                f"Underlying {underlying} resolved from canonical instrument metadata; "
                f"EYE {direction} aligns with {preferred}."
            ),
        )

    def _exact_row(self, raw: str) -> Optional[Mapping[str, Any]]:
        matches = [
            row for row in self._rows
            if raw in {
                str(row.get("SECURITY_ID") or "").upper(),
                str(row.get("security_id") or "").upper(),
                str(row.get("SYMBOL_NAME") or "").upper(),
                str(row.get("trading_symbol") or "").upper(),
                str(row.get("openalgo_symbol") or "").upper(),
            }
        ]
        return matches[0] if len(matches) == 1 else None

    def _from_row(
        self,
        *,
        raw: str,
        row: Mapping[str, Any],
        preferred: str,
        aligned: bool,
        reason: str,
    ) -> Optional[ResolvedContract]:
        security_id = str(row.get("SECURITY_ID") or row.get("security_id") or "").strip()
        symbol = str(
            row.get("SYMBOL_NAME") or row.get("trading_symbol") or row.get("openalgo_symbol") or ""
        ).strip()
        strike = self._strike(row)
        lot = row.get("LOT_SIZE", row.get("lot_size"))
        try:
            lot_size = int(lot)
        except (TypeError, ValueError):
            return None
        if not security_id or not symbol or strike is None or lot_size <= 0:
            return None
        option_type = self._option_type(row)
        expiry = self._expiry(row)
        if option_type not in {"CE", "PE"} or not expiry:
            return None
        return ResolvedContract(
            raw_symbol=raw,
            underlying=self._underlying(row),
            exchange=str(row.get("EXCHANGE") or row.get("exchange") or "NFO").upper(),
            expiry=expiry,
            strike=float(strike),
            option_type=option_type,
            openalgo_symbol=symbol,
            dhan_security_id=security_id,
            lot_size=lot_size,
            alignment_status="ALIGNED" if aligned else "CONTRARY",
            preferred_option_type=preferred,
            opening_action="BUY" if aligned else "NO_ACTION",
            routing_reason=reason,
        )

    @staticmethod
    def _underlying(row: Mapping[str, Any]) -> str:
        return str(row.get("UNDERLYING_SYMBOL") or row.get("underlying") or "").upper()

    @staticmethod
    def _option_type(row: Mapping[str, Any]) -> str:
        return str(row.get("OPTION_TYPE") or row.get("option_type") or "").upper()

    @staticmethod
    def _expiry(row: Mapping[str, Any]) -> str:
        return str(row.get("SM_EXPIRY_DATE") or row.get("expiry") or "")

    @staticmethod
    def _strike(row: Mapping[str, Any]) -> Optional[float]:
        try:
            value = float(row.get("STRIKE_PRICE", row.get("strike")))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _positive_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0

    @classmethod
    def _first_expiry(
        cls, rows: Iterable[Mapping[str, Any]], session_date: str | None
    ) -> Optional[str]:
        session = cls._date(session_date) if session_date else None
        candidates = [
            (parsed, raw)
            for row in rows
            if (raw := cls._expiry(row)) and (parsed := cls._date(raw))
            and (session is None or parsed >= session)
        ]
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    @staticmethod
    def _date(value: str | None) -> Optional[date]:
        if not value:
            return None
        for pattern in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(value), pattern).date()
            except ValueError:
                continue
        return None
