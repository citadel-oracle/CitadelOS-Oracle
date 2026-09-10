import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.getenv("CITADEL_ENV_FILE", "/Users/ayushmudgal/Developer/CitadelOS/.env"), override=True)

import time
from datetime import datetime

from dhan_client import DhanClient
from candle_builder import CandleBuilder
from signal_engine import SignalEngine, print_signal
from kronos_engine import KronosEngine, print_kronos
from risk_engine import RiskEngine, print_risk
from paper_trader import PaperTrader, print_paper_order


def calculate_indicators(candles):
    closes = [
        float(c.get("close", c.get("ltp", 0)))
        for c in candles
        if float(c.get("close", c.get("ltp", 0))) > 0
    ]

    if len(closes) < 40:
        return {
            "ema_21": None,
            "ema_38": None,
            "rsi_14": None,
            "vwap": None,
            "close": closes[-1] if closes else None,
        }

    def ema(values, length):
        k = 2 / (length + 1)
        e = values[0]
        for price in values[1:]:
            e = price * k + e * (1 - k)
        return round(e, 2)

    def rsi(values, length=14):
        gains = []
        losses = []

        for i in range(1, len(values)):
            change = values[i] - values[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        avg_gain = sum(gains[-length:]) / length
        avg_loss = sum(losses[-length:]) / length

        if avg_loss == 0 and avg_gain == 0:
            return 50

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    return {
        "ema_21": ema(closes[-80:], 21),
        "ema_38": ema(closes[-120:], 38),
        "rsi_14": rsi(closes, 14),
        "vwap": closes[-1],
        "close": closes[-1],
    }


def get_candles_safe(candle_builder):
    if hasattr(candle_builder, "get_candles"):
        return candle_builder.get_candles()

    if hasattr(candle_builder, "candles"):
        return candle_builder.candles

    return []


def start():
    dhan = DhanClient()
    candle_builder = CandleBuilder()
    signal_engine = SignalEngine()
    kronos_engine = KronosEngine()
    risk_engine = RiskEngine()
    paper_trader = PaperTrader()

    if hasattr(candle_builder, "load_csv"):
        try:
            candle_builder.load_csv("logs/live_candles.csv")
        except Exception:
            pass

    candles = get_candles_safe(candle_builder)

    print("CitadelOS Live Candle Feed Started ✅")
    print(f"Preloaded candles: {len(candles)} ✅")

    while True:
        try:
            ltp_data = dhan.get_ltp()
            ltp = float(ltp_data.get("ltp", 0))
            updated = ltp_data.get("updated", "NA")

            print(f"\nLive ✅ | Dhan Connected | NIFTY LTP: {ltp} | Updated: {updated}")

            candle = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "ltp": ltp,
            }

            if hasattr(candle_builder, "update"):
                candle_builder.update(candle)

            candles = get_candles_safe(candle_builder)

            if hasattr(candle_builder, "save_csv"):
                candle_builder.save_csv("logs/live_candles.csv")

            indicators = calculate_indicators(candles)

            print("\n📊 Indicators")
            print(f"EMA21 : {indicators.get('ema_21')}")
            print(f"EMA38 : {indicators.get('ema_38')}")
            print(f"RSI14 : {indicators.get('rsi_14')}")
            print(f"VWAP  : {indicators.get('vwap')}")
            print(f"Close : {indicators.get('close')}")

            signal = signal_engine.generate(indicators, candle)
            print_signal(signal)

            kronos = kronos_engine.analyze(indicators, candle)
            print_kronos(kronos)

            risk = risk_engine.validate(signal, kronos)
            print_risk(risk)

            if risk.get("approved") is True:
                order = paper_trader.execute(signal, ltp)
            else:
                order = paper_trader.monitor(ltp)

            print_paper_order(order)

            time.sleep(2)

        except KeyboardInterrupt:
            print("\nCitadelOS stopped manually.")
            break

        except Exception as e:
            print(f"Live Feed ❌ | Error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    start()