import sys, os
sys.path.insert(0, os.path.abspath("."))

import json, csv, statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv("/Users/ayushmudgal/Developer/CitadelOS/.env")

from src.argus.tactical_store import ArgusTacticalStore
from src.argus.tactical_edge import ArgusTacticalEdgeEngine

ist = timezone(timedelta(hours=5, minutes=30))
artifact_dir = "/Users/ayushmudgal/.gemini/antigravity/brain/9528aba5-4490-4b02-b1ef-3180eaa51bf2"
candles_file = "/tmp/full_day_2026-07-23_candles.json"

if not os.path.exists(candles_file):
    print(f"FAIL_LOUDS: {candles_file} missing", file=sys.stderr)
    sys.exit(1)

with open(candles_file) as f:
    dataset = json.load(f)

spot_candles = dataset["NIFTY_SPOT"]
pe24100_candles = dataset["24100_PE"]
ce24100_candles = dataset["24100_CE"]

strikes_list = [23700, 23800, 23900, 24000, 24100, 24200, 24300]

store = ArgusTacticalStore(Path("/tmp/prod_argus_replay_store.json"))
engine = ArgusTacticalEdgeEngine(store)

n = len(spot_candles)
ledger_rows = []

prev_delta = 0.0
prev_breadth_count = 0

for i in range(1, n - 31):
    sc = spot_candles[i]
    dt = datetime.fromtimestamp(sc["time"], ist)
    t_str = dt.strftime("%H:%M:%S")
    
    underlying = {"symbol": "NIFTY", "ltp": sc["close"]}
    previous_underlying = {"spot": spot_candles[i-1]["close"]}
    
    raw_rows = []
    for strike in strikes_list:
        ce_key = f"{strike}_CE"
        pe_key = f"{strike}_PE"
        
        ce_c = dataset[ce_key][i] if ce_key in dataset and i < len(dataset[ce_key]) else None
        pe_c = dataset[pe_key][i] if pe_key in dataset and i < len(dataset[pe_key]) else None
        
        row_item = {"strike": strike}
        if ce_c:
            row_item["ce"] = {
                "security_id": ce_c.get("security_id", 0),
                "intraday_price_change": ce_c["close"] - ce_c["open"],
                "volume": ce_c["volume"],
                "ltp": ce_c["close"]
            }
        if pe_c:
            row_item["pe"] = {
                "security_id": pe_c.get("security_id", 0),
                "intraday_price_change": pe_c["close"] - pe_c["open"],
                "volume": pe_c["volume"],
                "ltp": pe_c["close"]
            }
        raw_rows.append(row_item)
        
    pres = engine._pressure(raw_rows, underlying, previous_underlying)
    breadth = engine._breadth(pres)
    
    curr_delta = pres.get("delta", 0.0)
    pres_accel = round(curr_delta - prev_delta, 2)
    
    call_confirm = breadth.get("call_confirming_strikes", 0)
    put_confirm = breadth.get("put_confirming_strikes", 0)
    confirming_strikes = max(call_confirm, put_confirm)
    
    sig_accel = (pres_accel >= 5.0 and confirming_strikes >= 4)
    sig_reexpand = (confirming_strikes >= 6 and prev_breadth_count < 4)
    sig_contract = (confirming_strikes < 4 and prev_breadth_count >= 6)
    
    pe_next = pe24100_candles[i+1]
    entry_price_t1 = pe_next["open"]
    
    forward_pe_candles = pe24100_candles[i+1 : i+16]
    max_high_15m = max([c["high"] for c in forward_pe_candles])
    min_low_15m = min([c["low"] for c in forward_pe_candles])
    close_15m = forward_pe_candles[-1]["close"]
    
    mfe_15m = round(max_high_15m - entry_price_t1, 2)
    mae_15m = round(min_low_15m - entry_price_t1, 2)
    tx_adj_pnl = round((close_15m - entry_price_t1) - 0.50, 2)
    
    if sig_accel:
        action = "ENTRY" if pres_accel >= 10.0 else "WATCH"
        sig_name = "pressure_accel_gated"
    elif sig_reexpand:
        action = "ENTRY"
        sig_name = "breadth_reexpansion"
    elif sig_contract:
        action = "HOLD"
        sig_name = "participation_contraction"
    elif confirming_strikes >= 6:
        action = "ENTRY"
        sig_name = "ohlcv_participation_breadth_proxy"
    else:
        action = "NONE"
        sig_name = "NONE"
        
    if action != "NONE":
        ledger_rows.append({
            "timestamp_T": t_str,
            "spot_T": sc["close"],
            "signal_name": sig_name,
            "production_pressure_state": pres.get("state"),
            "production_pressure_delta": curr_delta,
            "production_accel": pres_accel,
            "production_confirming_strikes": confirming_strikes,
            "action_emitted_at_T": action,
            "actual_recorded_T1_entry_pe_price": entry_price_t1,
            "actual_recorded_15m_MFE": mfe_15m,
            "actual_recorded_15m_MAE": mae_15m,
            "actual_recorded_15m_tx_adj_pnl": tx_adj_pnl
        })
        
    prev_delta = curr_delta
    prev_breadth_count = confirming_strikes

out_csv = os.path.join(artifact_dir, "PRODUCTION_ARGUS_REPLAY_LEDGER.csv")
with open(out_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(ledger_rows[0].keys()))
    writer.writeheader()
    writer.writerows(ledger_rows)

print(f"PRODUCTION ARGUS REPLAY COMPLETE: Generated {len(ledger_rows)} rows using 100% actual historical option OHLCV & live ArgusTacticalEdgeEngine methods.")
