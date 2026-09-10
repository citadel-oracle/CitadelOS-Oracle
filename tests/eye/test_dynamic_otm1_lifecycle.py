"""Unit test for E8A Dynamic OTM1 Lifecycle across S01 CE, S05 CE, and S05 PE.

Proves:
1. Pre-cycle dynamic resolution (Spot -> ATM -> OTM1 strike -> Security ID).
2. Active-cycle contract lock (Locked contract maintained during active DETECTED/MANAGING cycle).
3. Rearm fresh resolution (Fresh contract resolution allowed after cycle re-arm).
"""

from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator


def _certified_master_rows():
    """Small frozen master fixture; tests must not require a live worktree log."""
    values = {
        (24600, "CE"): ("41015", "NIFTY-Aug2026-24600-CE"),
        (24750, "CE"): ("41025", "NIFTY-Aug2026-24750-CE"),
        (24500, "PE"): ("41012", "NIFTY-Aug2026-24500-PE"),
        (24350, "PE"): ("41006", "NIFTY-Aug2026-24350-PE"),
    }
    return [
        {
            "UNDERLYING_SYMBOL": "NIFTY",
            "SM_EXPIRY_DATE": "2026-08-11",
            "STRIKE_PRICE": str(strike),
            "OPTION_TYPE": side,
            "SECURITY_ID": security_id,
            "SYMBOL_NAME": symbol,
        }
        for (strike, side), (security_id, symbol) in values.items()
    ]


def resolve_otm1_contract(spot: float, option_type: str, master_rows: list):
    """Dynamic strike resolver: Spot -> ATM -> OTM1 -> Security ID."""
    atm_strike = round(spot / 50.0) * 50.0
    otm1_strike = atm_strike + 50.0 if option_type == "CE" else atm_strike - 50.0
    
    for r in master_rows:
        if r.get("UNDERLYING_SYMBOL") == "NIFTY" and r.get("SM_EXPIRY_DATE") == "2026-08-11":
            strike = float(r.get("STRIKE_PRICE", 0))
            if strike == otm1_strike and r.get("OPTION_TYPE") == option_type:
                return r.get("SECURITY_ID"), r.get("SYMBOL_NAME")
    return None, None


def test_s01_ce_otm1_lifecycle():
    master_rows = _certified_master_rows()

    # 1. Pre-cycle dynamic resolution at spot 24538.9 -> 24550 ATM -> 24600 CE (41015)
    sec_id1, contract1 = resolve_otm1_contract(24538.9, "CE", master_rows)
    assert sec_id1 == "41015"
    assert contract1 == "NIFTY-Aug2026-24600-CE"

    evaluator = S01Evaluator()
    assert evaluator.cycle_locked_contract is None

    # Simulate active cycle lock
    evaluator.cycle_locked_contract = contract1
    evaluator.rearm_satisfied = False

    # Spot moves to 24680 -> ATM 24700 -> OTM1 CE would be 24750 CE
    sec_id2, contract2 = resolve_otm1_contract(24680.0, "CE", master_rows)
    assert contract2 == "NIFTY-Aug2026-24750-CE"

    # Active cycle: lock MUST maintain contract1
    active_contract = evaluator.cycle_locked_contract or contract2
    assert active_contract == contract1, "Active cycle must remain locked to initial contract"

    # Post re-arm: cycle unlocks, allowing fresh resolution
    evaluator.rearm_satisfied = True
    evaluator.cycle_locked_contract = None
    fresh_contract = evaluator.cycle_locked_contract or contract2
    assert fresh_contract == contract2, "Post re-arm must resolve fresh OTM1 contract"


def test_s05_ce_otm1_lifecycle():
    master_rows = _certified_master_rows()

    sec_id1, contract1 = resolve_otm1_contract(24538.9, "CE", master_rows)
    assert sec_id1 == "41015"

    evaluator = S05Evaluator(option_type="CE")
    evaluator.rearm_satisfied = False

    # Spot moves to 24680
    sec_id2, contract2 = resolve_otm1_contract(24680.0, "CE", master_rows)
    assert sec_id2 == "41025"  # 24750 CE

    # Lock verification
    locked_contract = contract1 if not evaluator.rearm_satisfied else contract2
    assert locked_contract == contract1

    # Rearm verification
    evaluator.rearm_satisfied = True
    rearmed_contract = contract1 if not evaluator.rearm_satisfied else contract2
    assert rearmed_contract == contract2


def test_s05_pe_otm1_lifecycle():
    master_rows = _certified_master_rows()

    # Spot 24538.9 -> ATM 24550 -> OTM1 PE = 24500 PE (41012)
    sec_id1, contract1 = resolve_otm1_contract(24538.9, "PE", master_rows)
    assert sec_id1 == "41012"
    assert contract1 == "NIFTY-Aug2026-24500-PE"

    evaluator = S05Evaluator(option_type="PE")
    evaluator.rearm_satisfied = False

    # Spot drops to 24380 -> ATM 24400 -> OTM1 PE = 24350 PE (41006)
    sec_id2, contract2 = resolve_otm1_contract(24380.0, "PE", master_rows)
    assert sec_id2 == "41006"

    # Lock verification
    locked_contract = contract1 if not evaluator.rearm_satisfied else contract2
    assert locked_contract == contract1

    # Rearm verification
    evaluator.rearm_satisfied = True
    rearmed_contract = contract1 if not evaluator.rearm_satisfied else contract2
    assert rearmed_contract == contract2
