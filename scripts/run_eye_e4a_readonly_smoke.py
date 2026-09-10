"""Read-Only Smoke Test for Citadel Eye Engine Phase E4A."""

import json
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.instrument_master import InstrumentMasterRegistry
from src.eye.option_evidence.exact_history_adapter import ExactHistoryAdapter
from src.eye.contracts import PriceAtom


def run_smoke():
    print("=== PHASE E4A: READ-ONLY SMOKE TEST ===")
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    reg = InstrumentMasterRegistry()
    reg.register(cid)

    adapter = ExactHistoryAdapter()
    obs = adapter.parse_historical_candle(cid, now, 150.0, 152.0, 149.0, 150.5)

    print(f"Contract Key: {cid.contract_key}")
    print(f"Identity Record ID: {cid.identity_record_id}")
    print(f"Observation ID: {obs.observation_id}")
    print("Smoke test PASSED cleanly!")


if __name__ == "__main__":
    run_smoke()
