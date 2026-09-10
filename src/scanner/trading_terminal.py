import os
import time
from datetime import datetime

from src.scanner.market_scanner import MarketScanner
from src.execution.paper_execution import PaperExecution
from src.session.session_manager import SessionManager


scanner = MarketScanner()
execution = PaperExecution()
session = SessionManager()


while True:
    os.system("clear")

    print("=" * 180)
    print("                         CITADEL TRADING TERMINAL V4 — PHASE 2")
    print("=" * 180)
    print(datetime.now().strftime("%d %b %Y   %H:%M:%S"))
    print()

    rows = scanner.scan()
    strategy_config = scanner.strategy_manager.strategy_config()

    if session.should_square_off(strategy_config) and execution.has_active_trade():
        execution.close_active_trade("MARKET CLOSE")

    print(
        f"{'SYMBOL':<12}"
        f"{'LTP':<10}"
        f"{'REGIME':<10}"
        f"{'BIAS':<9}"
        f"{'CONF':<7}"
        f"{'TRADE':<7}"
        f"{'MTF':<9}"
        f"{'BOS':<13}"
        f"{'CHOCH':<13}"
        f"{'LIQ':<16}"
        f"{'FVG':<14}"
        f"{'OB':<13}"
        f"{'PB':<7}"
        f"{'ENTRY':<10}"
        f"{'SL':<10}"
        f"{'TARGET':<10}"
    )

    print("-" * 180)

    for row in rows:
        print(
            f"{row['symbol']:<12}"
            f"{row['ltp']:<10}"
            f"{row['regime']:<10}"
            f"{row['bias']:<9}"
            f"{str(row['confidence']) + '%':<7}"
            f"{row['trade']:<7}"
            f"{row['mtf_bias']:<9}"
            f"{row['bos']:<13}"
            f"{row['choch']:<13}"
            f"{row['liquidity']:<16}"
            f"{row['fvg']:<14}"
            f"{row['order_block']:<13}"
            f"{row['pullback_signal']:<7}"
            f"{str(row['entry']):<10}"
            f"{str(row['sl']):<10}"
            f"{str(row['target']):<10}"
        )

        signal = {
            "signal": row["pullback_signal"],
            "reason": row["reason"],
            "confidence": row["confidence"],
            "entry": row["entry"],
            "sl": row["sl"],
            "target": row["target"],
        }

        if row["pullback_signal"] in ["BUY", "SELL"] and session.entry_allowed(strategy_config):
            execution.process_signal(
                signal,
                symbol=row["symbol"],
                context=row.get("context"),
            )

    active_trade = execution.get_active_trade()

    print("-" * 180)
    print()
    print("📌 ACTIVE PAPER TRADE")

    if active_trade:
        symbol = active_trade["symbol"]
        live_ltp = None

        for row in rows:
            if row["symbol"] == symbol:
                live_ltp = row["ltp"]
                break

        if live_ltp is not None:
            update = execution.update_trade(live_ltp)
            trade = update.get("trade") or active_trade
        else:
            trade = active_trade

        print(f"Trade ID : {trade.get('trade_id')}")
        print(f"Symbol   : {trade.get('symbol')}")
        print(f"Side     : {trade.get('side')}")
        print(f"Entry    : {trade.get('entry')}")
        print(f"LTP      : {trade.get('ltp')}")
        print(f"SL       : {trade.get('sl')}")
        print(f"Target   : {trade.get('target')}")
        print(f"PnL      : {trade.get('pnl_points')}")
        print(f"R        : {trade.get('r_multiple')}")
        print(f"Status   : {trade.get('status')}")
        print(f"Exit     : {trade.get('exit_reason')}")
    else:
        print("No active trade")

    print()
    print("=" * 180)
    print("📊 SESSION STATUS")
    print("=" * 180)

    status = session.status(strategy_config)

    print(f"Market Open   : {status.get('market_open')}")
    print(f"Entry Allowed : {status.get('entry_allowed')}")
    print(f"Square Off    : {status.get('square_off')}")
    print(f"Strategy      : {scanner.strategy_manager.strategy_name()}")
    print(f"Mode          : {strategy_config.get('mode')}")
    print(f"Overnight     : {strategy_config.get('allow_overnight')}")

    print()
    print("=" * 180)
    print("📊 PAPER JOURNAL SUMMARY")
    print("=" * 180)

    summary = execution.journal_summary()

    print(f"Closed Trades : {summary.get('total_closed')}")
    print(f"Wins          : {summary.get('wins')}")
    print(f"Losses        : {summary.get('losses')}")
    print(f"Net Points    : {summary.get('net_points')}")

    print()
    print("🧾 RECENT TRADE EVENTS")
    print("-" * 180)

    recent = execution.recent_trades(5)

    if not recent:
        print("No journal entries yet")
    else:
        print(
            f"{'TIME':<20}"
            f"{'EVENT':<8}"
            f"{'ID':<14}"
            f"{'SYMBOL':<12}"
            f"{'SIDE':<7}"
            f"{'ENTRY':<10}"
            f"{'LTP':<10}"
            f"{'PNL':<10}"
            f"{'STATUS':<10}"
            f"{'EXIT'}"
        )

        for r in recent:
            print(
                f"{r.get('time'):<20}"
                f"{r.get('event'):<8}"
                f"{str(r.get('trade_id')):<14}"
                f"{r.get('symbol'):<12}"
                f"{r.get('side'):<7}"
                f"{r.get('entry'):<10}"
                f"{r.get('ltp'):<10}"
                f"{r.get('pnl_points'):<10}"
                f"{r.get('status'):<10}"
                f"{r.get('exit_reason')}"
            )

    print("-" * 180)
    print()
    print("Refreshing every 5 seconds... Press CTRL+C to stop.")

    time.sleep(5)