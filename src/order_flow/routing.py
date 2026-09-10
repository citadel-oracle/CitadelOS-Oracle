"""Pure instrument-basket routing from the existing canonical ARGUS projection."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .contracts import InstrumentIdentity


def basket_from_argus(projection: Mapping[str, Any] | None) -> tuple[InstrumentIdentity, ...]:
    """Resolve NIFTY future and ATM±2 option identities without provider I/O."""

    if not isinstance(projection, Mapping):
        return ()
    data = projection.get("data") if isinstance(projection.get("data"), Mapping) else {}
    underlying = data.get("underlying") if isinstance(data.get("underlying"), Mapping) else {}
    futures = data.get("futures") if isinstance(data.get("futures"), Mapping) else {}
    expiry = str(underlying.get("expiry") or "") or None
    futures_expiry = str(futures.get("expiry") or "") or None
    try:
        if date.fromisoformat(str(expiry)) < date.today() or date.fromisoformat(str(futures_expiry)) < date.today():
            return ()
    except ValueError:
        return ()
    atm = _number(underlying.get("atm_strike"))
    rows = [row for row in data.get("atm_window") or [] if isinstance(row, Mapping)]
    if atm is None or not expiry or futures.get("security_id") is None:
        return ()
    strikes = sorted({_number(row.get("strike")) for row in rows} - {None})
    if atm not in strikes:
        return ()
    center = strikes.index(atm)
    wanted = set(strikes[max(0, center - 2): center + 3])
    if len(wanted) != 5:
        return ()
    identities = [
        InstrumentIdentity(
            exchange_segment=str(futures.get("segment") or "NSE_FNO"),
            security_id=str(futures["security_id"]),
            role="NIFTY_FUTURE",
            expiry=str(futures.get("expiry") or "") or None,
        )
    ]
    for row in rows:
        strike = _number(row.get("strike"))
        if strike not in wanted:
            continue
        offset = strikes.index(strike) - center
        label = "ATM" if offset == 0 else f"ATM{offset:+d}"
        for side in ("CE", "PE"):
            leg = row.get(side.lower())
            if not isinstance(leg, Mapping) or leg.get("security_id") is None:
                return ()
            identities.append(
                InstrumentIdentity(
                    exchange_segment="NSE_FNO",
                    security_id=str(leg["security_id"]),
                    role=f"{label}_{side}",
                    expiry=expiry,
                    strike=strike,
                    option_type=side,
                )
            )
    return tuple(identities) if len(identities) == 11 else ()


def gateway_instruments(identities: tuple[InstrumentIdentity, ...]) -> list[dict[str, Any]]:
    return [
        {
            "exchange_segment": item.exchange_segment,
            "security_id": item.security_id,
            "role": item.role,
            "expiry": item.expiry,
            "strike": item.strike,
            "option_type": item.option_type,
        }
        for item in identities
    ]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None
