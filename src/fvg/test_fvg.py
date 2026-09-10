import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.getenv("CITADEL_ENV_FILE", "/Users/ayushmudgal/Developer/CitadelOS/.env"), override=True)

from src.broker.dhan_client import DhanClient
from src.fvg.fvg_engine import FVGEngine


dhan = DhanClient()
engine = FVGEngine()

res = dhan.get_intraday_candles(
    segment="IDX_I",
    security_id="13",
    instrument="INDEX",
    interval="1",
)

candles = res.get("candles", [])

result = engine.analyze(candles)

print("========== FVG TEST ==========")
print(result)