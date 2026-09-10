import json
import tempfile
from pathlib import Path
from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore

def generate_samples():
    tmp_dir = tempfile.mkdtemp()
    store = ArgusTacticalStore(path=Path(tmp_dir) / "store.json")
    engine = ArgusTacticalEdgeEngine(store=store)

    # 1. BUY CALL
    argus_call = {
        "status": "AVAILABLE",
        "freshness": "FRESH",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "expiry": "2026-07-30",
                "ltp": 24000.0,
                "atm_strike": 24000.0,
                "market_state": "OPEN",
                "fetched_at": "2026-07-23T10:00:00+00:00",
            },
            "atm_window": [
                {
                    "strike": 23900.0 + i * 50,
                    "ce": {
                        "oi": 20000 + i * 1000,
                        "day_change_oi": 1500,
                        "intraday_change_oi": 800,
                        "volume": 25000,
                        "intraday_price_change": 25.0,
                        "activity": "CALL_BUYING",
                        "security_id": f"CE_{23900 + i * 50}",
                    },
                    "pe": {
                        "oi": 5000,
                        "day_change_oi": -200,
                        "intraday_change_oi": -100,
                        "volume": 2000,
                        "intraday_price_change": -15.0,
                        "activity": "PUT_WRITING",
                        "security_id": f"PE_{23900 + i * 50}",
                    },
                }
                for i in range(7)
            ],
            "walls": {"highest_ce_oi": {"strike": 24300.0}, "highest_pe_oi": {"strike": 23800.0}},
            "totals": {"day_ce_change_oi": 8000, "day_pe_change_oi": -1000, "intraday_ce_change_oi": 4000, "intraday_pe_change_oi": -500},
        },
    }
    ose_call = {
        "status": "LIVE",
        "symbol": "NIFTY",
        "expiry": "2026-07-30",
        "anchor": 24000.0,
        "canonical_digest": "digest_call",
        "calculated_at": "2026-07-23T10:00:00+00:00",
        "contracts": {
            "CE": {
                "contract": {"security_id": "CE_23900", "strike": 23900.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL23900CE"},
                "premium": 200.0,
                "composite": {"label": "BULLISH_CONTINUATION"},
                "structures": {"5m": {"completed_bucket": True, "state": "BULLISH", "supply_break": True, "demand_break": False, "bullish_retest": True, "bearish_retest": False}},
            },
            "PE": {
                "contract": {"security_id": "PE_24100", "strike": 24100.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL24100PE"},
                "premium": 180.0,
                "composite": {"label": "BEARISH_REVERSAL"},
                "structures": {"5m": {"completed_bucket": True, "state": "BEARISH", "supply_break": False, "demand_break": True, "bullish_retest": False, "bearish_retest": True}},
            },
        },
    }

    res_call = engine.evaluate(argus_call, ose_call)

    # 2. BUY PUT
    argus_put = {
        "status": "AVAILABLE",
        "freshness": "FRESH",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "expiry": "2026-07-30",
                "ltp": 24000.0,
                "atm_strike": 24000.0,
                "market_state": "OPEN",
                "fetched_at": "2026-07-23T10:00:00+00:00",
            },
            "atm_window": [
                {
                    "strike": 23900.0 + i * 50,
                    "ce": {
                        "oi": 5000,
                        "day_change_oi": -200,
                        "intraday_change_oi": -100,
                        "volume": 2000,
                        "intraday_price_change": -15.0,
                        "activity": "CALL_WRITING",
                        "security_id": f"CE_{23900 + i * 50}",
                    },
                    "pe": {
                        "oi": 20000 + i * 1000,
                        "day_change_oi": 1500,
                        "intraday_change_oi": 800,
                        "volume": 25000,
                        "intraday_price_change": 25.0,
                        "activity": "PUT_BUYING",
                        "security_id": f"PE_{23900 + i * 50}",
                    },
                }
                for i in range(7)
            ],
            "walls": {"highest_ce_oi": {"strike": 24200.0}, "highest_pe_oi": {"strike": 23700.0}},
            "totals": {"day_ce_change_oi": -1000, "day_pe_change_oi": 8000, "intraday_ce_change_oi": -500, "intraday_pe_change_oi": 4000},
        },
    }
    ose_put = {
        "status": "LIVE",
        "symbol": "NIFTY",
        "expiry": "2026-07-30",
        "anchor": 24000.0,
        "canonical_digest": "digest_put",
        "calculated_at": "2026-07-23T10:00:00+00:00",
        "contracts": {
            "CE": {
                "contract": {"security_id": "CE_23900", "strike": 23900.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL23900CE"},
                "premium": 180.0,
                "composite": {"label": "BULLISH_CONTINUATION"},
                "structures": {"5m": {"completed_bucket": True, "state": "BULLISH", "supply_break": False, "demand_break": True, "bullish_retest": False, "bearish_retest": True}},
            },
            "PE": {
                "contract": {"security_id": "PE_24100", "strike": 24100.0, "expiry": "2026-07-30", "trading_symbol": "NIFTY26JUL24100PE"},
                "premium": 220.0,
                "composite": {"label": "BEARISH_CONTINUATION"},
                "structures": {"5m": {"completed_bucket": True, "state": "BEARISH", "supply_break": False, "demand_break": True, "bullish_retest": False, "bearish_retest": True}},
            },
        },
    }
    res_put = engine.evaluate(argus_put, ose_put)

    # 3. WAIT FOR PULLBACK (Stretched premium)
    ose_pullback = json.loads(json.dumps(ose_call))
    ose_pullback["contracts"]["CE"]["premium"] = 450.0  # Highly stretched premium
    res_pullback = engine.evaluate(argus_call, ose_pullback)

    # 4. NO TRADE (Balanced pressure)
    argus_balanced = json.loads(json.dumps(argus_call))
    for row in argus_balanced["data"]["atm_window"]:
        row["ce"]["intraday_change_oi"] = 100
        row["pe"]["intraday_change_oi"] = 100
        row["ce"]["volume"] = 1000
        row["pe"]["volume"] = 1000
    res_notrade = engine.evaluate(argus_balanced, ose_call)

    # 5. MISSING DATA (Stale / Unavailable)
    argus_stale = json.loads(json.dumps(argus_call))
    argus_stale["status"] = "STALE"
    argus_stale["freshness"] = "STALE"
    res_missing = engine.evaluate(argus_stale, ose_call)

    print("SAMPLE_BUY_CALL:", json.dumps(res_call["decision"], indent=2))
    print("SAMPLE_BUY_PUT:", json.dumps(res_put["decision"], indent=2))
    print("SAMPLE_WAIT_PULLBACK:", json.dumps(res_pullback["decision"], indent=2))
    print("SAMPLE_NO_TRADE:", json.dumps(res_notrade["decision"], indent=2))
    print("SAMPLE_MISSING_DATA:", json.dumps(res_missing["decision"], indent=2))

if __name__ == "__main__":
    generate_samples()
