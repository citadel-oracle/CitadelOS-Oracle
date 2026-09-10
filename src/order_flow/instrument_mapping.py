"""Explicit Instrument Identity Mapping Layer.

Maintains bidirectional, exact mapping between:
CANONICAL CITADEL INSTRUMENT <-> Dhan security_id <-> Upstox instrument_key.

Preserves exact contract continuity for NIFTY derivatives (underlying, segment,
expiry, strike, option_type) and prevents synthetic role-stitching across rollovers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.order_flow.contracts import InstrumentIdentity

logger = logging.getLogger(__name__)

# Fixed Canonical Index Instruments
CANONICAL_INDICES: Dict[str, Dict[str, Any]] = {
    "NIFTY_SPOT": {
        "symbol": "NIFTY",
        "name": "Nifty 50 Index",
        "dhan_segment": "IDX_I",
        "dhan_security_id": "13",
        "upstox_key": "NSE_INDEX|Nifty 50",
        "is_index": True,
        "is_global": False,
    },
    "BANKNIFTY_SPOT": {
        "symbol": "BANKNIFTY",
        "name": "Nifty Bank Index",
        "dhan_segment": "IDX_I",
        "dhan_security_id": "25",
        "upstox_key": "NSE_INDEX|Nifty Bank",
        "is_index": True,
        "is_global": False,
    },
    "MIDCPNIFTY_SPOT": {
        "symbol": "MIDCPNIFTY",
        "name": "Nifty Midcap Select",
        "dhan_segment": "IDX_I",
        "dhan_security_id": "442",
        "upstox_key": "NSE_INDEX|NIFTY MID SELECT",
        "is_index": True,
        "is_global": False,
    },
    "INDIA_VIX": {
        "symbol": "INDIA_VIX",
        "name": "India Volatility Index",
        "dhan_segment": "IDX_I",
        "dhan_security_id": "15",  # Dhan India VIX index ID
        "upstox_key": "NSE_INDEX|India VIX",
        "is_index": True,
        "is_global": False,
    },
    "GIFT_NIFTY": {
        "symbol": "GIFT_NIFTY",
        "name": "GIFT Nifty Global Index",
        "dhan_segment": "GLOBAL",
        "dhan_security_id": "GIFT_NIFTY",
        "upstox_key": "GLOBAL_INDEX|SGX NIFTY",
        "is_index": True,
        "is_global": True,
        "declared_refresh_seconds": 120,
    },
    "SP500": {
        "symbol": "SP500",
        "name": "S&P 500 Global Index",
        "dhan_segment": "GLOBAL",
        "dhan_security_id": "SP500",
        "upstox_key": "GLOBAL_INDEX|^GSPC",
        "is_index": True,
        "is_global": True,
        "declared_refresh_seconds": 20,
    },
    "DOW_JONES": {
        "symbol": "DOW_JONES",
        "name": "Dow Jones Industrial Average",
        "dhan_segment": "GLOBAL",
        "dhan_security_id": "DJIA",
        "upstox_key": "GLOBAL_INDEX|^DJI",
        "is_index": True,
        "is_global": True,
        "declared_refresh_seconds": 20,
    },
    "US_TECH_100": {
        "symbol": "US_TECH_100",
        "name": "US Tech 100 Index",
        "dhan_segment": "GLOBAL",
        "dhan_security_id": "USTECH100",
        "upstox_key": "GLOBAL_INDEX|IXIX",
        "is_index": True,
        "is_global": True,
        "declared_refresh_seconds": 20,
    },
    "NIKKEI_225": {
        "symbol": "NIKKEI_225",
        "name": "Nikkei 225 Global Index",
        "dhan_segment": "GLOBAL",
        "dhan_security_id": "N225",
        "upstox_key": "GLOBAL_INDEX|^N225",
        "is_index": True,
        "is_global": True,
        "declared_refresh_seconds": 900,
    },
}


@dataclass(frozen=True, slots=True)
class CanonicalInstrument:
    canonical_id: str
    symbol: str
    role: str
    segment: str  # "NSE_INDEX", "NSE_FNO", "GLOBAL_INDEX"
    expiry: Optional[str]
    strike: Optional[float]
    option_type: Optional[str]  # "CE", "PE", or None
    dhan_segment: Optional[str]
    dhan_security_id: Optional[str]
    upstox_key: Optional[str]
    trading_symbol: Optional[str] = None


class InstrumentMappingRegistry:
    """Authoritative bidirectional mapping registry."""

    def __init__(self) -> None:
        self._canonical_by_id: Dict[str, CanonicalInstrument] = {}
        self._upstox_to_canonical: Dict[str, CanonicalInstrument] = {}
        self._dhan_to_canonical: Dict[Tuple[str, str], CanonicalInstrument] = {}
        self._derivative_spec_to_upstox: Dict[Tuple[str, str, float, str], str] = {}
        self._derivative_spec_to_dhan: Dict[Tuple[str, str, float, str], Tuple[str, str]] = {}
        self._futures_spec_to_upstox: Dict[Tuple[str, str], str] = {}
        self._futures_spec_to_dhan: Dict[Tuple[str, str], Tuple[str, str]] = {}
        self._init_fixed_indices()

    def _init_fixed_indices(self) -> None:
        for role, spec in CANONICAL_INDICES.items():
            inst = CanonicalInstrument(
                canonical_id=f"INDEX:{spec['symbol']}",
                symbol=spec["symbol"],
                role=role,
                segment="NSE_INDEX" if not spec["is_global"] else "GLOBAL_INDEX",
                expiry=None,
                strike=None,
                option_type=None,
                dhan_segment=spec["dhan_segment"],
                dhan_security_id=spec["dhan_security_id"],
                upstox_key=spec["upstox_key"],
                trading_symbol=spec["name"],
            )
            self._register_instrument(inst)

    def _register_instrument(self, inst: CanonicalInstrument) -> None:
        self._canonical_by_id[inst.canonical_id] = inst
        if inst.upstox_key:
            self._upstox_to_canonical[inst.upstox_key] = inst
        if inst.dhan_segment and inst.dhan_security_id:
            key = (str(inst.dhan_segment), str(inst.dhan_security_id))
            self._dhan_to_canonical[key] = inst

    def register_upstox_contract_metadata(self, contracts: List[Dict[str, Any]]) -> int:
        """Indexes Upstox option contracts and futures by exact derivatives spec."""
        count = 0
        for c in contracts:
            symbol = str(c.get("underlying_symbol") or c.get("name") or "NIFTY").upper()
            expiry = str(c.get("expiry") or "")
            strike = c.get("strike_price")
            opt_type = str(c.get("instrument_type") or "").upper()
            key = str(c.get("instrument_key") or "")
            if not key or not expiry:
                continue

            if opt_type in ("CE", "PE") and strike is not None:
                try:
                    strike_f = float(strike)
                    self._derivative_spec_to_upstox[(symbol, expiry, strike_f, opt_type)] = key
                    count += 1
                except (ValueError, TypeError):
                    pass
            elif opt_type in ("FUT", "FUTIDX"):
                self._futures_spec_to_upstox[(symbol, expiry)] = key
                count += 1
        logger.info("Indexed %d Upstox contract specifications in mapping registry", count)
        return count

    def map_identity(self, identity: InstrumentIdentity) -> CanonicalInstrument:
        """Converts an existing CITADEL InstrumentIdentity into a dual-mapped CanonicalInstrument."""
        role = identity.role
        sec_id = str(identity.security_id)
        seg = str(identity.exchange_segment)

        # 1. Check fixed indices
        for fixed_role, spec in CANONICAL_INDICES.items():
            if role == fixed_role or (spec["dhan_segment"] == seg and spec["dhan_security_id"] == sec_id):
                return self._canonical_by_id[f"INDEX:{spec['symbol']}"]

        # 2. Derive canonical ID based on exact contract spec
        symbol = "NIFTY"
        expiry = identity.expiry
        strike = identity.strike
        opt_type = identity.option_type

        if role == "NIFTY_FUTURE":
            cid = f"FUT:{symbol}:{expiry or 'CURR'}"
            upstox_key = self._futures_spec_to_upstox.get((symbol, str(expiry or "")))
            inst = CanonicalInstrument(
                canonical_id=cid,
                symbol=symbol,
                role=role,
                segment="NSE_FNO",
                expiry=expiry,
                strike=None,
                option_type=None,
                dhan_segment=seg,
                dhan_security_id=sec_id,
                upstox_key=upstox_key,
                trading_symbol=f"{symbol} FUT {expiry or ''}".strip(),
            )
            self._register_instrument(inst)
            return inst

        # 3. Option contract
        if strike is not None and opt_type:
            strike_f = float(strike)
            opt_type_u = str(opt_type).upper()
            cid = f"OPT:{symbol}:{expiry}:{strike_f}:{opt_type_u}"
            upstox_key = self._derivative_spec_to_upstox.get((symbol, str(expiry or ""), strike_f, opt_type_u))
            inst = CanonicalInstrument(
                canonical_id=cid,
                symbol=symbol,
                role=role,
                segment="NSE_FNO",
                expiry=expiry,
                strike=strike_f,
                option_type=opt_type_u,
                dhan_segment=seg,
                dhan_security_id=sec_id,
                upstox_key=upstox_key,
                trading_symbol=f"{symbol} {int(strike_f)} {opt_type_u} {expiry or ''}".strip(),
            )
            self._register_instrument(inst)
            return inst

        # Fallback generic
        cid = f"GENERIC:{seg}:{sec_id}"
        inst = CanonicalInstrument(
            canonical_id=cid,
            symbol=symbol,
            role=role,
            segment=seg,
            expiry=expiry,
            strike=strike,
            option_type=opt_type,
            dhan_segment=seg,
            dhan_security_id=sec_id,
            upstox_key=None,
        )
        self._register_instrument(inst)
        return inst

    def get_by_upstox_key(self, instrument_key: str) -> Optional[CanonicalInstrument]:
        canon = self._upstox_to_canonical.get(instrument_key)
        if canon is not None:
            return canon
        # Fallback 1: NSE_FO token id match
        if instrument_key.startswith("NSE_FO|"):
            sec_id = instrument_key.split("|", 1)[1]
            for seg in ("NSE_FNO", "2", 2):
                canon = self._dhan_to_canonical.get((str(seg), str(sec_id)))
                if canon is not None:
                    self._upstox_to_canonical[instrument_key] = canon
                    return canon
            # Dynamic FNO contract
            dyn = CanonicalInstrument(
                canonical_id=f"NSE_FO:{sec_id}",
                symbol="NIFTY",
                role="NIFTY_DERIVATIVE",
                segment="NSE_FNO",
                expiry=None,
                strike=None,
                option_type=None,
                dhan_segment="NSE_FNO",
                dhan_security_id=sec_id,
                upstox_key=instrument_key,
            )
            self._register_instrument(dyn)
            return dyn
        return None

    def get_by_dhan_key(self, segment: str, security_id: str) -> Optional[CanonicalInstrument]:
        return self._dhan_to_canonical.get((str(segment), str(security_id)))

    def get_upstox_keys_for_identities(self, identities: tuple[InstrumentIdentity, ...]) -> List[str]:
        """Returns all resolved Upstox instrument keys for a given basket of identities."""
        keys = []
        for ident in identities:
            inst = self.map_identity(ident)
            if inst.upstox_key:
                keys.append(inst.upstox_key)
        return keys


# Global singleton mapping registry
instrument_mapping = InstrumentMappingRegistry()
