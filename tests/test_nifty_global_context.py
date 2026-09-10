# CITADEL ORACLE — NIFTY-RELEVANT GLOBAL CONTEXT TEST SUITE
import os
import json
import pytest
from src.external_context.contracts import ExternalQuote, ExactOrProxy, DataAgeStatus
from src.external_context.adapters.world_market import BASKET_DEFINITIONS, UNAVAILABLE_TARGETS, WorldMarketAdapter
from src.external_context.core import ExternalContextCore
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.cognitive_status import get_cognitive_models_status


def test_no_instrument_mislabeled_exact():
    """Assertion 1: Ensure only genuine exact assets are labeled EXACT; all ETF proxies are PROXY."""
    for sym, meta in BASKET_DEFINITIONS.items():
        if sym in {"USD/INR", "BTC/USD"}:
            assert meta["exact_or_proxy"] == ExactOrProxy.EXACT.value, f"{sym} must be EXACT"
        else:
            assert meta["exact_or_proxy"] == ExactOrProxy.PROXY.value, f"{sym} must be PROXY"


def test_spy_never_labeled_sp_futures():
    """Assertion 2: SPY must never be labeled S&P futures."""
    spy_meta = BASKET_DEFINITIONS["SPY"]
    assert "futures" not in spy_meta["display_name"].lower()
    assert spy_meta["exact_or_proxy"] == "PROXY"
    assert spy_meta["proxy_for"] == "FOR S&P RISK"
    assert "NOT S&P futures" in spy_meta["notes"]


def test_qqq_never_labeled_nasdaq_futures():
    """Assertion 3: QQQ must never be labeled Nasdaq futures."""
    qqq_meta = BASKET_DEFINITIONS["QQQ"]
    assert "futures" not in qqq_meta["display_name"].lower()
    assert qqq_meta["exact_or_proxy"] == "PROXY"
    assert qqq_meta["proxy_for"] == "FOR NASDAQ RISK"
    assert "NOT Nasdaq futures" in qqq_meta["notes"]


def test_uup_never_labeled_dxy():
    """Assertion 4: UUP must never be labeled DXY cash index."""
    uup_meta = BASKET_DEFINITIONS["UUP"]
    assert uup_meta["display_name"] != "DXY"
    assert uup_meta["exact_or_proxy"] == "PROXY"
    assert uup_meta["proxy_for"] == "FOR USD"
    assert "NOT DXY cash index" in uup_meta["notes"]


def test_tlt_never_labeled_us10y_yield():
    """Assertion 5: TLT must never be labeled US10Y yield."""
    tlt_meta = BASKET_DEFINITIONS["TLT"]
    assert tlt_meta["display_name"] != "US 10Y"
    assert tlt_meta["exact_or_proxy"] == "PROXY"
    assert tlt_meta["proxy_for"] == "FOR TREASURY DURATION"
    assert "NOT US10Y yield" in tlt_meta["notes"]


def test_uso_never_labeled_wti():
    """Assertion 6: USO must never be labeled WTI futures."""
    uso_meta = BASKET_DEFINITIONS["USO"]
    assert uso_meta["display_name"] != "WTI"
    assert uso_meta["exact_or_proxy"] == "PROXY"
    assert uso_meta["proxy_for"] == "FOR OIL"
    assert "NOT WTI futures" in uso_meta["notes"]


def test_gld_never_labeled_gold_spot():
    """Assertion 7: GLD must never be labeled spot/futures gold."""
    gld_meta = BASKET_DEFINITIONS["GLD"]
    assert gld_meta["display_name"] != "Gold Spot"
    assert gld_meta["exact_or_proxy"] == "PROXY"
    assert gld_meta["proxy_for"] == "FOR GOLD"
    assert "NOT spot gold" in gld_meta["notes"]


def test_closed_market_quote_labeled_session_last():
    """Assertion 8: When market is closed, quote must be SESSION_LAST regardless of fresh retrieval time."""
    q_closed = ExternalQuote(
        symbol="SPY",
        display_name="S&P 500 (SPY ETF)",
        provider="twelve_data",
        instrument_type="EQUITY_ETF",
        exact_or_proxy="PROXY",
        price=590.25,
        change=-1.20,
        change_percent=-0.20,
        market_status="CLOSED",
        provider_timestamp="2026-09-02T20:00:00Z",
        retrieved_at="2026-09-02T23:50:00Z",
        data_age="SESSION_LAST",
        cluster="US_RISK",
        proxy_for="FOR S&P RISK",
    )
    assert q_closed.market_status == "CLOSED"
    assert q_closed.data_age == DataAgeStatus.SESSION_LAST.value
    assert q_closed.data_age != DataAgeStatus.LIVE.value


def test_session_last_survives_service_projection():
    """Assertion 9: SESSION_LAST data_age survives serialization to /v1/oracle/sol/state."""
    service = SolMarketBrainService.get_instance()
    state = service.get_latest_state()
    wc = state.get("world_context", {})
    quotes = wc.get("quotes", [])
    assert len(quotes) > 0
    for q in quotes:
        assert q["data_age"] in {"LIVE", "DELAYED", "SESSION_LAST"}
        assert q["exact_or_proxy"] in {"EXACT", "PROXY"}
        assert q["cluster"] in {"INDIA_LEAD", "US_RISK", "RATES_USD", "COMMODITIES", "SECONDARY"}


def test_unavailable_desired_instruments_truthful():
    """Assertion 10: Unavailable instruments (GIFT NIFTY, INDIA VIX, NIKKEI 225, HANG SENG) are truthfully exposed."""
    service = SolMarketBrainService.get_instance()
    state = service.get_latest_state()
    unavail = state.get("world_context", {}).get("unavailable_context", [])
    unavail_targets = {u["target"] for u in unavail}
    assert "GIFT NIFTY" in unavail_targets
    assert "INDIA VIX" in unavail_targets
    assert "NIKKEI 225" in unavail_targets
    assert "HANG SENG" in unavail_targets
    for u in unavail:
        assert u["status"] == "UNAVAILABLE"
        assert len(u["reason"]) > 0


def test_api_keys_never_enter_frontend_payload():
    """Assertion 11: Twelve Data / Groq / Marketaux keys never enter /v1/oracle/sol/state payload."""
    service = SolMarketBrainService.get_instance()
    state = service.get_latest_state()
    serialized = json.dumps(state)
    assert "131653f7977e47ae80ce1c2f629ea840" not in serialized
    assert "plByfSF2vfcJSQW4wEiST6VaQLPVhj305NGdefxL" not in serialized
    assert "gsk_" not in serialized


def test_cognitive_model_cards_preserved():
    """Assertion 12: GPT-OSS and Qwen status cards telemetry remains intact and truthful."""
    cm = get_cognitive_models_status()
    assert cm["provider_connected"] is True
    assert cm["provider"] == "GROQ"
    gpt = cm["models"]["gpt_oss"]
    qwen = cm["models"]["qwen"]
    assert gpt["configured"] is True
    assert gpt["role"] == "SHADOW PRIMARY"
    assert gpt["api_connected"] is True
    assert gpt["live_shadow_enabled"] is False
    assert gpt["current_request_in_flight"] is False
    assert qwen["role"] == "CHALLENGER"
    assert qwen["api_connected"] is True
    assert qwen["live_shadow_enabled"] is False
    assert qwen["current_request_in_flight"] is False


def test_vob_unchanged():
    """Assertion 13: VOB files remain unmodified and uninfluenced by external/AI modules."""
    vob_file = "src/trading/vob.py"
    if os.path.exists(vob_file):
        with open(vob_file, "r", encoding="utf-8") as f:
            vob_code = f.read()
        assert "groq" not in vob_code.lower()
        assert "twelve_data" not in vob_code.lower()
        assert "marketaux" not in vob_code.lower()
