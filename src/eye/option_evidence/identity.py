"""Exact Option Contract Identity & Key Generation for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from decimal import Decimal
from src.eye.contracts import PriceAtom, canonical_json, compute_sha256
from src.eye.option_evidence.sources import SourceType


def generate_contract_key(
    exchange: str,
    segment: str,
    security_id: str,
    underlying_instrument_key: str,
    expiry_date: date,
    strike: PriceAtom,
    option_type: str,
    derivative_instrument_type: str,
) -> str:
    """Generate stable semantic option contract key."""
    raw = (
        f"OPTCONTRACT:{exchange.upper()}:{segment.upper()}:{security_id.strip()}:"
        f"{underlying_instrument_key.strip()}:{expiry_date.isoformat()}:"
        f"{strike.ticks}:{option_type.upper()}:{derivative_instrument_type.upper()}"
    )
    return raw


def generate_identity_record_id(
    contract_key: str,
    metadata_revision: int,
    tick_size: PriceAtom,
    lot_size: int,
    expiry_class: str,
    source_revision: int,
    effective_time: datetime,
) -> str:
    """Generate immutable metadata record ID."""
    eff_iso = effective_time.isoformat() if effective_time else "NONE"
    payload = {
        "contract_key": contract_key,
        "metadata_revision": metadata_revision,
        "tick_size_ticks": tick_size.ticks if tick_size else 0,
        "lot_size": lot_size,
        "expiry_class": expiry_class.upper() if expiry_class else "UNKNOWN",
        "source_revision": source_revision,
        "effective_time": eff_iso,
    }
    hash_hex = compute_sha256(canonical_json(payload))[:16]
    return f"OPTREC:{hash_hex}"


@dataclass(frozen=True)
class OptionContractIdentity:
    schema_version: str
    contract_key: str
    identity_record_id: str
    metadata_revision: int
    exchange: str
    segment: str
    security_id: str
    underlying_security_id: str
    underlying_symbol: str
    underlying_instrument_key: str
    derivative_instrument_type: str
    option_type: str  # CE or PE
    expiry_date: date
    expiry_timestamp: datetime
    expiry_class: str  # WEEKLY, MONTHLY, QUARTERLY, OTHER, UNKNOWN
    strike: PriceAtom
    tick_size: PriceAtom
    lot_size: int
    currency: str
    settlement_style: str
    exercise_style: str
    source: SourceType
    source_revision: int
    effective_time: datetime
    identity_epoch: int
    display_name: str

    @property
    def strike_price(self) -> float:
        return self.strike.ticks / 100.0


    @classmethod
    def create(
        cls,
        exchange: str,
        segment: str,
        security_id: str,
        underlying_security_id: str,
        underlying_symbol: str,
        underlying_instrument_key: str,
        derivative_instrument_type: str,
        option_type: str,
        expiry_date: date,
        expiry_timestamp: datetime,
        expiry_class: str,
        strike: PriceAtom,
        tick_size: PriceAtom,
        lot_size: int,
        source: SourceType | str,
        effective_time: datetime,
        metadata_revision: int = 1,
        currency: str = "INR",
        settlement_style: str = "CASH",
        exercise_style: str = "EUROPEAN",
        source_revision: int = 1,
        identity_epoch: int = 1,
        display_name: str = "",
    ) -> "OptionContractIdentity":
        if not security_id or str(security_id).strip() == "":
            raise ValueError("SECURITY_ID_MISMATCH: security_id must be non-empty string")
        if lot_size is None or lot_size <= 0:
            raise ValueError(f"LOT_SIZE_UNRESOLVED: lot_size must be positive integer, got {lot_size}")
        if tick_size is None or tick_size.ticks <= 0:
            raise ValueError(f"TICK_SIZE_UNRESOLVED: tick_size must be positive PriceAtom, got {tick_size}")
        if expiry_date is None:
            raise ValueError("EXPIRY_UNRESOLVED: expiry_date is required")
        if strike is None or strike.ticks <= 0:
            raise ValueError(f"STRIKE_UNRESOLVED: strike must be positive PriceAtom, got {strike}")

        src_enum = SourceType(source) if isinstance(source, str) else source
        opt_type = option_type.upper()
        if opt_type not in ("CE", "PE"):
            raise ValueError(f"Invalid option_type: {option_type}. Must be CE or PE.")

        ckey = generate_contract_key(
            exchange=exchange,
            segment=segment,
            security_id=security_id,
            underlying_instrument_key=underlying_instrument_key,
            expiry_date=expiry_date,
            strike=strike,
            option_type=opt_type,
            derivative_instrument_type=derivative_instrument_type,
        )

        rec_id = generate_identity_record_id(
            contract_key=ckey,
            metadata_revision=metadata_revision,
            tick_size=tick_size,
            lot_size=lot_size,
            expiry_class=expiry_class,
            source_revision=source_revision,
            effective_time=effective_time,
        )

        strike_price_str = f"{strike.ticks / 100:.2f}"

        return cls(
            schema_version="1.0.0",
            contract_key=ckey,
            identity_record_id=rec_id,
            metadata_revision=metadata_revision,
            exchange=exchange.upper(),
            segment=segment.upper(),
            security_id=str(security_id),
            underlying_security_id=str(underlying_security_id),
            underlying_symbol=underlying_symbol.upper(),
            underlying_instrument_key=underlying_instrument_key,
            derivative_instrument_type=derivative_instrument_type.upper(),
            option_type=opt_type,
            expiry_date=expiry_date,
            expiry_timestamp=expiry_timestamp,
            expiry_class=expiry_class.upper(),
            strike=strike,
            tick_size=tick_size,
            lot_size=lot_size,
            currency=currency,
            settlement_style=settlement_style,
            exercise_style=exercise_style,
            source=src_enum,
            source_revision=source_revision,
            effective_time=effective_time,
            identity_epoch=identity_epoch,
            display_name=display_name or f"{underlying_symbol} {expiry_date} {strike_price_str} {opt_type}",
        )
