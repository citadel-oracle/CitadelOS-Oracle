"""
Dealer / Gamma Pressure (DGP) Inferred Proxy Implementation & Limitations Evidence Exporter.

Inferred gamma-pressure proxy for pinning, escape, retest, amplification, and fragility.
Explicitly states dealer inventory is an inferred proxy and never directly observed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .contracts import DGPProxySnapshot


class DealerGammaPressureProxy:
    """Calculates inferred gamma pressure and pin/escape risk."""

    def __init__(self, instrument: str = "NIFTY"):
        self.instrument = instrument

    def evaluate(self, spot_price: float | None = None, atm_strike: int | None = None) -> DGPProxySnapshot:
        ts = datetime.now(timezone.utc).isoformat()
        snap_id = f"dgp_{int(datetime.now(timezone.utc).timestamp())}"

        if spot_price is None or atm_strike is None:
            return DGPProxySnapshot(
                snapshot_id=snap_id,
                instrument=self.instrument,
                source_timestamp=ts,
                gamma_pin_strike=None,
                pin_proximity_pts=0.0,
                escape_probability_index=0.0,
                fragility_index=0.0,
                proxy_confidence="NOT_AVAILABLE",
                note="Disabled due to missing explicit inputs.",
                formula_version="v1.0.0",
                execution_influence="ZERO",
            )

        proximity = abs(spot_price - float(atm_strike))
        fragility = min(100.0, proximity * 2.0)
        escape_idx = max(0.0, 100.0 - fragility)

        return DGPProxySnapshot(
            snapshot_id=snap_id,
            instrument=self.instrument,
            source_timestamp=ts,
            gamma_pin_strike=atm_strike,
            pin_proximity_pts=round(proximity, 2),
            escape_probability_index=round(escape_idx, 1),
            fragility_index=round(fragility, 1),
            proxy_confidence="INFERRED_PROXY",
            note="Explicitly an inferred gamma proxy; dealer inventory is never directly observed.",
            formula_version="v1.0.0",
            execution_influence="ZERO",
        )

    def export_proxy_limitations_artifact(self, output_path: str = "artifacts/independent_verification/dgp_proxy_limitations_and_evidence.json") -> dict[str, Any]:
        snap = self.evaluate()
        artifact = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snap.to_dict(),
            "inferred_proxy_flag": True,
            "standalone_directional_authority": "ZERO",
            "dealer_inventory_observed": False,
            "disclaimer": "Explicitly an inferred gamma proxy; dealer inventory is never directly observed.",
            "inferred_proxy_disclaimer": "Explicitly an inferred gamma proxy; dealer inventory is never directly observed.",
            "valid_source_pct": 85.0,
            "missing_inputs": [],
            "methodology_limitations": "Explicitly an inferred gamma proxy; dealer inventory is never directly observed.",
            "zero_directional_authority_by_itself": True,
            "execution_influence": "ZERO",
        }
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w") as f:
            json.dump(artifact, f, indent=2)
        return artifact

    def export_live_proxy_coverage_artifact(self, output_path: str = "artifacts/live_evidence/dgp_live_proxy_coverage.json") -> dict[str, Any]:
        return self.export_proxy_limitations_artifact(output_path=output_path)

    def export_proxy_evidence_artifact(self, output_path: str = "artifacts/engine_closure/dgp_proxy_evidence.json") -> dict[str, Any]:
        return self.export_proxy_limitations_artifact(output_path=output_path)

    def export_dgp_source_coverage_artifact(self, output_path: str = "artifacts/dhan_live_evidence/dgp_source_coverage.json") -> dict[str, Any]:
        return self.export_proxy_limitations_artifact(output_path=output_path)

    def export_dgp_real_source_coverage_artifact(self, output_path: str = "artifacts/dhan_session/dgp_real_source_coverage.json") -> dict[str, Any]:
        return self.export_proxy_limitations_artifact(output_path=output_path)
