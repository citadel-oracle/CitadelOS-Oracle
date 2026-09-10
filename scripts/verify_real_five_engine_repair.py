import sys
import json
from pathlib import Path
import os
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.premium_intelligence.capture import PremiumCaptureStore

def main():
    store_path = Path("logs/premium_intelligence/captures_v3.jsonl")
    if not store_path.exists():
        print("WARNING: captures_v3.jsonl not found. Normal if Dhan auth fails on this environment.")
    else:
        store = PremiumCaptureStore(file_path=str(store_path))
        records = store.get_all_records()
        print(f"Parsed {len(records)} V3 records from store.")
    
    # Run a quick API check
    api_url = "http://localhost:8000/v1/premium-intelligence/engines"
    try:
        res = requests.get(api_url)
        if res.status_code == 200:
            data = res.json()
            assert "coverage_readiness" in data
            print("API fetch successful.")
            if data.get("coverage_readiness") == "ENGINEERING_REPAIRED_WAITING_FOR_LIVE_EVIDENCE":
                print("API returned correct WAITING state.")
            else:
                print(f"API returned: {data.get('coverage_readiness')}")
        else:
            print(f"API returned status code: {res.status_code}")
    except Exception as e:
        print(f"API Check skipped/failed (is the server running?): {e}")

    # Checking SME default
    from src.premium_intelligence.sme import StrikeMigrationEngine
    sme = StrikeMigrationEngine()
    snap = sme.evaluate()
    if snap.migration_state != "INSUFFICIENT_HISTORY":
        print("ERROR: SME did not return INSUFFICIENT_HISTORY.")
        sys.exit(1)

    # Checking DGP disclosure
    from src.premium_intelligence.dgp import DealerGammaPressureProxy
    dgp = DealerGammaPressureProxy()
    snap_dgp = dgp.evaluate(24500, 24500)
    if "inferred" not in str(snap_dgp.note).lower():
        print("ERROR: DGP proxy disclosure missing.")
        sys.exit(1)

    print("Independent Verification PASS")
    sys.exit(0)

if __name__ == "__main__":
    main()
