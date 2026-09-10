def replay_day_s01(date_str, master_rows):
    spot_fp = RAW_DIR / f"spot_1m_{date_str.replace('-', '')}.json"
    if not spot_fp.exists():
        return {'trades': [], 'blocked': [], 'diag': {}, 'trace': []}
    with open(spot_fp) as f:
        spot_candles = load_candles(json.load(f))
    if not spot_candles:
        return {'trades': [], 'blocked': [], 'diag': {}, 'trace': []}
    exp_date = get_nifty_weekly_expiry(date_str)
    spot_3m = aggregate_1m_candles(spot_candles, 3)
    trades, blocked, trace = ([], [], [])
    bb_brk = rsi_x = bb_rsi = partial = 0
    in_trade = False
    trade_info = None
    done_cnt = 0
    rearm = True
    for i in range(20, len(spot_3m)):
        ts = spot_3m[i]['time']
        ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M:%S')
        curr_spot = spot_3m[i]['close']
        atm = round(curr_spot / 50.0) * 50.0
        otm1 = atm + 50.0
        ce_1m, _, sec_id, cname = load_option_candles(date_str, 'CE', otm1, exp_date, master_rows)
        if not ce_1m:
            continue
        ce_3m = aggregate_1m_candles(ce_1m, 3)
        if i >= len(ce_3m):
            continue
        closes_3m = [b['close'] for b in ce_3m[:i + 1]]
        lows_3m = [b['low'] for b in ce_3m[:i + 1]]
        bb_list = compute_bollinger_bands(closes_3m, 20, 2.0)
        rsi_list = compute_rsi(closes_3m, 14)
        curr_cl = closes_3m[-1]
        curr_lo = lows_3m[-1]
        curr_bb = bb_list[-1]
        curr_rsi = rsi_list[-1]
        prev_rsi = rsi_list[-2]
        if not curr_bb or curr_rsi is None or prev_rsi is None:
            continue
        c_bb = curr_cl > curr_bb['upper']
        c_rsi = prev_rsi <= 65.0 and curr_rsi > 65.0
        if c_bb:
            bb_brk += 1
        if c_rsi:
            rsi_x += 1
        if c_bb and c_rsi:
            bb_rsi += 1
        if c_bb or c_rsi:
            partial += 1
        trace.append({'date': date_str, 'strategy': 'S01', 'timestamp': ts_str, 'contract': cname, 'close': curr_cl, 'upper_bb': curr_bb['upper'], 'prev_rsi': prev_rsi, 'rsi': curr_rsi, 'c_bb': c_bb, 'c_rsi': c_rsi, 'partial': c_bb or c_rsi, 'trigger': c_bb and c_rsi})
        if not rearm:
            if curr_cl <= curr_bb['upper']:
                rearm = True
        if in_trade:
            hit_sl = curr_lo <= trade_info['stop_price']
            hit_mid = curr_cl < curr_bb['middle']
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            t_exit = dt_utc.hour == 9 and dt_utc.minute >= 55 or dt_utc.hour > 9
            trade_info['mfe_max'] = max(trade_info['mfe_max'], ce_3m[i]['high'] - trade_info['entry_price'])
            trade_info['mae_max'] = max(trade_info['mae_max'], trade_info['entry_price'] - curr_lo)
            ex_reason = ex_price = None
            if hit_sl:
                ex_reason = 'STRUCTURAL_SL'
                nx = i * 3
                if nx < len(ce_1m) and ce_1m[nx]['open'] < trade_info['stop_price']:
                    ex_price = ce_1m[nx]['open']
                else:
                    ex_price = trade_info['stop_price']
            elif hit_mid:
                ex_reason, ex_price = ('MIDDLE_BB', curr_cl)
            elif t_exit:
                ex_reason, ex_price = ('TIME_EXIT', curr_cl)
            if ex_reason:
                pts = round(ex_price - trade_info['entry_price'], 2)
                risk = trade_info['initial_risk_points']
                trade_info.update({'exit_timestamp': ts_str, 'exit_price': ex_price, 'exit_reason': ex_reason, 'gross_points': pts, 'R_multiple': round(pts / risk, 2) if risk > 0 else 0.0, 'MFE_points': round(trade_info['mfe_max'], 2), 'MAE_points': round(trade_info['mae_max'], 2), 'max_R_seen': round(trade_info['mfe_max'] / risk, 2) if risk > 0 else 0.0, 'result': 'WIN' if pts > 0 else 'LOSS' if pts < 0 else 'FLAT', 'rupee_pnl': round(pts * LOT_SIZE, 2), 'holding_minutes': int((datetime.strptime(ts_str, '%H:%M:%S') - datetime.strptime(trade_info['entry_timestamp'], '%H:%M:%S')).total_seconds() // 60)})
                trades.append(trade_info)
                done_cnt += 1
                in_trade = False
                trade_info = None
            continue
        if c_bb and c_rsi and rearm and (done_cnt < 3):
            stop = round(curr_lo - TICK_SIZE, 2)
            nx = (i + 1) * 3
            fill = ce_1m[nx]['open'] if nx < len(ce_1m) else curr_cl
            e_ts = datetime.fromtimestamp(ce_1m[nx]['time'], tz=timezone.utc).strftime('%H:%M:%S') if nx < len(ce_1m) else ts_str
            risk = round(fill - stop, 2)
            if risk > 30.0:
                blocked.append({'date': date_str, 'strategy': 'S01_BB_RSI_MOMENTUM', 'signal_timestamp': ts_str, 'contract': cname, 'trigger_close': curr_cl, 'entry_fill': fill, 'stop_price': stop, 'risk_points': risk, 'reason': 'STRUCTURAL_RISK_GT_30'})
            else:
                in_trade = True
                rearm = False
                trade_info = {'date': date_str, 'strategy': 'S01_BB_RSI_MOMENTUM', 'option_type': 'CE', 'security_id': sec_id, 'contract': cname, 'strike': otm1, 'expiry': exp_date, 'signal_timestamp': ts_str, 'entry_timestamp': e_ts, 'entry_price': fill, 'entry_price_source': 'NEXT_1M_OPEN', 'trigger_close': curr_cl, 'trigger_high': ce_3m[i]['high'], 'trigger_low': curr_lo, 'ATM_at_selection': atm, 'OTM1_at_selection': otm1, 'spot_at_selection': curr_spot, 'stop_price': stop, 'initial_risk_points': risk, 'mfe_max': 0.0, 'mae_max': 0.0}
    diag = {'BB_BREAK_COUNT': bb_brk, 'RSI_CROSS_65_COUNT': rsi_x, 'BB_AND_RSI_SAME_BAR_COUNT': bb_rsi, 'PARTIAL_COUNT': partial}
    return {'trades': trades, 'blocked': blocked, 'diag': diag, 'trace': trace}