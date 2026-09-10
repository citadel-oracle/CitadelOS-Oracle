#!/usr/bin/env python3
"""
Reusable Proof Tool for Canonical Feature Engine Phase 3:
Cadence & Persistence Hardening Validation.
Replays 512 real NIFTY 5m market bars, verifies completed/forming bar contracts,
proves idempotency & restart persistence without double-finalization, and calculates
exact per-feature and aggregate parity accounting.
"""

from __future__ import annotations
import json
import os
import sys
import time
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.canonical_features.engine import CanonicalFeatureEngine
from src.canonical_features.formula_registry import FormulaProfileRegistry
from src.canonical_features.service import CanonicalFeatureService


def run_phase3_validation() -> dict[str, Any]:
    print("==================================================")
    print("CANONICAL SHADOW CADENCE & PERSISTENCE VALIDATION")
    print("==================================================")

    # 1. Real Data Inventory
    candles_path = "logs/kronos_alpha_candles.json"
    real_candles: list[dict[str, Any]] = []

    if os.path.exists(candles_path):
        with open(candles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        real_candles = data.get("candles", [])

    if not real_candles:
        print("ERROR: Persisted real session data unavailable in logs/kronos_alpha_candles.json!")
        return {"verdict": "REAL_DATA_INSUFFICIENT"}

    print(f"Loaded {len(real_candles)} real NIFTY 5m bars ({real_candles[0]['timestamp']} to {real_candles[-1]['timestamp']})")

    # 2. Bar-Cadence & Finalization Proof
    engine = CanonicalFeatureEngine(instrument="NIFTY", timeframe="5m", max_history=500)

    # Bootstrap initial 50 bars
    engine.bootstrap(real_candles[:50])

    def get_comp_keys(eng: CanonicalFeatureEngine) -> int:
        return sum(1 for k in eng._processed_keys if str(k).endswith(":True"))

    finalization_count = get_comp_keys(engine)
    initial_finalizations = finalization_count

    # Replay remaining 462 bars with forming ticks in between
    for idx, c in enumerate(real_candles[50:], start=50):
        # 1. Forming tick update
        forming_tick = {
            "timestamp": c.get("timestamp"),
            "open": c.get("open"),
            "high": float(c.get("high")) + 1.0,
            "low": float(c.get("low")) - 1.0,
            "close": c.get("close"),
            "volume": float(c.get("volume") or 0.0) / 2.0,
        }
        forming_snap = engine.update_bar(forming_tick, is_complete=False)
        assert forming_snap.bar_complete is False, "Forming tick must set bar_complete=False"

        # 2. Completed bar finalization
        comp_snap = engine.update_bar(c, is_complete=True)
        assert comp_snap.bar_complete is True, "Completed bar must set bar_complete=True"

    finalization_count = get_comp_keys(engine)
    unique_finalizations = finalization_count - initial_finalizations
    assert unique_finalizations == len(real_candles) - 50, f"Expected 462 unique finalizations, got {unique_finalizations}"

    # Verify duplicate finalization attempt is idempotent
    snap_dup = engine.update_bar(real_candles[-1], is_complete=True)
    assert get_comp_keys(engine) == finalization_count, "Duplicate finalization must be idempotent"

    print(f"Cadence Proof: {unique_finalizations} unique completed bar finalizations. 0 duplicate finalizations.")

    # 3. Restart Persistence Proof (no double-finalization on restart)
    state_file = "logs/test_cadence_persistence.json"
    if os.path.exists(state_file):
        os.remove(state_file)

    service1 = CanonicalFeatureService(persistence_path=state_file, enabled=True)
    for c in real_candles[:50]:
        service1.publish_candle(c, is_complete=True)

    c_count1 = service1.checkpoint_count
    assert c_count1 == 50, f"Expected 50 checkpoints on 50 completed bars, got {c_count1}"
    snap_before = service1.get_latest_snapshot()

    # Re-instantiate from persisted file
    service2 = CanonicalFeatureService(persistence_path=state_file, enabled=True)
    snap_after = service2.get_latest_snapshot()

    assert snap_after is not None
    assert snap_after.feature_snapshot_id == snap_before.feature_snapshot_id
    assert len(service2.engine._processed_keys) == len(service1.engine._processed_keys)

    # Re-publish last bar to verify no double finalization
    snap_repub = service2.publish_candle(real_candles[49], is_complete=True)
    assert len(service2.engine._processed_keys) == len(service1.engine._processed_keys)

    if os.path.exists(state_file):
        os.remove(state_file)
    if os.path.exists(state_file + ".tmp"):
        os.remove(state_file + ".tmp")

    print("Restart Proof: State cleanly restored from persistence. 0 duplicate finalizations on restart.")

    # 4. Correct Aggregate Parity Accounting
    engine_parity = CanonicalFeatureEngine(instrument="NIFTY", timeframe="5m", max_history=500)
    engine_parity.bootstrap(real_candles[:50])

    features_to_check = [
        ("OSE", "ema_50", "EMA_OSE_V1", 50),
        ("VOB", "atr_value", "ATR_OSE_V1", 14),
        ("OSE", "supertrend", "SUPERTREND_OSE_V1", 10),
        ("Edge Lab", "vwap_value", "VWAP_CUMULATIVE_V1", 1),
    ]

    total_comparisons = 0
    exact_comparisons = 0
    tolerance_comparisons = 0
    mismatches = 0
    max_drift = 0.0

    per_feature_totals: dict[str, dict[str, int]] = {}

    for idx, c in enumerate(real_candles[50:], start=50):
        snap = engine_parity.update_bar(c, is_complete=True)
        all_sub_candles = real_candles[: idx + 1]

        # For session VWAP, filter candles to current trading date
        curr_date = str(c.get("timestamp") or "")[:10]
        session_candles = [sc for sc in all_sub_candles if str(sc.get("timestamp") or "").startswith(curr_date)]

        bounded_sub_candles = all_sub_candles[-500:]

        for consumer, feat_key, profile_id, period in features_to_check:
            feat_name = f"{consumer}:{feat_key}"
            if feat_name not in per_feature_totals:
                per_feature_totals[feat_name] = {"total": 0, "exact": 0, "tolerance": 0, "mismatch": 0}

            leg_val = FormulaProfileRegistry.compute_profile(profile_id, bounded_sub_candles, period=period)
            if isinstance(leg_val, tuple):
                leg_val = leg_val[0]

            if feat_key == "ema_50":
                can_val = snap.ema_values.get("ema_50")
            elif feat_key == "atr_value":
                can_val = snap.atr_value
            elif feat_key == "supertrend":
                can_val = snap.supertrend.value
            elif feat_key == "vwap_value":
                can_val = snap.vwap_value
            else:
                can_val = None

            if leg_val is not None and can_val is not None:
                total_comparisons += 1
                per_feature_totals[feat_name]["total"] += 1

                drift = abs(float(can_val) - float(leg_val))
                if drift > max_drift:
                    max_drift = drift

                if drift == 0.0:
                    exact_comparisons += 1
                    per_feature_totals[feat_name]["exact"] += 1
                elif drift <= 0.02:
                    tolerance_comparisons += 1
                    per_feature_totals[feat_name]["tolerance"] += 1
                else:
                    mismatches += 1
                    per_feature_totals[feat_name]["mismatch"] += 1

    print("\n--- AGGREGATE PARITY ACCOUNTING ---")
    print(f"Total Feature Comparisons: {total_comparisons}")
    print(f"Exact Comparisons: {exact_comparisons}")
    print(f"Tolerance Comparisons: {tolerance_comparisons}")
    print(f"Mismatches: {mismatches}")
    print(f"Max Absolute Drift: {max_drift:.6f}")
    print("Per-Feature Breakdown:")
    for fn, counts in per_feature_totals.items():
        print(f"  - {fn}: Total={counts['total']}, Exact={counts['exact']}, Tolerance={counts['tolerance']}, Mismatch={counts['mismatch']}")

    verdict = "CANONICAL_SHADOW_OFFLINE_HARDENING_PASS" if mismatches == 0 else "FORMULA_PARITY_FAILED"

    print("\n==================================================")
    print(f"Final Verdict: {verdict}")
    print("==================================================")

    return {
        "verdict": verdict,
        "total_comparisons": total_comparisons,
        "exact_comparisons": exact_comparisons,
        "tolerance_comparisons": tolerance_comparisons,
        "mismatches": mismatches,
        "max_drift": round(max_drift, 6),
        "per_feature_totals": per_feature_totals,
        "unique_finalizations": unique_finalizations,
    }


if __name__ == "__main__":
    res = run_phase3_validation()
    if res["verdict"] != "CANONICAL_SHADOW_OFFLINE_HARDENING_PASS":
        sys.exit(1)
    sys.exit(0)
