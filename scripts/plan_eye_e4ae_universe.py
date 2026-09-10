"""Plan & Inspect Dynamic NIFTY Option Universe for Phase E4A-E."""

from datetime import datetime, date, timezone
from src.eye.option_capture.universe import UniverseManager, ResearchCoveragePolicy
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def plan_universe():
    print("=== PHASE E4A-E: UNIVERSE PLANNING ===")
    policy = ResearchCoveragePolicy(underlying_symbol="NIFTY", strike_interval_count=10, strike_step=50.0, horizon_days=30)
    mgr = UniverseManager(policy)

    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    exp = date(2026, 8, 13)

    contracts = {}
    # Build 21 strikes (ATM +/- 10 intervals around 24500)
    for strike in range(24000, 25050, 50):
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
    ce_count = len([k for k in rev.active_contract_keys if ":CE" in k])
    pe_count = len([k for k in rev.active_contract_keys if ":PE" in k])

    print(f"Planned Universe Revision #{rev.revision_number}:")
    print(f"  Underlying Price: {rev.underlying_price}")
    print(f"  Total Active Contracts: {len(rev.active_contract_keys)}")
    print(f"  CE Contracts: {ce_count} | PE Contracts: {pe_count}")
    print(f"  Label: {rev.label}")
    return "PASS"


if __name__ == "__main__":
    plan_universe()
