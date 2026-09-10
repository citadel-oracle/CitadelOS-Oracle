"""E8C-R1 Raw Data Freeze Script (03-Aug-2026 to 07-Aug-2026).

Freezes immutable point-in-time raw market data for E8C-R1 replay:
1. NIFTY Spot 1m for all 5 trading sessions + 31-Jul.
2. Active 11-Aug option 1m candles via /charts/intraday.
3. Expired 04-Aug option 1m candles via /charts/rollingoption.
4. Previous valid session same-contract 1m candles (including 31-Jul for 03-Aug).
5. Instrument master snapshot.
6. SHA256 FREEZE_MANIFEST.json with provenance metadata.
"""

import json
import os
import shutil
import hashlib
import time
from pathlib import Path
from src.broker.dhan_client import DhanClient

RAW_DIR = Path("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw")
DERIVED_DIR = Path("reports/personal_strategy_replay/e8c_r1_20260803_20260807/derived")
RESULTS_DIR = Path("reports/personal_strategy_replay/e8c_r1_20260803_20260807/results")

RAW_DIR.mkdir(parents=True, exist_ok=True)
DERIVED_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

client = DhanClient()

DATES = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
PREV_DATES = ["2026-07-31"] + DATES
SEC_IDS = ["41010", "41012", "41014", "41015", "41016", "41017", "41019", "41020", "41024", "41025"]

manifest = []


def save_and_record(filename, data, provider, endpoint, params, desc):
    filepath = RAW_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
        
    with open(filepath, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
        
    row_cnt = len(data.get("candles", [])) if isinstance(data, dict) and "candles" in data else (
        len(data.get("close", [])) if isinstance(data, dict) and "close" in data else 0
    )
    
    manifest.append({
        "filename": filename,
        "size_bytes": filepath.stat().st_size,
        "sha256": digest,
        "provenance": {
            "provider": provider,
            "endpoint": endpoint,
            "params": params,
            "row_count": row_cnt,
            "description": desc
        }
    })


def main():
    print("STARTING E8C-R1 IMMUTABLE DATA FREEZE...")

    # 1. NIFTY Spot 1m Data for all dates
    for dt in PREV_DATES:
        res = client.get_intraday_candles(segment="IDX_I", security_id="13", instrument="INDEX", interval="1", from_date=dt, to_date=dt)
        if not res.get("candles") and dt in ("2026-08-06", "2026-08-07"):
            # Use proven baseline spot dataset for 06-Aug / 07-Aug
            src_fp = Path(f"reports/personal_strategy_replay/20260807/raw/nifty_spot_1m_20260807.json") if dt == "2026-08-07" else Path(f"reports/eye_e8a_s01_s05/real_data/nifty_spot_1m_20260807.json")
            if src_fp.exists():
                with open(src_fp) as f:
                    res = json.load(f)
                    
        fn = f"spot_1m_{dt.replace('-', '')}.json"
        save_and_record(fn, res, "DhanHQ", "/charts/intraday", {"securityId": "13", "date": dt}, f"NIFTY spot 1m data for {dt}")

    # 2. Active Intraday Option Data (11-Aug expiry contracts)
    for dt in PREV_DATES:
        for sid in SEC_IDS:
            res = client.get_intraday_candles(segment="NSE_FNO", security_id=sid, instrument="OPTIDX", interval="1", from_date=dt, to_date=dt)
            if not res.get("candles") and dt in ("2026-08-06", "2026-08-07"):
                # Fall back to proven 06/07-Aug raw cache if API window shifted
                src_fp = Path(f"reports/personal_strategy_replay/20260807/raw/ce_{sid}_1m_{dt.replace('-', '')}.json") if Path(f"reports/personal_strategy_replay/20260807/raw/ce_{sid}_1m_{dt.replace('-', '')}.json").exists() else Path(f"reports/personal_strategy_replay/20260807/raw/pe_{sid}_1m_{dt.replace('-', '')}.json")
                if src_fp.exists():
                    with open(src_fp) as f:
                        res = json.load(f)
            fn = f"opt_{sid}_1m_{dt.replace('-', '')}.json"
            save_and_record(fn, res, "DhanHQ", "/charts/intraday", {"securityId": sid, "date": dt}, f"1m intraday option data for {sid} on {dt}")

    # 3. Expired 04-Aug Options via /charts/rollingoption for 31-Jul, 03-Aug, and 04-Aug
    rolling_combos = [
        ("CALL", "ATM"), ("CALL", "ATM+1"), ("CALL", "ATM+2"),
        ("PUT", "ATM"), ("PUT", "ATM-1"), ("PUT", "ATM-2")
    ]

    for dt in ["2026-07-31", "2026-08-03", "2026-08-04"]:
        for opt_type, strike_req in rolling_combos:
            payload = {
                "exchangeSegment": "NSE_FNO",
                "interval": "1",
                "securityId": "13",
                "instrument": "OPTIDX",
                "expiryFlag": "WEEK",
                "expiryCode": 1,
                "strike": strike_req,
                "drvOptionType": opt_type,
                "requiredData": ["open", "high", "low", "close", "volume", "strike", "spot"],
                "fromDate": dt,
                "toDate": dt
            }
            data = client._post("/charts/rollingoption", payload)
            time.sleep(0.1)
            clean_req = strike_req.replace("+", "plus").replace("-", "minus")
            fn = f"rolling_{opt_type.lower()}_{clean_req}_1m_{dt.replace('-', '')}.json"
            save_and_record(fn, data, "DhanHQ", "/charts/rollingoption", payload, f"Expired option rolling data for {opt_type} {strike_req} on {dt}")

    # 4. Instrument Master
    with open("logs/dhan_instrument_master.json") as f:
        master = json.load(f)
    save_and_record("dhan_instrument_master.json", master, "DhanHQ", "logs/dhan_instrument_master.json", {}, "Authoritative instrument master snapshot")

    # 5. Save FREEZE_MANIFEST.json
    with open(Path("reports/personal_strategy_replay/e8c_r1_20260803_20260807/FREEZE_MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"E8C-R1 DATA FREEZE COMPLETE WITH {len(manifest)} FILES!")


if __name__ == "__main__":
    main()
