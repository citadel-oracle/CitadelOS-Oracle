"""
VOB Read-Only Shadow Adapter for Canonical Features.
Compares VOB legacy ATR/pivots against CanonicalFeatureEngine snapshots.
"""

from __future__ import annotations
from typing import Any, Mapping, Optional

from src.canonical_features.models import CanonicalFeatureSnapshot


class VobShadowAdapter:
    def __init__(self, tolerance: float = 1e-4):
        self.tolerance = tolerance

    def evaluate_shadow_parity(
        self,
        legacy_output: Mapping[str, Any],
        canonical_snapshot: CanonicalFeatureSnapshot,
        feature_name: str = "atr",
    ) -> dict[str, Any]:
        legacy_val: Optional[float] = legacy_output.get(feature_name)
        canonical_val: Optional[float] = (
            canonical_snapshot.atr_value if feature_name in ("atr", "atr_value") else None
        )

        if legacy_val is None or canonical_val is None:
            parity_status = "WARMUP_MISSING"
            drift = None
        else:
            drift = round(abs(canonical_val - legacy_val), 6)
            parity_status = "MATCH" if drift <= self.tolerance else "DRIFT"

        return {
            "consumer": "VOB",
            "feature": feature_name,
            "legacy_value": legacy_val,
            "canonical_value": canonical_val,
            "parity_status": parity_status,
            "drift": drift,
            "snapshot_id": canonical_snapshot.feature_snapshot_id,
            "execution_influence": "ZERO",
        }
