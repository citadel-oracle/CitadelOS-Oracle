import json
from pathlib import Path
from src.eye.kernel.runtime import EyeRuntime
from src.eye.kernel.adapters.replay import FrozenReplayAdapter
from scripts.run_e8d_month_replay import load_candles, aggregate_1m_candles, get_nifty_weekly_expiry, resolve_sec_id

def test_kernel_on_07aug():
    RAW_DIR = Path("reports/personal_strategy_replay/e8d_r1_20260706_20260807/raw")
    date_str = "2026-08-07"
    
    with open(RAW_DIR / "dhan_instrument_master.json") as f:
        master_rows = json.load(f)["rows"]
        
    with open(RAW_DIR / f"spot_1m_{date_str.replace('-', '')}.json") as f:
        spot_candles = load_candles(json.load(f))
        
    exp_date = get_nifty_weekly_expiry(date_str)
    
    runtime = EyeRuntime()
    runtime.start()
    adapter = FrozenReplayAdapter(runtime.get_kernel())
    
    # In a full replay, we push spot and option bars in time order.
    # We will simulate pushing all 1m bars in order.
    
    # We need to find the OTM1 CE contract
    # First, let's just aggregate spot to 3m to find the initial ATM
    spot_3m = aggregate_1m_candles(spot_candles, 3)
    if not spot_3m:
        return
        
    # Just a quick integration test to ensure no crashes
    adapter.inject_bars("NIFTY_SPOT", spot_candles)
    runtime.get_kernel().process_cycle()
    print("Kernel processed successfully.")

if __name__ == "__main__":
    test_kernel_on_07aug()
