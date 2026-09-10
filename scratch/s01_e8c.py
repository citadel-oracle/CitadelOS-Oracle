def replay_day_s01(date_str, master_rows):
    """S01 CE Replay for a single trading date."""
    spot_fp = RAW_DIR / f"spot_1m_{date_str.replace('-', '')}.json"
    if not spot_fp.exists():
        return {'trades': [], 'blocked': [], 'diag': {}, 'trace': []}
    with open(spot_fp) as f:
        spot_candles = load_candles(json.load(f))
    if not spot_candles:
        return {'trades': [], 'blocked': [], 'diag': {}, 'trace': []}
    exp_date = get_nifty_weekly_expiry(date_str)
    spot_3m = aggregate_1m_candles(spot_candles, 3)
    trades = []
    blocked_signals = []
    trace_records = []
    bb_break_cnt = 0
    rsi_cross_cnt = 0
    bb_and_rsi_cnt = 0
    partial_cnt = 0
    in_trade = False
    trade_info = None
    completed_trades_count = 0
    rearm_satisfied = True
    for i in range(20, len(spot_3m)):
        ts = spot_3m[i]['time']
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M:%S')
        curr_spot = spot_3m[i]['close']
        atm_strike = round(curr_spot / 50.0) * 50.0
        otm1_ce_strike = atm_strike + 50.0
        ce_1m, data_src, sec_id, contract_name = load_option_candles_for_session(date_str, 'CE', otm1_ce_strike, exp_date, master_rows)
        if not ce_1m:
            continue
        ce_3m = aggregate_1m_candles(ce_1m, 3)
        if i >= len(ce_3m):
            continue
        closes_3m = [b['close'] for b in ce_3m[:i + 1]]
        lows_3m = [b['low'] for b in ce_3m[:i + 1]]
        bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
        rsi_list = compute_rsi(closes_3m, period=14)
        curr_close = closes_3m[-1]
        curr_low = lows_3m[-1]
        curr_bb = bb_list[-1]
        curr_rsi = rsi_list[-1]
        prev_rsi = rsi_list[-2]
        if not curr_bb or curr_rsi is None or prev_rsi is None:
            continue
        c_bb = curr_close > curr_bb['upper']
        c_rsi = prev_rsi <= 65.0 and curr_rsi > 65.0
        if c_bb:
            bb_break_cnt += 1
        if c_rsi:
            rsi_cross_cnt += 1
        if c_bb and c_rsi:
            bb_and_rsi_cnt += 1
        if c_bb or c_rsi:
            partial_cnt += 1
        trace_records.append({'date': date_str, 'strategy': 'S01', 'timestamp': ts_str, 'contract': contract_name, 'close': curr_close, 'upper_bb': curr_bb['upper'], 'prev_rsi': prev_rsi, 'rsi': curr_rsi, 'c_bb': c_bb, 'c_rsi': c_rsi, 'partial': c_bb or c_rsi, 'trigger': c_bb and c_rsi})
        if not rearm_satisfied:
            if curr_close <= curr_bb['upper']:
                rearm_satisfied = True
        if in_trade:
            hit_sl = curr_low <= trade_info['stop_price']
            hit_mid_bb = curr_close < curr_bb['middle']
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_exit = dt_utc.hour == 9 and dt_utc.minute >= 55 or dt_utc.hour > 9
            trade_info['mfe_max'] = max(trade_info['mfe_max'], ce_3m[i]['high'] - trade_info['entry_price'])
            trade_info['mae_max'] = max(trade_info['mae_max'], trade_info['entry_price'] - curr_low)
            exit_reason = None
            exit_price = None
            if hit_sl:
                exit_reason = 'STRUCTURAL_SL'
                next_1m_idx = i * 3
                if next_1m_idx < len(ce_1m) and ce_1m[next_1m_idx]['open'] < trade_info['stop_price']:
                    exit_price = ce_1m[next_1m_idx]['open']
                else:
                    exit_price = trade_info['stop_price']
            elif hit_mid_bb:
                exit_reason = 'MIDDLE_BB'
                exit_price = curr_close
            elif time_exit:
                exit_reason = 'TIME_EXIT'
                exit_price = curr_close
            if exit_reason:
                trade_info['exit_timestamp'] = ts_str
                trade_info['exit_price'] = exit_price
                trade_info['exit_reason'] = exit_reason
                trade_info['gross_points'] = round(exit_price - trade_info['entry_price'], 2)
                trade_info['R_multiple'] = round(trade_info['gross_points'] / trade_info['initial_risk_points'], 2) if trade_info['initial_risk_points'] > 0 else 0.0
                trade_info['MFE_points'] = round(trade_info['mfe_max'], 2)
                trade_info['MAE_points'] = round(trade_info['mae_max'], 2)
                trade_info['max_R_seen'] = round(trade_info['MFE_points'] / trade_info['initial_risk_points'], 2) if trade_info['initial_risk_points'] > 0 else 0.0
                trade_info['result'] = 'WIN' if trade_info['gross_points'] > 0 else 'LOSS' if trade_info['gross_points'] < 0 else 'FLAT'
                trade_info['rupee_pnl'] = round(trade_info['gross_points'] * LOT_SIZE, 2)
                entry_dt = datetime.strptime(trade_info['entry_timestamp'], '%H:%M:%S')
                exit_dt = datetime.strptime(ts_str, '%H:%M:%S')
                trade_info['holding_minutes'] = int((exit_dt - entry_dt).total_seconds() // 60)
                trades.append(trade_info)
                completed_trades_count += 1
                in_trade = False
                trade_info = None
            continue
        if c_bb and c_rsi and rearm_satisfied and (completed_trades_count < 3):
            stop_price = round(curr_low - TICK_SIZE, 2)
            next_1m_idx = (i + 1) * 3
            entry_fill = ce_1m[next_1m_idx]['open'] if next_1m_idx < len(ce_1m) else curr_close
            entry_time_str = datetime.fromtimestamp(ce_1m[next_1m_idx]['time'], tz=timezone.utc).strftime('%H:%M:%S') if next_1m_idx < len(ce_1m) else ts_str
            risk_points = round(entry_fill - stop_price, 2)
            if risk_points > 30.0:
                blocked_signals.append({'date': date_str, 'strategy': 'S01_BB_RSI_MOMENTUM', 'signal_timestamp': ts_str, 'contract': contract_name, 'trigger_close': curr_close, 'entry_fill': entry_fill, 'stop_price': stop_price, 'risk_points': risk_points, 'reason': 'STRUCTURAL_RISK_GT_30'})
            else:
                in_trade = True
                rearm_satisfied = False
                trade_info = {'date': date_str, 'strategy': 'S01_BB_RSI_MOMENTUM', 'option_type': 'CE', 'security_id': sec_id, 'contract': contract_name, 'strike': otm1_ce_strike, 'expiry': exp_date, 'signal_timestamp': ts_str, 'entry_timestamp': entry_time_str, 'entry_price': entry_fill, 'entry_price_source': 'NEXT_1M_OPEN', 'trigger_close': curr_close, 'trigger_high': ce_3m[i]['high'], 'trigger_low': curr_low, 'ATM_at_selection': atm_strike, 'OTM1_at_selection': otm1_ce_strike, 'spot_at_selection': curr_spot, 'stop_price': stop_price, 'initial_risk_points': risk_points, 'mfe_max': 0.0, 'mae_max': 0.0}
    diag = {'BB_BREAK_COUNT': bb_break_cnt, 'RSI_CROSS_65_COUNT': rsi_cross_cnt, 'BB_AND_RSI_SAME_BAR_COUNT': bb_and_rsi_cnt, 'PARTIAL_COUNT': partial_cnt}
    return {'trades': trades, 'blocked': blocked_signals, 'diag': diag, 'trace': trace_records}