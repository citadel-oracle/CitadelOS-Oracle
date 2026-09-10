import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.getenv("CITADEL_ENV_FILE", "/Users/ayushmudgal/Developer/CitadelOS/.env"), override=True)

from src.broker.dhan_client import DhanClient
from src.timeframe.timeframe_engine import TimeframeEngine


dhan = DhanClient()
engine = TimeframeEngine()

res = dhan.get_intraday_candles(
    segment="IDX_I",
    security_id="13",
    instrument="INDEX",
    interval="1",
)

candles = res.get("candles", [])

result = engine.analyze(candles)

print("========== MULTI TIMEFRAME TEST ==========")
print("Bias          :", result["bias"])
print("Mode          :", result["mode"])
print("Allow Trade   :", result["allow_trade"])
print("Confidence    :", result["confidence"])
print("Bull Votes    :", result["bullish_votes"])
print("Bear Votes    :", result["bearish_votes"])
print("Reason        :", result["reason"])

print()
print("1m candles    :", len(result["timeframes"]["1m"]["candles"]))
print("5m candles    :", len(result["timeframes"]["5m"]["candles"]))
print("15m candles   :", len(result["timeframes"]["15m"]["candles"]))

print()
print("15m Kronos    :", result["timeframes"]["15m"]["kronos"])
print("5m Kronos     :", result["timeframes"]["5m"]["kronos"])
print("1m Kronos     :", result["timeframes"]["1m"]["kronos"])