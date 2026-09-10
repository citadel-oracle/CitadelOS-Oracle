"""Deterministic Decimal slippage and versioned cost estimation contracts."""

from decimal import Decimal
from typing import Any, Mapping, Optional

from .models import decimal_value

DEFAULT_COST_SCHEDULE = {
    "schedule_id": "CITADEL_ESTIMATE_V1",
    "version": 1,
    "effective_from": "2026-01-01",
    "status": "ESTIMATED",
    "brokerage_flat": "0",
    "transaction_rate": "0",
    "tax_rate": "0",
    "other_rate": "0",
    "accuracy_claim": "NOT_REGULATORY_OR_BROKER_RECONCILED",
}


def select_reference_price(side: str, quote: Mapping[str, Any]) -> tuple[Optional[Decimal], str]:
    side_key = "ask" if side == "BUY" else "bid"
    for key, label in ((side_key, side_key.upper()), ("mid", "MID"), ("ltp", "LTP")):
        value = quote.get(key)
        if value is not None:
            try: return decimal_value(value, key, positive=True), label
            except ValueError: continue
    return None, "UNAVAILABLE"


def slippage(side: str, fill_price: Any, reference_price: Any | None, reference_source: str) -> dict:
    if reference_price is None:
        return {"status": "UNAVAILABLE", "reference_price": None, "reference_source": "UNAVAILABLE", "per_unit": None, "total": None}
    fill = decimal_value(fill_price, "fill_price", positive=True)
    reference = decimal_value(reference_price, "reference_price", positive=True)
    per_unit = fill - reference if side == "BUY" else reference - fill
    return {"status": "CALCULATED", "reference_price": format(reference, "f"), "reference_source": reference_source, "per_unit": format(per_unit, "f")}


def costs(quantity: int, price: Any, schedule: Optional[Mapping[str, Any]] = None) -> dict:
    rule = dict(DEFAULT_COST_SCHEDULE if schedule is None else schedule)
    if rule.get("status") == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "schedule": rule, "items": {}, "total": None}
    notional = decimal_value(price, "price", positive=True) * quantity
    brokerage = decimal_value(rule.get("brokerage_flat", "0"), "brokerage_flat")
    transaction = notional * decimal_value(rule.get("transaction_rate", "0"), "transaction_rate")
    taxes = notional * decimal_value(rule.get("tax_rate", "0"), "tax_rate")
    other = notional * decimal_value(rule.get("other_rate", "0"), "other_rate")
    items = {"brokerage": brokerage, "transaction_charges": transaction, "taxes": taxes, "other": other}
    return {"status": str(rule.get("status") or "ESTIMATED"), "schedule": rule, "notional": format(notional, "f"), "items": {key: format(value, "f") for key, value in items.items()}, "total": format(sum(items.values(), Decimal("0")), "f")}
