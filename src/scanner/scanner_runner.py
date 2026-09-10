import os
import time
from datetime import datetime

from src.scanner.market_scanner import MarketScanner


scanner = MarketScanner()


while True:
    os.system("clear")

    print("=" * 170)
    print("                                      CITADEL TERMINAL V5 — KRONOS X + STRUCTURE + PULLBACK")
    print("=" * 170)
    print(datetime.now().strftime("%d %b %Y   %H:%M:%S"))
    print()

    rows = scanner.scan()

    print(
        f"{'SYMBOL':<13}"
        f"{'LTP':<10}"
        f"{'DIR':<5}"
        f"{'REGIME':<10}"
        f"{'BIAS':<9}"
        f"{'BULL':<7}"
        f"{'BEAR':<7}"
        f"{'CONF':<7}"
        f"{'TRADE':<7}"
        f"{'STRUCT':<10}"
        f"{'BOS':<13}"
        f"{'PB':<7}"
        f"{'ENTRY':<10}"
        f"{'SL':<10}"
        f"{'TARGET':<10}"
    )

    print("-" * 170)

    for row in rows:
        print(
            f"{row['symbol']:<13}"
            f"{row['ltp']:<10}"
            f"{row['direction']:<5}"
            f"{row['regime']:<10}"
            f"{row['bias']:<9}"
            f"{str(row['bull']) + '%':<7}"
            f"{str(row['bear']) + '%':<7}"
            f"{str(row['confidence']) + '%':<7}"
            f"{row['trade']:<7}"
            f"{row['structure']:<10}"
            f"{row['bos']:<13}"
            f"{row['pullback_signal']:<7}"
            f"{str(row['entry']):<10}"
            f"{str(row['sl']):<10}"
            f"{str(row['target']):<10}"
        )

    print("-" * 170)
    print()
    print("Refreshing every 5 seconds... Press CTRL+C to stop.")

    time.sleep(5)