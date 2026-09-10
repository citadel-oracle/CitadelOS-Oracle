from src.execution.trade_journal import TradeJournal


journal = TradeJournal("logs/test_paper_trades.csv")

trade = {
    "trade_id": 1,
    "symbol": "NIFTY",
    "side": "BUY",
    "entry": 100,
    "ltp": 121,
    "sl": 107.5,
    "target": 120,
    "pnl_points": 21,
    "r_multiple": 2.1,
    "status": "CLOSED",
    "exit_reason": "TARGET HIT",
    "confidence": 99,
    "reason": "FORCE TEST",
}

journal.log_trade("OPEN", trade)
journal.log_trade("CLOSE", trade)

print("Last rows:")
print(journal.read_last(5))

print("Summary:")
print(journal.summary())