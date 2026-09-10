import json
from scripts.run_e8d_month_replay import load_candles, aggregate_1m_candles
from datetime import datetime, timezone

def get_opt(fp):
    with open(fp) as f:
        candles = load_candles(json.load(f))
    opt_3m = aggregate_1m_candles(candles, 3)
    return [b["close"] for b in opt_3m[:10]]

print("E8C:", get_opt("reports/personal_strategy_replay/e8c_r1_20260803_20260807/raw/rolling_call_ATMplus1_1m_20260803.json"))
print("E8D:", get_opt("reports/personal_strategy_replay/e8d_20260706_20260807/raw/rolling_call_ATMplus1_1m_20260803.json"))
