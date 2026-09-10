"""Dynamic Research Contract Universe Manager for Eye Engine Option Capture."""

import json
import hashlib
from datetime import datetime, date, timezone
from dataclasses import dataclass, asdict
from typing import Dict, List, Set, Tuple, Optional

from src.eye.option_evidence.identity import OptionContractIdentity


@dataclass
class ResearchCoveragePolicy:
    underlying_symbol: str = "NIFTY"
    strike_interval_count: int = 10
    strike_step: float = 50.0
    horizon_days: int = 30
    include_ce: bool = True
    include_pe: bool = True

    def fingerprint(self) -> str:
        s = f"{self.underlying_symbol}:{self.strike_interval_count}:{self.strike_step}:{self.horizon_days}:{self.include_ce}:{self.include_pe}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class UniverseRevision:
    revision_number: int
    reason: str
    effective_at_utc: str
    underlying_price: float
    active_contract_keys: List[str]
    added_contract_keys: List[str]
    removed_contract_keys: List[str]
    fingerprint: str
    label: str = "CAPTURED_FOR_RESEARCH_COVERAGE"


class UniverseManager:
    def __init__(self, policy: ResearchCoveragePolicy):
        self.policy = policy
        self.active_universe: Dict[str, OptionContractIdentity] = {}
        self.revisions: List[UniverseRevision] = []
        self.current_revision_number: int = 0

    def update_universe(
        self,
        spot_price: float,
        all_contracts: Dict[str, OptionContractIdentity],
        valid_expiries: List[date],
        as_of: datetime,
        reason: str = "SPOT_MOVED",
    ) -> UniverseRevision:
        """Computes active research contract universe around spot_price and produces a new UniverseRevision."""
        today = as_of.date()
        cutoff_date = date.fromordinal(today.toordinal() + self.policy.horizon_days)

        active_expiries = [e for e in valid_expiries if today <= e <= cutoff_date]
        if not active_expiries and valid_expiries:
            # Fallback to nearest expiry
            future_expiries = [e for e in valid_expiries if e >= today]
            if future_expiries:
                active_expiries = [future_expiries[0]]

        # Round spot price to nearest strike step (50 points)
        atm_strike = round(spot_price / self.policy.strike_step) * self.policy.strike_step
        min_strike = atm_strike - (self.policy.strike_interval_count * self.policy.strike_step)
        max_strike = atm_strike + (self.policy.strike_interval_count * self.policy.strike_step)

        new_universe: Dict[str, OptionContractIdentity] = {}
        for key, cid in all_contracts.items():
            if cid.expiry_date in active_expiries:
                if min_strike <= cid.strike_price <= max_strike:
                    if (cid.option_type == "CE" and self.policy.include_ce) or (cid.option_type == "PE" and self.policy.include_pe):
                        new_universe[key] = cid

        old_keys = set(self.active_universe.keys())
        new_keys = set(new_universe.keys())

        added = sorted(list(new_keys - old_keys))
        removed = sorted(list(old_keys - new_keys))

        if added or removed or not self.revisions:
            self.current_revision_number += 1
            self.active_universe = new_universe
            active_list = sorted(list(new_keys))
            raw_str = f"{self.current_revision_number}:{spot_price}:{active_list}"
            fp = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

            rev = UniverseRevision(
                revision_number=self.current_revision_number,
                reason=reason if self.revisions else "INITIAL_CREATION",
                effective_at_utc=as_of.isoformat(),
                underlying_price=spot_price,
                active_contract_keys=active_list,
                added_contract_keys=added,
                removed_contract_keys=removed,
                fingerprint=fp,
            )
            self.revisions.append(rev)
            return rev

        return self.revisions[-1]
