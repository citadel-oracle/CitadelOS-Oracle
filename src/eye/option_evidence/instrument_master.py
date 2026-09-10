"""Instrument Master Registry & Contract Metadata Management for Eye Engine Phase E4A."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.sources import SourceType


class InstrumentMasterRegistry:
    def __init__(self):
        self._by_security_id: Dict[str, OptionContractIdentity] = {}
        self._by_contract_key: Dict[str, OptionContractIdentity] = {}

    def register(self, identity: OptionContractIdentity):
        self._by_security_id[identity.security_id] = identity
        self._by_contract_key[identity.contract_key] = identity

    def get_by_security_id(self, security_id: str) -> Optional[OptionContractIdentity]:
        return self._by_security_id.get(str(security_id))

    def get_by_contract_key(self, contract_key: str) -> Optional[OptionContractIdentity]:
        return self._by_contract_key.get(contract_key)

    def resolve_option_contract(
        self,
        underlying_symbol: str,
        expiry_date: date,
        strike: PriceAtom,
        option_type: str,
        exchange: str = "NSE",
        segment: str = "NSE_FO",
    ) -> Optional[OptionContractIdentity]:
        """Lookup active contract identity matching underlying, expiry, strike, and option_type."""
        symbol = underlying_symbol.upper()
        opt_type = option_type.upper()
        for cid in self._by_contract_key.values():
            if (
                cid.underlying_symbol == symbol
                and cid.expiry_date == expiry_date
                and cid.strike.ticks == strike.ticks
                and cid.option_type == opt_type
                and cid.exchange == exchange.upper()
            ):
                return cid
        return None
