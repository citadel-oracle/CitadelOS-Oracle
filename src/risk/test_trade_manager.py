from src.risk.trade_manager import TradeManager, print_trade_state


manager = TradeManager()

signal = {
    "signal": "BUY",
    "reason": "Test BUY trade",
    "confidence": 85,
    "entry": 100,
    "sl": 90,
    "target": 120,
}

print("\n========== OPEN TRADE ==========")

opened = manager.open_trade(signal, symbol="NIFTY")
print(opened)

print("\n========== TRADE UPDATES ==========")

test_prices = [100, 105, 110, 115, 118, 121]

for price in test_prices:
    result = manager.update(price)
    print_trade_state(result)

print("\n========== SELL TRADE TEST ==========")

sell_signal = {
    "signal": "SELL",
    "reason": "Test SELL trade",
    "confidence": 82,
    "entry": 200,
    "sl": 210,
    "target": 180,
}

opened = manager.open_trade(sell_signal, symbol="BANKNIFTY")
print(opened)

sell_test_prices = [200, 195, 190, 185, 179]

for price in sell_test_prices:
    result = manager.update(price)
    print_trade_state(result)