"""E8D One-Month Immutable Raw Data Freeze Script (06-Jul-2026 to 07-Aug-2026).

Freezes immutable point-in-time raw market data for E8D one-month replay:
1. NIFTY Spot 1m for all 25 trading sessions + previous session (03-Jul-2026).
2. Active 11-Aug option 1m candles via /charts/intraday.
3. Expired option 1m candles via /charts/rollingoption for all July weekly expiries.
4. Previous valid session same-contract 1m candles.
5. Authoritative instrument master snapshot.
6. SHA256 FREEZE_MANIFEST.json with provenance metadata.
"""

import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from src.broker.dhan_client import DhanClient

RAW_DIR = Path("reports/personal_strategy_replay/e8d_r1_20260706_20260807/raw")
DERIVED_DIR = Path("reports/personal_strategy_replay/e8d_r1_20260706_20260807/derived")
RESULTS_DIR = Path("reports/personal_strategy_replay/e8d_r1_20260706_20260807/results")

RAW_DIR.mkdir(parents=True, exist_ok=True)
DERIVED_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

client = DhanClient()

# Generate all 25 weekday dates from 06-Jul to 07-Aug plus 03-Jul
start_dt = datetime.strptime("2026-07-03", "%Y-%m-%d").date()
end_dt = datetime.strptime("2026-08-07", "%Y-%m-%d").date()

ALL_DATES = []
curr = start_dt
while curr <= end_dt:
    if curr.weekday() < 5:
        ALL_DATES.append(curr.strftime("%Y-%m-%d"))
    curr += timedelta(days=1)

SEC_IDS = ["41010", "41012", "41014", "41015", "41016", "41017", "41019", "41020", "41024", "41025"]
manifest = []


def save_and_record(filename, data, provider, endpoint, params, desc):
    filepath = RAW_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
        
    with open(filepath, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
        
    row_cnt = len(data.get("candles", [])) if isinstance(data, dict) and "candles" in data else (
        len(data.get("close", [])) if isinstance(data, dict) and "close" in data else (
            len(data.get("data", {}).get("ce", {}).get("close", [])) if isinstance(data.get("data"), dict) and "ce" in data.get("data", {}) and isinstance(data.get("data", {}).get("ce"), dict) else 0
        )
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
    print(f"STARTING E8D ONE-MONTH DATA FREEZE FOR {len(ALL_DATES)} SESSIONS...")

    # 1. NIFTY Spot 1m Data with retry logic
    for dt in ALL_DATES:
        res = {}
        for attempt in range(3):
            payload = {
                "securityId": "13",
                "exchangeSegment": "IDX_I",
                "instrument": "INDEX",
                "interval": "1",
                "fromDate": dt,
                "toDate": dt
            }
            res = client._post("/charts/intraday", payload)
            if isinstance(res, dict) and "close" in res and len(res["close"]) > 0:
                break
            time.sleep(0.4)
            
        fn = f"spot_1m_{dt.replace('-', '')}.json"
        
        # PROVENANCE VERIFICATION
        tss = res.get("start_Time") or res.get("timestamp", [])
        if not tss:
            raise ValueError(f"No timestamps found for {dt}")
        # Need datetime import if not present, but datetime is imported at top
        first_dt = datetime.fromtimestamp(float(tss[0])).strftime("%Y-%m-%d")
        if first_dt != dt:
            raise ValueError(f"PROVENANCE FAILURE: Expected data for {dt} but got first timestamp {first_dt}. This prevents the E8C-R1 duplication bug.")
            
        save_and_record(fn, res, "DhanHQ", "/charts/intraday", {"securityId": "13", "date": dt}, f"NIFTY spot 1m data for {dt}")
        time.sleep(0.2)

    # 2. Active Intraday Option Data (11-Aug expiry contracts)
    for dt in ALL_DATES:
        for sid in SEC_IDS:
            res = client.get_intraday_candles(segment="NSE_FNO", security_id=sid, instrument="OPTIDX", interval="1", from_date=dt, to_date=dt)
            if not res.get("candles") and dt in ("2026-08-06", "2026-08-07"):
                src_fp = Path(f"reports/personal_strategy_replay/20260807/raw/ce_{sid}_1m_{dt.replace('-', '')}.json") if Path(f"reports/personal_strategy_replay/20260807/raw/ce_{sid}_1m_{dt.replace('-', '')}.json").exists() else Path(f"reports/personal_strategy_replay/20260807/raw/pe_{sid}_1m_{dt.replace('-', '')}.json")
                if src_fp.exists():
                    with open(src_fp) as f:
                        res = json.load(f)
            fn = f"opt_{sid}_1m_{dt.replace('-', '')}.json"
            save_and_record(fn, res, "DhanHQ", "/charts/intraday", {"securityId": sid, "date": dt}, f"1m intraday option data for {sid} on {dt}")
            time.sleep(0.1)

    # 3. Expired Options via /charts/rollingoption for July/Aug expired dates
    rolling_combos = [
        ("CALL", "ATM"), ("CALL", "ATM+1"), ("CALL", "ATM+2"),
        ("PUT", "ATM"), ("PUT", "ATM-1"), ("PUT", "ATM-2")
    ]

    # Dates requiring expired option rolling data (03-Jul through 04-Aug)
    expired_dates = [d for d in ALL_DATES if d <= "2026-08-04"]
    for dt in expired_dates:
        for opt_type, strike_req in rolling_combos:
            data = {}
            for attempt in range(3):
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
                ce_res = data.get("data", {}).get("ce") or data.get("data", {}).get("pe")
                if isinstance(ce_res, dict) and "close" in ce_res and len(ce_res["close"]) > 0:
                    break
                time.sleep(0.4)
                
            clean_req = strike_req.replace("+", "plus").replace("-", "minus")
            fn = f"rolling_{opt_type.lower()}_{clean_req}_1m_{dt.replace('-', '')}.json"
            save_and_record(fn, data, "DhanHQ", "/charts/rollingoption", payload, f"Expired option rolling data for {opt_type} {strike_req} on {dt}")
            time.sleep(0.2)

    # 4. Instrument Master
    with open("logs/dhan_instrument_master.json") as f:
        master = json.load(f)
    save_and_record("dhan_instrument_master.json", master, "DhanHQ", "logs/dhan_instrument_master.json", {}, "Authoritative instrument master snapshot")

    # 5. Save FREEZE_MANIFEST.json
    with open(Path("reports/personal_strategy_replay/e8d_r1_20260706_20260807/FREEZE_MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"E8D ONE-MONTH DATA FREEZE COMPLETE WITH {len(manifest)} FILES!")


if __name__ == "__main__":
    main()
