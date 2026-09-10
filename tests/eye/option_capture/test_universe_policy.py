"""E4A-E Test for Dynamic Research Universe Policy & Manager."""

from datetime import datetime, date, timezone
import pytest
from src.eye.option_capture.universe import UniverseManager, ResearchCoveragePolicy
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_universe_manager_filters_around_spot():
    policy = ResearchCoveragePolicy(strike_interval_count=2, strike_step=50.0)
    mgr = UniverseManager(policy)
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    exp = date(2026, 8, 13)

    contracts = {}
    for strike in [24400, 24450, 24500, 24550, 24600, 24650, 24700]:
        for opt in ["CE", "PE"]:
            cid = OptionContractIdentity.create(
                exchange="NSE", segment="NSE_FO", security_id=f"SEC:{strike}:{opt}",
                underlying_security_id="13", underlying_symbol="NIFTY",
                underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
                derivative_instrument_type="OPTIDX", option_type=opt,
                expiry_date=exp, expiry_timestamp=datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc),
                expiry_class="WEEKLY", strike=PriceAtom(ticks=strike * 100),
                tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
                effective_time=now,
            )
            contracts[cid.contract_key] = cid

    rev = mgr.update_universe(24500.0, contracts, [exp], now)

    assert rev.revision_number == 1
    # 5 strikes (24400, 24450, 24500, 24550, 24600) * 2 options = 10 active contracts
    assert len(rev.active_contract_keys) == 10
