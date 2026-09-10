"""Option Observation Universe & Research Data Coverage Policy for Eye Engine Phase E4A."""

from dataclasses import dataclass
from typing import List, Dict, Set
from src.eye.option_evidence.identity import OptionContractIdentity


@dataclass(frozen=True)
class OptionObservationUniverse:
    policy_name: str = "RESEARCH_DATA_COVERAGE_POLICY"
    underlying_symbol: str = "NIFTY"
    horizon_days: int = 30
    strike_interval_count: int = 10
    active_contracts: List[OptionContractIdentity] = ()
    inclusion_reasons: Dict[str, str] = ()

    def contains_contract(self, contract_key: str) -> bool:
        return any(c.contract_key == contract_key for c in self.active_contracts)
