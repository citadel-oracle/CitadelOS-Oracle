"""Full multi-timeframe VOB + Horsepower + Resolver session replay soak for 2026-08-07."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.vob.bigbeluga_engine import BigBelugaVOBEngine, MSLEN
from src.vob.engine import NiftyVOBEngine
from src.oracle.resolver_engine import ResolverEngine
from src.oracle.option_buyer_intelligence import _OiRollingTracker

IST = ZoneInfo("Asia/Kolkata")
RAW_DIR = Path("reports/personal_strategy_replay/e8d_20260706_20260807/raw")


def to_dt(ts) -> datetime | None:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=IST)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
    return None


def run_full_vob_soak():
    # Load 1m candles for CE 41015 (24600 CE) and PE 41024 (24700 PE)
    with open(RAW_DIR / "opt_41015_1m_20260807.json") as f:
        ce_1m = json.load(f)["candles"]
    with open(RAW_DIR / "opt_41024_1m_20260807.json") as f:
        pe_1m = json.load(f)["candles"]

    vob_helper = NiftyVOBEngine()
    ce_3m = vob_helper._resample_1m(ce_1m, 3)
    ce_5m = vob_helper._resample_1m(ce_1m, 5)

    pe_3m = vob_helper._resample_1m(pe_1m, 3)
    pe_5m = vob_helper._resample_1m(pe_1m, 5)

    engine = ResolverEngine()
    ledger = []
    behaviors = {
        "SINGLE_1M": 0,
        "SINGLE_3M": 0,
        "SINGLE_5M": 0,
        "1M_3M_ALIGNMENT": 0,
        "3M_5M_ALIGNMENT": 0,
        "FULL_ALIGNMENT": 0,
        "HELD_STATE": 0,
    }

    # Step chronologically through 1-minute bars from 09:15 to 15:30
    for idx, bar in enumerate(ce_1m):
        t = to_dt(bar["time"])
        if not t:
            continue

        # Ingest flow proxy from volume delta
        vol_delta = bar["volume"] * 0.05
        engine.ingest_flow_snapshot({
            "revision": f"FLOW_BAR_{idx}",
            "source_timestamp": t.isoformat(),
            "diagnostics": {"book_pressure": {"mlofi": 0.25 if bar["close"] >= bar["open"] else -0.25}},
        }, t)

        # Build CE VOB state from slice up to time t
        sub_1m = [c for c in ce_1m if to_dt(c.get("timestamp") or c.get("time")) <= t]
        sub_3m = [c for c in ce_3m if to_dt(c.get("timestamp") or c.get("time")) <= t]
        sub_5m = [c for c in ce_5m if to_dt(c.get("timestamp") or c.get("time")) <= t]

        hp_1m_status = "RESISTANCE_OUT" if sub_1m and sub_1m[-1]["close"] > sub_1m[-1]["open"] else "SUPPORT_GONE"
        hp_3m_status = "RESISTANCE_OUT" if len(sub_3m) >= 3 and sub_3m[-1]["close"] > sub_3m[-1]["open"] else ("SUPPORT_GONE" if len(sub_3m) >= 3 else "NEUTRAL")
        hp_5m_status = "RESISTANCE_OUT" if len(sub_5m) >= 3 and sub_5m[-1]["close"] > sub_5m[-1]["open"] else ("SUPPORT_GONE" if len(sub_5m) >= 3 else "NEUTRAL")

        ce_payload = {
            "contract": {"security_id": "41015", "strike": 24600},
            "quote": {"security_id": "41015", "strike": 24600, "ltp": bar["close"], "oi": 5000000},
            "vob": {
                "horsepower": {
                    "1m": {"status": hp_1m_status, "event_id": f"CE_1M_{idx}", "confirmed_candle": t.isoformat()},
                    "3m": {"status": hp_3m_status, "event_id": f"CE_3M_{idx//3}", "confirmed_candle": t.isoformat()},
                    "5m": {"status": hp_5m_status, "event_id": f"CE_5M_{idx//5}", "confirmed_candle": t.isoformat()},
                }
            },
        }

        flow_diag = engine.compute_flow_diagnostics(t, t)
        ev, diag = engine.synthesize_resolver_state("CE", ce_payload, {}, flow_diag, {}, t)

        lbl = ev["label"]
        if "FULL VOB" in lbl:
            behaviors["FULL_ALIGNMENT"] += 1
        elif "3M+5M" in lbl:
            behaviors["3M_5M_ALIGNMENT"] += 1
        elif "1M+3M" in lbl:
            behaviors["1M_3M_ALIGNMENT"] += 1
        elif "5M" in lbl:
            behaviors["SINGLE_5M"] += 1
        elif "3M" in lbl:
            behaviors["SINGLE_3M"] += 1
        elif "1M" in lbl:
            behaviors["SINGLE_1M"] += 1

        if ev["held_previous"]:
            behaviors["HELD_STATE"] += 1

        ledger.append({"t": t.isoformat(), "label": lbl, "variant": ev["variant"]})

    print("2026-08-07 Multi-Timeframe VOB Replay Soak Results:")
    print(f"Total bars processed: {len(ce_1m)}")
    print(f"Behavior Counts: {json.dumps(behaviors, indent=2)}")
    print(f"Distinct labels observed: {set(x['label'] for x in ledger)}")
    return behaviors


if __name__ == "__main__":
    run_full_vob_soak()
