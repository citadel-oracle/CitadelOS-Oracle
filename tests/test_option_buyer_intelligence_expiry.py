from src.oracle.option_buyer_intelligence import OptionBuyerIntelligenceWorker
from tests.test_option_buyer_intelligence import _inputs


def test_valid_monthly_future_weekly_options():
    argus, vob = _inputs()
    # Monthly futures
    argus["data"]["futures"]["expiry"] = "2026-09-29"
    # Weekly options
    argus["data"]["underlying"]["expiry"] = "2026-09-03"
    for r in argus["data"]["atm_window"]:
        r["ce"]["expiry"] = "2026-09-03"
        r["pe"]["expiry"] = "2026-09-03"
    vob["current_itm1_contracts"]["CE"]["contract"]["expiry"] = "2026-09-03"
    vob["current_itm1_contracts"]["PE"]["contract"]["expiry"] = "2026-09-03"
    
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is True
    assert output["PE"]["quality"]["valid"] is True
    assert output["straddle"]["now"] is not None


def test_wrong_option_expiry():
    argus, vob = _inputs()
    # ITM1 contract has wrong expiry
    vob["current_itm1_contracts"]["CE"]["contract"]["expiry"] = "2026-09-10"
    argus["data"]["underlying"]["expiry"] = "2026-09-03"
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is False


def test_ce_pe_expiry_disagreement():
    argus, vob = _inputs()
    vob["current_itm1_contracts"]["CE"]["contract"]["expiry"] = "2026-09-03"
    vob["current_itm1_contracts"]["PE"]["contract"]["expiry"] = "2026-09-10"
    argus["data"]["underlying"]["expiry"] = "2026-09-03"
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["PE"]["quality"]["valid"] is False


def test_stale_future_identity():
    argus, vob = _inputs()
    argus["data"]["futures"]["expiry"] = None
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is False


def test_contract_rotation():
    argus, vob = _inputs()
    vob["current_itm1_contracts"]["CE"]["contract"]["expiry"] = "2026-08-27"
    argus["data"]["underlying"]["expiry"] = "2026-09-03"
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is False
    assert output["CE"]["quality"]["reason"] == "MODEL_INPUT_UNAVAILABLE"
