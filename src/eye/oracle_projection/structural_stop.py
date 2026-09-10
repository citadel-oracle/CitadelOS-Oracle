"""Structural Stop / Invalidation Level Builder for Eye Oracle Projection."""

from typing import Dict, Optional, Any
from src.eye.oracle_projection.contracts import EyeStructuralStop, StructuralStopStatus


class StructuralStopBuilder:
    """Derives deterministic structural invalidation stop level from Eye setup events."""

    def build_structural_stop(self, setup_event: Optional[Dict[str, Any]]) -> EyeStructuralStop:
        if not setup_event or not isinstance(setup_event, dict):
            return EyeStructuralStop(
                sl_price=None,
                sl_type="NONE",
                structural_reference="NONE",
                source_event_key=None,
                reason="No active setup geometry available",
                distance_from_entry=None,
                status=StructuralStopStatus.STRUCTURAL_SL_NOT_ESTABLISHED,
                is_confirmed=False,
            )

        sweep_extreme = setup_event.get("sweep_extreme")
        evt_key = setup_event.get("event_key")
        entry_ref = setup_event.get("entry_reference") or setup_event.get("fvg_high")

        if sweep_extreme is not None:
            sl_px = float(sweep_extreme)
            dist = round(abs(float(entry_ref) - sl_px), 2) if entry_ref else None
            return EyeStructuralStop(
                sl_price=sl_px,
                sl_type="SWEEP_EXTREME_INVALIDATION",
                structural_reference=f"Sweep extreme level {sl_px}",
                source_event_key=evt_key,
                reason="Invalidation on price breaking past recent liquidity sweep extreme",
                distance_from_entry=dist,
                status=StructuralStopStatus.ACTIVE,
                is_confirmed=True,
            )

        fvg_low = setup_event.get("fvg_low")
        if fvg_low is not None:
            sl_px = float(fvg_low)
            dist = round(abs(float(entry_ref) - sl_px), 2) if entry_ref else None
            return EyeStructuralStop(
                sl_price=sl_px,
                sl_type="FVG_FAR_EDGE_INVALIDATION",
                structural_reference=f"FVG far edge boundary {sl_px}",
                source_event_key=evt_key,
                reason="Invalidation on price closing beyond FVG far edge",
                distance_from_entry=dist,
                status=StructuralStopStatus.ACTIVE,
                is_confirmed=True,
            )

        return EyeStructuralStop(
            sl_price=None,
            sl_type="NONE",
            structural_reference="NONE",
            source_event_key=None,
            reason="No valid structural invalidation level found",
            distance_from_entry=None,
            status=StructuralStopStatus.STRUCTURAL_SL_NOT_ESTABLISHED,
            is_confirmed=False,
        )
