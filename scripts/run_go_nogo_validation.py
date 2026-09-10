import sys, os
sys.path.insert(0, os.path.abspath("."))

import json, csv, math, statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv("/Users/ayushmudgal/Developer/CitadelOS/.env")

from src.argus.tactical_store import ArgusTacticalStore
from src.argus.tactical_edge import ArgusTacticalEdgeEngine

ist = timezone(timedelta(hours=5, minutes=30))
artifact_dir = "/Users/ayushmudgal/.gemini/antigravity/brain/9528aba5-4490-4b02-b1ef-3180eaa51bf2"
vob_file = "/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json"

if not os.path.exists(vob_file):
    print(f"ERROR: {vob_file} missing", file=sys.stderr)
    sys.exit(1)

with open(vob_file) as f:
    vob_data = json.load(f)

all_candles = vob_data.get("candles", [])

session_spot = {}
for c in all_candles:
    dt = datetime.fromtimestamp(c["time"], ist)
    d_str = dt.strftime("%Y-%m-%d")
    if d_str not in session_spot:
        session_spot[d_str] = []
    session_spot[d_str].append(c)

all_dates = sorted(list(session_spot.keys()))
total_sessions = len(all_dates)

split_idx = int(math.ceil(total_sessions * 0.70))
is_dates = all_dates[:split_idx]
oos_dates = all_dates[split_idx:]

store = ArgusTacticalStore(Path("/tmp/go_nogo_store.json"))
engine = ArgusTacticalEdgeEngine(store)

def evaluate_trading_signals(target_dates, sample_type):
    trades = []
    session_profits = {}
    
    for d in target_dates:
        candles = session_spot[d]
        n = len(candles)
        if n < 30: continue
        
        session_profits[d] = 0.0
        in_trade = False
        trade_exit_idx = -1
        prev_delta = 0.0
        
        for i in range(1, n - 16):
            if i <= trade_exit_idx:
                continue
                
            sc = candles[i]
            t_str = datetime.fromtimestamp(sc["time"], ist).strftime("%H:%M:%S")
            
            underlying = {"symbol": "NIFTY", "ltp": sc["close"]}
            previous_underlying = {"spot": candles[i-1]["close"]}
            
            spot_mom = sc["close"] - candles[i-1]["close"]
            
            raw_rows = []
            for strike in [23700, 23800, 23900, 24000, 24100, 24200, 24300]:
                raw_rows.append({
                    "strike": strike,
                    "ce": {"security_id": 1, "intraday_price_change": spot_mom * 0.5, "volume": abs(spot_mom) * 1000, "ltp": 150.0 + spot_mom},
                    "pe": {"security_id": 2, "intraday_price_change": -spot_mom * 0.5, "volume": abs(spot_mom) * 1000, "ltp": 150.0 - spot_mom}
                })
                
            pres = engine._pressure(raw_rows, underlying, previous_underlying)
            breadth = engine._breadth(pres)
            
            curr_delta = pres.get("delta", 0.0)
            pres_accel = round(curr_delta - prev_delta, 2)
            direction = pres.get("direction", "BALANCED")
            
            call_confirm = breadth.get("call_confirming_strikes", 0)
            put_confirm = breadth.get("put_confirming_strikes", 0)
            confirming_strikes = max(call_confirm, put_confirm)
            
            is_entry = (confirming_strikes >= 4 and pres_accel >= 10.0 and direction in ["CALL", "PUT"])
            
            if is_entry:
                contract_type = "CE" if direction == "CALL" else "PE"
                
                next_candle = candles[i+1]
                entry_spot = next_candle["open"]
                entry_opt_price = round(150.0 + (entry_spot - sc["close"]) * (0.50 if contract_type == "CE" else -0.50), 2)
                
                exit_candle = candles[min(n-1, i+16)]
                exit_spot = exit_candle["close"]
                exit_opt_price = round(150.0 + (exit_spot - sc["close"]) * (0.50 if contract_type == "CE" else -0.50), 2)
                
                path_spots = [candles[j]["close"] for j in range(i+1, min(n, i+16))]
                path_opts = [round(150.0 + (s - sc["close"]) * (0.50 if contract_type == "CE" else -0.50), 2) for s in path_spots]
                
                mfe = round(max(path_opts) - entry_opt_price, 2)
                mae = round(min(path_opts) - entry_opt_price, 2)
                
                tx_cost = 1.00
                gross_pnl = round(exit_opt_price - entry_opt_price, 2)
                net_pnl = round(gross_pnl - tx_cost, 2)
                rupee_pnl = round(net_pnl * 25.0, 2)
                
                trade = {
                    "session_date": d,
                    "sample_type": sample_type,
                    "signal_time": t_str,
                    "direction": direction,
                    "contract_type": contract_type,
                    "entry_opt_price": entry_opt_price,
                    "exit_opt_price": exit_opt_price,
                    "gross_pnl_pts": gross_pnl,
                    "net_pnl_pts": net_pnl,
                    "rupee_pnl": rupee_pnl,
                    "mfe_pts": mfe,
                    "mae_pts": mae,
                    "is_win": net_pnl > 0
                }
                trades.append(trade)
                session_profits[d] += net_pnl
                
                trade_exit_idx = i + 15
                
            prev_delta = curr_delta
            
    return trades, session_profits

is_trades, is_session_pnl = evaluate_trading_signals(is_dates, "IN_SAMPLE")
oos_trades, oos_session_pnl = evaluate_trading_signals(oos_dates, "OUT_OF_SAMPLE")

all_trades = is_trades + oos_trades
out_csv = os.path.join(artifact_dir, "FINAL_GO_NOGO_TRADES.csv")
with open(out_csv, "w", newline="") as f:
    if all_trades:
        writer = csv.DictWriter(f, fieldnames=list(all_trades[0].keys()))
        writer.writeheader()
        writer.writerows(all_trades)

print(f"GO/NO-GO BACKTEST COMPLETE across {total_sessions} sessions:")
print(f"  In-Sample ({len(is_dates)} sessions): {len(is_trades)} non-overlapping trades")
print(f"  Out-Of-Sample ({len(oos_dates)} sessions): {len(oos_trades)} non-overlapping trades")

oos_cnt = len(oos_trades)
if oos_cnt > 0:
    oos_wins = [t for t in oos_trades if t["is_win"]]
    oos_win_rate = round(100.0 * len(oos_wins) / oos_cnt, 1)
    
    gains = sum([t["net_pnl_pts"] for t in oos_trades if t["net_pnl_pts"] > 0])
    losses = abs(sum([t["net_pnl_pts"] for t in oos_trades if t["net_pnl_pts"] < 0]))
    profit_factor = round(gains / losses, 2) if losses > 0 else 0.0
    
    avg_expectancy = round(statistics.mean([t["net_pnl_pts"] for t in oos_trades]), 2)
    med_expectancy = round(statistics.median([t["net_pnl_pts"] for t in oos_trades]), 2)
    
    pos_sessions = len([d for d, pnl in oos_session_pnl.items() if pnl > 0])
    pos_session_pct = round(100.0 * pos_sessions / len(oos_dates), 1)
    
    max_session_pnl = max(oos_session_pnl.values()) if oos_session_pnl else 0.0
    tot_oos_pnl = sum(oos_session_pnl.values())
    max_session_contrib = round(100.0 * max_session_pnl / tot_oos_pnl, 1) if tot_oos_pnl > 0 else 100.0
else:
    oos_win_rate = 0.0
    profit_factor = 0.0
    avg_expectancy = 0.0
    med_expectancy = 0.0
    pos_session_pct = 0.0
    max_session_contrib = 100.0

print(f"\n--- OUT-OF-SAMPLE EVALUATION ---")
print(f"  Trade Count: {oos_cnt} (Required: >= 40)")
print(f"  Profit Factor: {profit_factor} (Required: >= 1.15)")
print(f"  Average Expectancy: {avg_expectancy} pts (Required: > 0)")
print(f"  Median Expectancy: {med_expectancy} pts (Required: > 0)")
print(f"  Profitable Sessions: {pos_session_pct}% (Required: >= 60%)")
print(f"  Max Session Profit Contribution: {max_session_contrib}% (Required: <= 35%)")

go_pass = (
    oos_cnt >= 40 and
    profit_factor >= 1.15 and
    avg_expectancy > 0 and
    med_expectancy > 0 and
    pos_session_pct >= 60.0 and
    max_session_contrib <= 35.0
)

print(f"\n==========================================")
if go_pass:
    print("VERDICT: ARGUS TRADING EDGE: GO")
else:
    print("VERDICT: ARGUS TRADING EDGE: NO-GO")
print("==========================================")
