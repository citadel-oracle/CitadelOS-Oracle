import json, datetime
from scripts.run_e8d_month_replay import load_candles, aggregate_1m_candles

def get_spot(fp):
    with open(fp) as f:
        candles = load_candles(json.load(f))
    spot_3m = aggregate_1m_candles(candles, 3)
    return [b["close"] for b in spot_3m[:10]]

print("E8C:", get_spot("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw/spot_1m_20260806.json"))
print("E8D:", get_spot("reports/personal_strategy_replay/e8d_20260706_20260807/raw/spot_1m_20260806.json"))
