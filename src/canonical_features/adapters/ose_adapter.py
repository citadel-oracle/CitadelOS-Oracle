"""
OSE Read-Only Shadow Adapter for Canonical Features.
Compares OSE legacy indicators against CanonicalFeatureEngine snapshots.
"""

from __future__ import annotations
from typing import Any, Mapping, Optional

from src.canonical_features.models import CanonicalFeatureSnapshot


class OseShadowAdapter:
    def __init__(self, tolerance: float = 0.02):
        self.tolerance = tolerance

    def evaluate_shadow_parity(
        self,
        legacy_output: Mapping[str, Any],
        canonical_snapshot: CanonicalFeatureSnapshot,
        feature_name: str = "ema_21",
    ) -> dict[str, Any]:
        legacy_val: Optional[float] = legacy_output.get(feature_name)
        canonical_val: Optional[float] = None

        if feature_name in canonical_snapshot.ema_values:
            canonical_val = canonical_snapshot.ema_values[feature_name]
        elif feature_name == "atr":
            canonical_val = canonical_snapshot.atr_value
        elif feature_name == "vwap":
            canonical_val = canonical_snapshot.vwap_value
        elif feature_name == "supertrend":
            canonical_val = canonical_snapshot.supertrend.value

        if legacy_val is None or canonical_val is None:
            parity_status = "WARMUP_MISSING"
            drift = None
        else:
            drift = round(abs(float(canonical_val) - float(legacy_val)), 6)
            parity_status = "MATCH" if drift <= self.tolerance else "DRIFT"

        return {
            "consumer": "OSE",
            "feature": feature_name,
            "legacy_value": legacy_val,
            "canonical_value": canonical_val,
            "parity_status": parity_status,
            "drift": drift,
            "snapshot_id": canonical_snapshot.feature_snapshot_id,
            "execution_influence": "ZERO",
        }
