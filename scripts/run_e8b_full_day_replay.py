"""E8B S01 + S05 Full-Day Trade Replay Harness for 07-Aug-2026.

Executes deterministic full-day trade replay from immutable frozen raw data.
Calculates trade ledgers, MFE/MAE, R-multiples, performance metrics, and Rupee P&L.
"""

import json
import os
import math
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from src.eye.personal_strategies.indicators import compute_bollinger_bands, compute_rsi, compute_ema, compute_traditional_pivots
from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator


RAW_DIR = Path("reports/personal_strategy_replay/20260807/raw")
RESULTS_DIR = Path("reports/personal_strategy_replay/20260807/results")

LOT_SIZE = 65.0
TICK_SIZE = 0.05


def aggregate_1m_candles(candles, timeframe_minutes):
    """Session-anchored (09:15 IST) 1m -> timeframe_minutes aggregation. Rejects incomplete buckets."""
    bars = []
    curr_bucket = None
    curr_bars = []
    
    for c in candles:
        ts = c["time"]
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # 09:15 IST = 03:45 UTC
        minute_from_open = (dt.hour * 60 + dt.minute) - (3 * 60 + 45)
        if minute_from_open < 0:
            continue
            
        bucket_idx = minute_from_open // timeframe_minutes
        
        if curr_bucket is None:
            curr_bucket = bucket_idx
            curr_bars = [c]
        elif curr_bucket == bucket_idx:
            curr_bars.append(c)
        else:
            if len(curr_bars) == timeframe_minutes:
                bars.append({
                    "time": curr_bars[-1]["time"],
                    "open": curr_bars[0]["open"],
                    "high": max(b["high"] for b in curr_bars),
                    "low": min(b["low"] for b in curr_bars),
                    "close": curr_bars[-1]["close"],
                    "volume": sum(b.get("volume", 0) for b in curr_bars)
                })
            curr_bucket = bucket_idx
            curr_bars = [c]
            
    if len(curr_bars) == timeframe_minutes:
        bars.append({
            "time": curr_bars[-1]["time"],
            "open": curr_bars[0]["open"],
            "high": max(b["high"] for b in curr_bars),
            "low": min(b["low"] for b in curr_bars),
            "close": curr_bars[-1]["close"],
            "volume": sum(b.get("volume", 0) for b in curr_bars)
        })
    return bars


def run_s01_replay(ce_1m, spot_1m, master_rows):
    """Full-day S01 CE Replay."""
    ce_3m = aggregate_1m_candles(ce_1m, 3)
    closes_3m = [b["close"] for b in ce_3m]
    lows_3m = [b["low"] for b in ce_3m]
    times_3m = [b["time"] for b in ce_3m]
    
    bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
    rsi_list = compute_rsi(closes_3m, period=14)
    
    trades = []
    blocked_signals = []
    partial_signals = 0
    valid_triggers = 0
    blocked_triggers = 0
    rearm_count = 0
    
    in_trade = False
    trade_info = None
    completed_trades_count = 0
    rearm_satisfied = True
    
    for i in range(20, len(ce_3m)):
        ts = times_3m[i]
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        curr_close = closes_3m[i]
        curr_low = lows_3m[i]
        curr_bb = bb_list[i]
        curr_rsi = rsi_list[i]
        prev_rsi = rsi_list[i-1]
        
        if not curr_bb or curr_rsi is None or prev_rsi is None:
            continue
            
        c_bb = curr_close > curr_bb["upper"]
        c_rsi = prev_rsi <= 65.0 and curr_rsi > 65.0
        
        if c_bb or c_rsi:
            partial_signals += 1
            
        # Re-arm check
        if not rearm_satisfied:
            if curr_close <= curr_bb["upper"]:
                rearm_satisfied = True
                rearm_count += 1
                
        # Managing Active Position
        if in_trade:
            # Check exit conditions on current 3m bar
            # 1. Structural SL
            hit_sl = curr_low <= trade_info["stop_price"]
            # 2. Close < Middle BB
            hit_mid_bb = curr_close < curr_bb["middle"]
            # 3. Mandatory 15:25 exit (15:25 IST = 09:55 UTC)
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_exit = (dt_utc.hour == 9 and dt_utc.minute >= 55) or dt_utc.hour > 9
            
            # Track MFE / MAE
            trade_info["mfe_max"] = max(trade_info["mfe_max"], ce_3m[i]["high"] - trade_info["entry_price"])
            trade_info["mae_max"] = max(trade_info["mae_max"], trade_info["entry_price"] - ce_3m[i]["low"])
            
            exit_reason = None
            exit_price = None
            
            if hit_sl:
                exit_reason = "STRUCTURAL_SL"
                exit_price = trade_info["stop_price"]
            elif hit_mid_bb:
                exit_reason = "MIDDLE_BB"
                exit_price = curr_close
            elif time_exit:
                exit_reason = "TIME_EXIT"
                exit_price = curr_close
                
            if exit_reason:
                trade_info["exit_timestamp"] = ts_str
                trade_info["exit_price"] = exit_price
                trade_info["exit_reason"] = exit_reason
                trade_info["gross_points"] = round(exit_price - trade_info["entry_price"], 2)
                trade_info["R_multiple"] = round(trade_info["gross_points"] / trade_info["initial_risk_points"], 2) if trade_info["initial_risk_points"] > 0 else 0.0
                trade_info["MFE_points"] = round(trade_info["mfe_max"], 2)
                trade_info["MAE_points"] = round(trade_info["mae_max"], 2)
                trade_info["max_R_seen"] = round(trade_info["MFE_points"] / trade_info["initial_risk_points"], 2) if trade_info["initial_risk_points"] > 0 else 0.0
                trade_info["result"] = "WIN" if trade_info["gross_points"] > 0 else ("LOSS" if trade_info["gross_points"] < 0 else "FLAT")
                trade_info["rupee_pnl"] = round(trade_info["gross_points"] * LOT_SIZE, 2)
                
                # holding minutes
                entry_dt = datetime.strptime(trade_info["entry_timestamp"], "%H:%M:%S")
                exit_dt = datetime.strptime(ts_str, "%H:%M:%S")
                trade_info["holding_minutes"] = int((exit_dt - entry_dt).total_seconds() // 60)
                
                trades.append(trade_info)
                completed_trades_count += 1
                in_trade = False
                trade_info = None
            continue
            
        # Entry Evaluation
        if c_bb and c_rsi and rearm_satisfied and completed_trades_count < 3:
            valid_triggers += 1
            stop_price = round(curr_low - TICK_SIZE, 2)
            # Fill at next 1m OPEN
            next_1m_idx = (i + 1) * 3
            if next_1m_idx < len(ce_1m):
                entry_fill = ce_1m[next_1m_idx]["open"]
                entry_time_str = datetime.fromtimestamp(ce_1m[next_1m_idx]["time"], tz=timezone.utc).strftime("%H:%M:%S")
            else:
                entry_fill = curr_close
                entry_time_str = ts_str
                
            risk_points = round(entry_fill - stop_price, 2)
            
            if risk_points > 30.0:
                blocked_triggers += 1
                blocked_signals.append({
                    "strategy": "S01_BB_RSI_MOMENTUM",
                    "signal_timestamp": ts_str,
                    "contract": "NIFTY-Aug2026-24600-CE",
                    "trigger_close": curr_close,
                    "entry_fill": entry_fill,
                    "stop_price": stop_price,
                    "risk_points": risk_points,
                    "reason": "STRUCTURAL_RISK_GT_30"
                })
            else:
                in_trade = True
                rearm_satisfied = False
                spot_px = spot_1m[min(next_1m_idx, len(spot_1m)-1)]["close"]
                trade_info = {
                    "strategy": "S01_BB_RSI_MOMENTUM",
                    "option_type": "CE",
                    "security_id": "41015",
                    "contract": "NIFTY-Aug2026-24600-CE",
                    "strike": 24600.0,
                    "expiry": "2026-08-11",
                    "signal_timestamp": ts_str,
                    "entry_timestamp": entry_time_str,
                    "entry_price": entry_fill,
                    "entry_price_source": "NEXT_1M_OPEN",
                    "trigger_close": curr_close,
                    "trigger_high": ce_3m[i]["high"],
                    "trigger_low": curr_low,
                    "ATM_at_selection": round(spot_px / 50.0) * 50.0,
                    "OTM1_at_selection": (round(spot_px / 50.0) * 50.0) + 50.0,
                    "spot_at_selection": spot_px,
                    "stop_price": stop_price,
                    "initial_risk_points": risk_points,
                    "mfe_max": 0.0,
                    "mae_max": 0.0
                }

    return {
        "trades": trades,
        "blocked_signals": blocked_signals,
        "partial_signals": partial_signals,
        "valid_triggers": valid_triggers,
        "blocked_triggers": blocked_triggers,
        "rearm_count": rearm_count
    }


def run_s05_replay(opt_type, opt_1m, opt_06_1m, spot_1m, sec_id, strike, contract_name):
    """Full-day S05 Replay for CE or PE."""
    opt_3m = aggregate_1m_candles(opt_1m, 3)
    opt_5m = aggregate_1m_candles(opt_1m, 5)
    
    closes_3m = [b["close"] for b in opt_3m]
    times_3m = [b["time"] for b in opt_3m]
    
    bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
    
    # Prev session pivots
    h_06 = max(c["high"] for c in opt_06_1m)
    l_06 = min(c["low"] for c in opt_06_1m)
    c_06 = opt_06_1m[-1]["close"]
    pivots = compute_traditional_pivots(h_06, l_06, c_06)
    r1 = pivots["R1"]
    r4 = pivots["R4"]
    
    trades = []
    blocked_signals = []
    partial_signals = 0
    valid_triggers = 0
    blocked_triggers = 0
    rearm_count = 0
    
    in_trade = False
    trade_info = None
    completed_trades_count = 0
    rearm_satisfied = True
    
    for i in range(20, len(opt_3m)):
        ts = times_3m[i]
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        curr_close = closes_3m[i]
        prev_close = closes_3m[i-1]
        curr_bb = bb_list[i]
        
        if not curr_bb or not r1 or not r4:
            continue
            
        c_bb = curr_close > curr_bb["upper"]
        c_r1_cross = prev_close <= r1 and curr_close > r1
        
        if c_bb or c_r1_cross:
            partial_signals += 1
            
        # Re-arm check
        if not rearm_satisfied:
            if curr_close <= curr_bb["upper"] and curr_close <= r1:
                rearm_satisfied = True
                rearm_count += 1
                
        # 5m EMA15 calculation up to current timestamp
        sub_5m = [b for b in opt_5m if b["time"] <= ts]
        ema15_5m = None
        if len(sub_5m) >= 15:
            ema_list = compute_ema([b["close"] for b in sub_5m], period=15)
            ema15_5m = ema_list[-1]
            
        # Managing Active Position
        if in_trade:
            # Check exit conditions
            # 1. 20-point SL
            hit_sl = opt_3m[i]["low"] <= trade_info["stop_price"]
            # 2. Close < Middle BB
            hit_mid_bb = curr_close < curr_bb["middle"]
            # 3. Close > R4
            hit_r4 = curr_close > r4
            # 4. Close < 5m EMA15 (if available)
            hit_ema15 = (ema15_5m is not None) and (curr_close < ema15_5m)
            # 5. Mandatory 15:25 exit
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_exit = (dt_utc.hour == 9 and dt_utc.minute >= 55) or dt_utc.hour > 9
            
            # Track MFE / MAE
            trade_info["mfe_max"] = max(trade_info["mfe_max"], opt_3m[i]["high"] - trade_info["entry_price"])
            trade_info["mae_max"] = max(trade_info["mae_max"], trade_info["entry_price"] - opt_3m[i]["low"])
            
            exit_reason = None
            exit_price = None
            
            if hit_sl:
                exit_reason = "SL_20_PTS"
                exit_price = trade_info["stop_price"]
            elif hit_mid_bb:
                exit_reason = "MIDDLE_BB"
                exit_price = curr_close
            elif hit_r4:
                exit_reason = "R4_LEVEL"
                exit_price = curr_close
            elif hit_ema15:
                exit_reason = "EMA15_5M"
                exit_price = curr_close
            elif time_exit:
                exit_reason = "TIME_EXIT"
                exit_price = curr_close
                
            if exit_reason:
                trade_info["exit_timestamp"] = ts_str
                trade_info["exit_price"] = exit_price
                trade_info["exit_reason"] = exit_reason
                trade_info["gross_points"] = round(exit_price - trade_info["entry_price"], 2)
                trade_info["R_multiple"] = round(trade_info["gross_points"] / 20.0, 2)
                trade_info["MFE_points"] = round(trade_info["mfe_max"], 2)
                trade_info["MAE_points"] = round(trade_info["mae_max"], 2)
                trade_info["max_R_seen"] = round(trade_info["MFE_points"] / 20.0, 2)
                trade_info["result"] = "WIN" if trade_info["gross_points"] > 0 else ("LOSS" if trade_info["gross_points"] < 0 else "FLAT")
                trade_info["rupee_pnl"] = round(trade_info["gross_points"] * LOT_SIZE, 2)
                
                entry_dt = datetime.strptime(trade_info["entry_timestamp"], "%H:%M:%S")
                exit_dt = datetime.strptime(ts_str, "%H:%M:%S")
                trade_info["holding_minutes"] = int((exit_dt - entry_dt).total_seconds() // 60)
                
                trades.append(trade_info)
                completed_trades_count += 1
                in_trade = False
                trade_info = None
            continue
            
        # Entry Evaluation (after 09:18 IST = 03:48 UTC)
        dt_bar = datetime.fromtimestamp(ts, tz=timezone.utc)
        after_0918 = (dt_bar.hour > 3) or (dt_bar.hour == 3 and dt_bar.minute >= 48)
        
        if c_bb and c_r1_cross and rearm_satisfied and after_0918 and completed_trades_count < 3:
            valid_triggers += 1
            next_1m_idx = (i + 1) * 3
            if next_1m_idx < len(opt_1m):
                entry_fill = opt_1m[next_1m_idx]["open"]
                entry_time_str = datetime.fromtimestamp(opt_1m[next_1m_idx]["time"], tz=timezone.utc).strftime("%H:%M:%S")
            else:
                entry_fill = curr_close
                entry_time_str = ts_str
                
            stop_price = round(entry_fill - 20.0, 2)
            spot_px = spot_1m[min(next_1m_idx, len(spot_1m)-1)]["close"]
            
            in_trade = True
            rearm_satisfied = False
            trade_info = {
                "strategy": f"S05_BB_CPR_BREAKOUT_{opt_type}",
                "option_type": opt_type,
                "security_id": sec_id,
                "contract": contract_name,
                "strike": strike,
                "expiry": "2026-08-11",
                "signal_timestamp": ts_str,
                "entry_timestamp": entry_time_str,
                "entry_price": entry_fill,
                "entry_price_source": "NEXT_1M_OPEN",
                "trigger_close": curr_close,
                "trigger_high": opt_3m[i]["high"],
                "trigger_low": opt_3m[i]["low"],
                "ATM_at_selection": round(spot_px / 50.0) * 50.0,
                "OTM1_at_selection": (round(spot_px / 50.0) * 50.0) + (50.0 if opt_type == "CE" else -50.0),
                "spot_at_selection": spot_px,
                "stop_price": stop_price,
                "initial_risk_points": 20.0,
                "mfe_max": 0.0,
                "mae_max": 0.0
            }

    return {
        "trades": trades,
        "blocked_signals": blocked_signals,
        "partial_signals": partial_signals,
        "valid_triggers": valid_triggers,
        "blocked_triggers": blocked_triggers,
        "rearm_count": rearm_count
    }


def compute_metrics(trades):
    """Calculate summary performance metrics dict."""
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "TOTAL_TRADES": 0, "WINS": 0, "LOSSES": 0, "FLATS": 0, "WIN_RATE": 0.0,
            "GROSS_PREMIUM_POINTS": 0.0, "AVG_POINTS_PER_TRADE": 0.0, "MEDIAN_POINTS_PER_TRADE": 0.0,
            "AVG_WIN": 0.0, "AVG_LOSS": 0.0, "PAYOFF_RATIO": 0.0, "PROFIT_FACTOR": 0.0,
            "AVG_R": 0.0, "MEDIAN_R": 0.0, "TOTAL_R": 0.0, "BEST_TRADE": 0.0, "WORST_TRADE": 0.0,
            "MAX_CONSECUTIVE_WINS": 0, "MAX_CONSECUTIVE_LOSSES": 0, "MAX_INTRADAY_DRAWDOWN_POINTS": 0.0,
            "AVG_MFE": 0.0, "AVG_MAE": 0.0, "AVG_HOLD_MINUTES": 0.0,
            "GROSS_PNL_RUPEES": 0.0, "NET_PNL_RUPEES": "NOT_CALCULATED",
            "EXIT_REASON_COUNTS": {"SL": 0, "MIDDLE_BB": 0, "R4": 0, "EMA15": 0, "TIME_EXIT": 0}
        }
        
    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    flats = [t for t in trades if t["result"] == "FLAT"]
    
    pts = [t["gross_points"] for t in trades]
    r_mults = [t["R_multiple"] for t in trades]
    
    tot_pts = sum(pts)
    win_pts = sum(t["gross_points"] for t in wins)
    loss_pts = sum(abs(t["gross_points"]) for t in losses)
    
    avg_win = (win_pts / len(wins)) if wins else 0.0
    avg_loss = (loss_pts / len(losses)) if losses else 0.0
    
    # Drawdown calculation
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pts:
        equity += p
        if equity > peak: peak = equity
        dd = peak - equity
        if dd > max_dd: max_dd = dd
        
    # Consecutive win/loss streaks
    max_c_win = 0
    max_c_loss = 0
    curr_w = 0
    curr_l = 0
    for t in trades:
        if t["result"] == "WIN":
            curr_w += 1; curr_l = 0
            if curr_w > max_c_win: max_c_win = curr_w
        elif t["result"] == "LOSS":
            curr_l += 1; curr_w = 0
            if curr_l > max_c_loss: max_c_loss = curr_l
        else:
            curr_w = 0; curr_l = 0
            
    exit_counts = {"SL": 0, "MIDDLE_BB": 0, "R4": 0, "EMA15": 0, "TIME_EXIT": 0}
    for t in trades:
        reason = t["exit_reason"]
        if "SL" in reason: exit_counts["SL"] += 1
        elif "MIDDLE_BB" in reason: exit_counts["MIDDLE_BB"] += 1
        elif "R4" in reason: exit_counts["R4"] += 1
        elif "EMA15" in reason: exit_counts["EMA15"] += 1
        elif "TIME" in reason: exit_counts["TIME_EXIT"] += 1

    return {
        "TOTAL_TRADES": total_trades,
        "WINS": len(wins),
        "LOSSES": len(losses),
        "FLATS": len(flats),
        "WIN_RATE": round((len(wins) / total_trades) * 100.0, 2),
        "GROSS_PREMIUM_POINTS": round(tot_pts, 2),
        "AVG_POINTS_PER_TRADE": round(tot_pts / total_trades, 2),
        "MEDIAN_POINTS_PER_TRADE": round(sorted(pts)[total_trades // 2], 2),
        "AVG_WIN": round(avg_win, 2),
        "AVG_LOSS": round(avg_loss, 2),
        "PAYOFF_RATIO": round(avg_win / avg_loss, 2) if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0),
        "PROFIT_FACTOR": round(win_pts / loss_pts, 2) if loss_pts > 0 else (999.0 if win_pts > 0 else 0.0),
        "AVG_R": round(sum(r_mults) / total_trades, 2),
        "MEDIAN_R": round(sorted(r_mults)[total_trades // 2], 2),
        "TOTAL_R": round(sum(r_mults), 2),
        "BEST_TRADE": round(max(pts), 2),
        "WORST_TRADE": round(min(pts), 2),
        "MAX_CONSECUTIVE_WINS": max_c_win,
        "MAX_CONSECUTIVE_LOSSES": max_c_loss,
        "MAX_INTRADAY_DRAWDOWN_POINTS": round(max_dd, 2),
        "AVG_MFE": round(sum(t["MFE_points"] for t in trades) / total_trades, 2),
        "AVG_MAE": round(sum(t["MAE_points"] for t in trades) / total_trades, 2),
        "AVG_HOLD_MINUTES": round(sum(t["holding_minutes"] for t in trades) / total_trades, 1),
        "GROSS_PNL_RUPEES": round(tot_pts * LOT_SIZE, 2),
        "NET_PNL_RUPEES": "NOT_CALCULATED",
        "TRANSACTION_COSTS_NOT_INCLUDED": True,
        "EXIT_REASON_COUNTS": exit_counts
    }


def main():
    print("STARTING E8B FULL-DAY TRADE REPLAY...")
    
    with open(RAW_DIR / "nifty_spot_1m_20260807.json") as f:
        spot_1m = json.load(f)["candles"]
        
    with open(RAW_DIR / "ce_41015_1m_20260807.json") as f:
        ce_24600_07 = json.load(f)["candles"]
        
    with open(RAW_DIR / "pe_41012_1m_20260807.json") as f:
        pe_24500_07 = json.load(f)["candles"]
        
    with open(RAW_DIR / "ce_41015_1m_20260806.json") as f:
        ce_24600_06 = json.load(f)["candles"]
        
    with open(RAW_DIR / "pe_41012_1m_20260806.json") as f:
        pe_24500_06 = json.load(f)["candles"]
        
    with open(RAW_DIR / "dhan_instrument_master.json") as f:
        master_rows = json.load(f)["rows"]

    # 1. Run S01 Replay
    res_s01 = run_s01_replay(ce_24600_07, spot_1m, master_rows)
    
    # 2. Run S05 CE Replay
    res_s05_ce = run_s05_replay("CE", ce_24600_07, ce_24600_06, spot_1m, "41015", 24600.0, "NIFTY-Aug2026-24600-CE")
    
    # 3. Run S05 PE Replay
    res_s05_pe = run_s05_replay("PE", pe_24500_07, pe_24500_06, spot_1m, "41012", 24500.0, "NIFTY-Aug2026-24500-PE")
    
    # Save Trade Ledgers
    with open(RESULTS_DIR / "S01_TRADES.jsonl", "w") as f:
        for t in res_s01["trades"]: f.write(json.dumps(t) + "\n")
        
    with open(RESULTS_DIR / "S05_CE_TRADES.jsonl", "w") as f:
        for t in res_s05_ce["trades"]: f.write(json.dumps(t) + "\n")
        
    with open(RESULTS_DIR / "S05_PE_TRADES.jsonl", "w") as f:
        for t in res_s05_pe["trades"]: f.write(json.dumps(t) + "\n")
        
    all_blocked = res_s01["blocked_signals"] + res_s05_ce["blocked_signals"] + res_s05_pe["blocked_signals"]
    with open(RESULTS_DIR / "BLOCKED_SIGNALS.jsonl", "w") as f:
        for b in all_blocked: f.write(json.dumps(b) + "\n")
        
    # Calculate Metrics
    m_s01 = compute_metrics(res_s01["trades"])
    m_s05_ce = compute_metrics(res_s05_ce["trades"])
    m_s05_pe = compute_metrics(res_s05_pe["trades"])
    
    all_s05_trades = res_s05_ce["trades"] + res_s05_pe["trades"]
    m_s05_comb = compute_metrics(all_s05_trades)
    
    all_trades = res_s01["trades"] + all_s05_trades
    m_all = compute_metrics(all_trades)
    
    daily_metrics = {
        "S01": m_s01,
        "S05_CE": m_s05_ce,
        "S05_PE": m_s05_pe,
        "S05_COMBINED": m_s05_comb,
        "ALL_S01_S05": m_all,
        "SIGNALS_SUMMARY": {
            "PARTIAL_SIGNALS": res_s01["partial_signals"] + res_s05_ce["partial_signals"] + res_s05_pe["partial_signals"],
            "VALID_TRIGGERS": res_s01["valid_triggers"] + res_s05_ce["valid_triggers"] + res_s05_pe["valid_triggers"],
            "BLOCKED_TRIGGERS": res_s01["blocked_triggers"] + res_s05_ce["blocked_triggers"] + res_s05_pe["blocked_triggers"],
            "REARM_COUNT": res_s01["rearm_count"] + res_s05_ce["rearm_count"] + res_s05_pe["rearm_count"]
        }
    }
    
    with open(RESULTS_DIR / "DAILY_REPLAY_METRICS.json", "w") as f:
        json.dump(daily_metrics, f, indent=2)
        
    print("E8B FULL-DAY TRADE REPLAY COMPLETED!")
    print(f"S01 TRADES: {len(res_s01['trades'])}, PnL Points: {m_s01['GROSS_PREMIUM_POINTS']}")
    print(f"S05 CE TRADES: {len(res_s05_ce['trades'])}, PnL Points: {m_s05_ce['GROSS_PREMIUM_POINTS']}")
    print(f"S05 PE TRADES: {len(res_s05_pe['trades'])}, PnL Points: {m_s05_pe['GROSS_PREMIUM_POINTS']}")


if __name__ == "__main__":
    main()
