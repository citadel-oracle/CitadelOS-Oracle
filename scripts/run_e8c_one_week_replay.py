"""E8C S01 + S05 One-Week Real Trade Replay Harness (03-Aug-2026 to 07-Aug-2026).

Executes deterministic multi-day trade replay from immutable frozen raw data.
Calculates daily breakdown, weekly totals, trade ledgers, MFE/MAE, R-multiples, and Rupee P&L.
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

RAW_DIR = Path("reports/personal_strategy_replay/20260803_20260807/raw")
RESULTS_DIR = Path("reports/personal_strategy_replay/20260803_20260807/results")

LOT_SIZE = 65.0
TICK_SIZE = 0.05

DATES = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
PREV_DATES = {
    "2026-08-03": "2026-07-31",
    "2026-08-04": "2026-08-03",
    "2026-08-05": "2026-08-04",
    "2026-08-06": "2026-08-05",
    "2026-08-07": "2026-08-06",
}
EXPIRIES = {
    "2026-08-03": "2026-08-06",
    "2026-08-04": "2026-08-06",
    "2026-08-05": "2026-08-06",
    "2026-08-06": "2026-08-06",
    "2026-08-07": "2026-08-11",
}


def load_candles_from_raw(data):
    """Convert raw API dictionary output to list of candle objects."""
    if not isinstance(data, dict):
        return []
    if "candles" in data and isinstance(data["candles"], list):
        return data["candles"]
    
    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    timestamps = data.get("timestamp", [])
    
    if not all(isinstance(v, list) for v in (opens, highs, lows, closes, timestamps)):
        return []
        
    candles = []
    for i in range(len(timestamps)):
        candles.append({
            "time": float(timestamps[i]),
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]) if i < len(volumes) else 0.0
        })
    return candles


def aggregate_1m_candles(candles, timeframe_minutes):
    """Session-anchored (09:15 IST) 1m -> timeframe_minutes aggregation. Rejects incomplete buckets."""
    bars = []
    curr_bucket = None
    curr_bars = []
    
    for c in candles:
        ts = c["time"]
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
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


def resolve_sec_id(strike, opt_type, exp_date, master_rows):
    """Resolve Dhan security ID from master for given strike, option type, and expiry date."""
    for r in master_rows:
        if r.get("UNDERLYING_SYMBOL") == "NIFTY" and r.get("SM_EXPIRY_DATE") == exp_date:
            s_price = float(r.get("STRIKE_PRICE", 0))
            if s_price == strike and r.get("OPTION_TYPE") == opt_type:
                return r.get("SECURITY_ID"), r.get("SYMBOL_NAME")
    return None, None


def replay_day_s01(date_str, master_rows):
    """S01 CE Replay for a single trading date."""
    spot_fp = RAW_DIR / f"nifty_spot_1m_{date_str.replace('-', '')}.json"
    if not spot_fp.exists():
        return {"trades": [], "blocked": [], "partial": 0, "triggers": 0, "blocked_trig": 0, "rearms": 0}
        
    with open(spot_fp) as f:
        spot_candles = load_candles_from_raw(json.load(f))
        
    if not spot_candles:
        return {"trades": [], "blocked": [], "partial": 0, "triggers": 0, "blocked_trig": 0, "rearms": 0}

    exp_date = EXPIRIES[date_str]
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
    
    # Pre-load option candles cache for resolved security IDs to minimize disk I/O
    opt_cache = {}
    
    # Process spot candle by spot candle to build session 3m bars dynamically
    spot_3m = aggregate_1m_candles(spot_candles, 3)
    
    for i in range(20, len(spot_3m)):
        ts = spot_3m[i]["time"]
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        curr_spot = spot_3m[i]["close"]
        
        # Dynamic OTM1 resolution
        atm_strike = round(curr_spot / 50.0) * 50.0
        otm1_ce_strike = atm_strike + 50.0
        sec_id, contract_name = resolve_sec_id(otm1_ce_strike, "CE", exp_date, master_rows)
        
        if not sec_id:
            continue
            
        # Load option candles for this security ID if not cached
        if sec_id not in opt_cache:
            opt_fp = RAW_DIR / f"opt_{sec_id}_1m_{date_str.replace('-', '')}.json"
            if opt_fp.exists():
                with open(opt_fp) as f:
                    opt_cache[sec_id] = load_candles_from_raw(json.load(f))
            else:
                opt_cache[sec_id] = []
                
        ce_1m = opt_cache[sec_id]
        if not ce_1m:
            continue
            
        ce_3m = aggregate_1m_candles(ce_1m, 3)
        if i >= len(ce_3m):
            continue
            
        closes_3m = [b["close"] for b in ce_3m[:i+1]]
        lows_3m = [b["low"] for b in ce_3m[:i+1]]
        
        bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
        rsi_list = compute_rsi(closes_3m, period=14)
        
        curr_close = closes_3m[-1]
        curr_low = lows_3m[-1]
        curr_bb = bb_list[-1]
        curr_rsi = rsi_list[-1]
        prev_rsi = rsi_list[-2]
        
        if not curr_bb or curr_rsi is None or prev_rsi is None:
            continue
            
        c_bb = curr_close > curr_bb["upper"]
        c_rsi = prev_rsi <= 65.0 and curr_rsi > 65.0
        
        if c_bb or c_rsi:
            partial_signals += 1
            
        if not rearm_satisfied:
            if curr_close <= curr_bb["upper"]:
                rearm_satisfied = True
                rearm_count += 1
                
        # Active Trade Management
        if in_trade:
            hit_sl = curr_low <= trade_info["stop_price"]
            hit_mid_bb = curr_close < curr_bb["middle"]
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_exit = (dt_utc.hour == 9 and dt_utc.minute >= 55) or dt_utc.hour > 9
            
            trade_info["mfe_max"] = max(trade_info["mfe_max"], ce_3m[i]["high"] - trade_info["entry_price"])
            trade_info["mae_max"] = max(trade_info["mae_max"], trade_info["entry_price"] - curr_low)
            
            exit_reason = None
            exit_price = None
            if hit_sl:
                exit_reason = "STRUCTURAL_SL"; exit_price = trade_info["stop_price"]
            elif hit_mid_bb:
                exit_reason = "MIDDLE_BB"; exit_price = curr_close
            elif time_exit:
                exit_reason = "TIME_EXIT"; exit_price = curr_close
                
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
                    "date": date_str,
                    "strategy": "S01_BB_RSI_MOMENTUM",
                    "signal_timestamp": ts_str,
                    "contract": contract_name or f"CE_{otm1_ce_strike}",
                    "trigger_close": curr_close,
                    "entry_fill": entry_fill,
                    "stop_price": stop_price,
                    "risk_points": risk_points,
                    "reason": "STRUCTURAL_RISK_GT_30"
                })
            else:
                in_trade = True
                rearm_satisfied = False
                trade_info = {
                    "date": date_str,
                    "strategy": "S01_BB_RSI_MOMENTUM",
                    "option_type": "CE",
                    "security_id": sec_id,
                    "contract": contract_name or f"CE_{otm1_ce_strike}",
                    "strike": otm1_ce_strike,
                    "expiry": exp_date,
                    "signal_timestamp": ts_str,
                    "entry_timestamp": entry_time_str,
                    "entry_price": entry_fill,
                    "entry_price_source": "NEXT_1M_OPEN",
                    "trigger_close": curr_close,
                    "trigger_high": ce_3m[i]["high"],
                    "trigger_low": curr_low,
                    "ATM_at_selection": atm_strike,
                    "OTM1_at_selection": otm1_ce_strike,
                    "spot_at_selection": curr_spot,
                    "stop_price": stop_price,
                    "initial_risk_points": risk_points,
                    "mfe_max": 0.0,
                    "mae_max": 0.0
                }

    return {
        "trades": trades,
        "blocked": blocked_signals,
        "partial": partial_signals,
        "triggers": valid_triggers,
        "blocked_trig": blocked_triggers,
        "rearms": rearm_count
    }


def replay_day_s05(opt_type, date_str, master_rows):
    """S05 CE or PE Replay for a single trading date."""
    spot_fp = RAW_DIR / f"nifty_spot_1m_{date_str.replace('-', '')}.json"
    if not spot_fp.exists():
        return {"trades": [], "blocked": [], "partial": 0, "triggers": 0, "blocked_trig": 0, "rearms": 0}
        
    with open(spot_fp) as f:
        spot_candles = load_candles_from_raw(json.load(f))
        
    if not spot_candles:
        return {"trades": [], "blocked": [], "partial": 0, "triggers": 0, "blocked_trig": 0, "rearms": 0}

    exp_date = EXPIRIES[date_str]
    prev_date_str = PREV_DATES[date_str]
    
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
    
    opt_cache_07 = {}
    opt_cache_06 = {}
    
    spot_3m = aggregate_1m_candles(spot_candles, 3)
    
    for i in range(20, len(spot_3m)):
        ts = spot_3m[i]["time"]
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        curr_spot = spot_3m[i]["close"]
        
        atm_strike = round(curr_spot / 50.0) * 50.0
        otm1_strike = atm_strike + 50.0 if opt_type == "CE" else atm_strike - 50.0
        sec_id, contract_name = resolve_sec_id(otm1_strike, opt_type, exp_date, master_rows)
        
        if not sec_id:
            continue
            
        if sec_id not in opt_cache_07:
            fp_07 = RAW_DIR / f"opt_{sec_id}_1m_{date_str.replace('-', '')}.json"
            opt_cache_07[sec_id] = load_candles_from_raw(json.load(fp_07)) if fp_07.exists() else []
            
        if sec_id not in opt_cache_06:
            fp_06 = RAW_DIR / f"opt_{sec_id}_1m_{prev_date_str.replace('-', '')}.json"
            opt_cache_06[sec_id] = load_candles_from_raw(json.load(fp_06)) if fp_06.exists() else []
            
        opt_1m = opt_cache_07[sec_id]
        opt_06_1m = opt_cache_06[sec_id]
        
        if not opt_1m or not opt_06_1m:
            continue
            
        opt_3m = aggregate_1m_candles(opt_1m, 3)
        opt_5m = aggregate_1m_candles(opt_1m, 5)
        
        if i >= len(opt_3m):
            continue
            
        closes_3m = [b["close"] for b in opt_3m[:i+1]]
        curr_close = closes_3m[-1]
        prev_close = closes_3m[-2]
        
        bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
        curr_bb = bb_list[-1]
        
        h_06 = max(c["high"] for c in opt_06_1m)
        l_06 = min(c["low"] for c in opt_06_1m)
        c_06 = opt_06_1m[-1]["close"]
        pivots = compute_traditional_pivots(h_06, l_06, c_06)
        r1 = pivots["R1"]
        r4 = pivots["R4"]
        
        if not curr_bb or not r1 or not r4:
            continue
            
        c_bb = curr_close > curr_bb["upper"]
        c_r1_cross = prev_close <= r1 and curr_close > r1
        
        if c_bb or c_r1_cross:
            partial_signals += 1
            
        if not rearm_satisfied:
            if curr_close <= curr_bb["upper"] and curr_close <= r1:
                rearm_satisfied = True
                rearm_count += 1
                
        sub_5m = [b for b in opt_5m if b["time"] <= ts]
        ema15_5m = None
        if len(sub_5m) >= 15:
            ema_list = compute_ema([b["close"] for b in sub_5m], period=15)
            ema15_5m = ema_list[-1]
            
        # Active Trade Management
        if in_trade:
            hit_sl = opt_3m[i]["low"] <= trade_info["stop_price"]
            hit_mid_bb = curr_close < curr_bb["middle"]
            hit_r4 = curr_close > r4
            hit_ema15 = (ema15_5m is not None) and (curr_close < ema15_5m)
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_exit = (dt_utc.hour == 9 and dt_utc.minute >= 55) or dt_utc.hour > 9
            
            trade_info["mfe_max"] = max(trade_info["mfe_max"], opt_3m[i]["high"] - trade_info["entry_price"])
            trade_info["mae_max"] = max(trade_info["mae_max"], trade_info["entry_price"] - opt_3m[i]["low"])
            
            exit_reason = None
            exit_price = None
            
            if hit_sl:
                exit_reason = "SL_20_PTS"; exit_price = trade_info["stop_price"]
            elif hit_mid_bb:
                exit_reason = "MIDDLE_BB"; exit_price = curr_close
            elif hit_r4:
                exit_reason = "R4_LEVEL"; exit_price = curr_close
            elif hit_ema15:
                exit_reason = "EMA15_5M"; exit_price = curr_close
            elif time_exit:
                exit_reason = "TIME_EXIT"; exit_price = curr_close
                
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
            
            in_trade = True
            rearm_satisfied = False
            trade_info = {
                "date": date_str,
                "strategy": f"S05_BB_CPR_BREAKOUT_{opt_type}",
                "option_type": opt_type,
                "security_id": sec_id,
                "contract": contract_name or f"{opt_type}_{otm1_strike}",
                "strike": otm1_strike,
                "expiry": exp_date,
                "signal_timestamp": ts_str,
                "entry_timestamp": entry_time_str,
                "entry_price": entry_fill,
                "entry_price_source": "NEXT_1M_OPEN",
                "trigger_close": curr_close,
                "trigger_high": opt_3m[i]["high"],
                "trigger_low": opt_3m[i]["low"],
                "ATM_at_selection": atm_strike,
                "OTM1_at_selection": otm1_strike,
                "spot_at_selection": curr_spot,
                "stop_price": stop_price,
                "initial_risk_points": 20.0,
                "mfe_max": 0.0,
                "mae_max": 0.0
            }

    return {
        "trades": trades,
        "blocked": blocked_signals,
        "partial": partial_signals,
        "triggers": valid_triggers,
        "blocked_trig": blocked_triggers,
        "rearms": rearm_count
    }


def compute_metrics(trades):
    """Calculate summary performance metrics dict for trade array."""
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "TOTAL_TRADES": 0, "WINS": 0, "LOSSES": 0, "FLATS": 0, "WIN_RATE": "N/A",
            "GROSS_PREMIUM_POINTS": 0.0, "AVG_POINTS_PER_TRADE": 0.0, "MEDIAN_POINTS_PER_TRADE": 0.0,
            "AVG_WIN": 0.0, "AVG_LOSS": 0.0, "PAYOFF_RATIO": "N/A", "PROFIT_FACTOR": "N/A",
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
    
    equity = 0.0; peak = 0.0; max_dd = 0.0
    for p in pts:
        equity += p
        if equity > peak: peak = equity
        dd = peak - equity
        if dd > max_dd: max_dd = dd
        
    max_c_win = 0; max_c_loss = 0; curr_w = 0; curr_l = 0
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
        "PAYOFF_RATIO": round(avg_win / avg_loss, 2) if avg_loss > 0 else "N/A",
        "PROFIT_FACTOR": round(win_pts / loss_pts, 2) if loss_pts > 0 else "N/A",
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
    print("STARTING E8C ONE-WEEK REAL TRADE REPLAY (03-AUG TO 07-AUG)...")
    
    with open(RAW_DIR / "dhan_instrument_master.json") as f:
        master_rows = json.load(f)["rows"]

    daily_results = {}
    all_s01_trades = []
    all_s05_ce_trades = []
    all_s05_pe_trades = []
    all_blocked_signals = []
    
    tot_partial = 0
    tot_valid_trig = 0
    tot_blocked_trig = 0
    tot_rearms = 0

    for dt in DATES:
        res_s01 = replay_day_s01(dt, master_rows)
        res_s05_ce = replay_day_s05("CE", dt, master_rows)
        res_s05_pe = replay_day_s05("PE", dt, master_rows)
        
        all_s01_trades.extend(res_s01["trades"])
        all_s05_ce_trades.extend(res_s05_ce["trades"])
        all_s05_pe_trades.extend(res_s05_pe["trades"])
        
        all_blocked_signals.extend(res_s01["blocked"] + res_s05_ce["blocked"] + res_s05_pe["blocked"])
        
        tot_partial += (res_s01["partial"] + res_s05_ce["partial"] + res_s05_pe["partial"])
        tot_valid_trig += (res_s01["triggers"] + res_s05_ce["triggers"] + res_s05_pe["triggers"])
        tot_blocked_trig += (res_s01["blocked_trig"] + res_s05_ce["blocked_trig"] + res_s05_pe["blocked_trig"])
        tot_rearms += (res_s01["rearms"] + res_s05_ce["rearms"] + res_s05_pe["rearms"])
        
        daily_pnl_pts = (
            sum(t["gross_points"] for t in res_s01["trades"]) +
            sum(t["gross_points"] for t in res_s05_ce["trades"]) +
            sum(t["gross_points"] for t in res_s05_pe["trades"])
        )
        
        daily_results[dt] = {
            "S01_TRADES": len(res_s01["trades"]),
            "S01_POINTS": round(sum(t["gross_points"] for t in res_s01["trades"]), 2),
            "S05_CE_TRADES": len(res_s05_ce["trades"]),
            "S05_CE_POINTS": round(sum(t["gross_points"] for t in res_s05_ce["trades"]), 2),
            "S05_PE_TRADES": len(res_s05_pe["trades"]),
            "S05_PE_POINTS": round(sum(t["gross_points"] for t in res_s05_pe["trades"]), 2),
            "COMBINED_POINTS": round(daily_pnl_pts, 2),
            "COMBINED_RUPEE_PNL": round(daily_pnl_pts * LOT_SIZE, 2)
        }

    # Save Ledgers
    with open(RESULTS_DIR / "S01_TRADES.jsonl", "w") as f:
        for t in all_s01_trades: f.write(json.dumps(t) + "\n")
        
    with open(RESULTS_DIR / "S05_CE_TRADES.jsonl", "w") as f:
        for t in all_s05_ce_trades: f.write(json.dumps(t) + "\n")
        
    with open(RESULTS_DIR / "S05_PE_TRADES.jsonl", "w") as f:
        for t in all_s05_pe_trades: f.write(json.dumps(t) + "\n")
        
    with open(RESULTS_DIR / "BLOCKED_SIGNALS.jsonl", "w") as f:
        for b in all_blocked_signals: f.write(json.dumps(b) + "\n")
        
    m_s01 = compute_metrics(all_s01_trades)
    m_s05_ce = compute_metrics(all_s05_ce_trades)
    m_s05_pe = compute_metrics(all_s05_pe_trades)
    
    all_s05_trades = all_s05_ce_trades + all_s05_pe_trades
    m_s05_comb = compute_metrics(all_s05_trades)
    
    all_combined_trades = all_s01_trades + all_s05_trades
    m_all_comb = compute_metrics(all_combined_trades)
    
    weekly_metrics = {
        "DAILY_BREAKDOWN": daily_results,
        "S01": m_s01,
        "S05_CE": m_s05_ce,
        "S05_PE": m_s05_pe,
        "S05_COMBINED": m_s05_comb,
        "ALL_S01_S05": m_all_comb,
        "SIGNALS_SUMMARY": {
            "PARTIAL_SIGNALS": tot_partial,
            "VALID_TRIGGERS": tot_valid_trig,
            "BLOCKED_TRIGGERS": tot_blocked_trig,
            "REARM_COUNT": tot_rearms
        }
    }
    
    with open(RESULTS_DIR / "WEEKLY_REPLAY_METRICS.json", "w") as f:
        json.dump(weekly_metrics, f, indent=2)
        
    print("E8C ONE-WEEK REAL TRADE REPLAY COMPLETED SUCCESSFULLY!")
    print(f"TOTAL S01 TRADES: {len(all_s01_trades)}")
    print(f"TOTAL S05 CE TRADES: {len(all_s05_ce_trades)}")
    print(f"TOTAL S05 PE TRADES: {len(all_s05_pe_trades)}")
    print(f"WEEKLY COMBINED RUPEE PNL: ₹{m_all_comb['GROSS_PNL_RUPEES']}")


if __name__ == "__main__":
    main()
