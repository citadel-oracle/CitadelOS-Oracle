"""Entry Geometry Builder for Eye Oracle Projection."""

from typing import Dict, Optional, Any
from src.eye.oracle_projection.contracts import EyeEntryGeometry, EntryGeometryStatus


class EntryGeometryBuilder:
    """Derives deterministic structural entry band from Eye setup events."""

    def build_entry_geometry(self, setup_event: Optional[Dict[str, Any]]) -> EyeEntryGeometry:
        if not setup_event or not isinstance(setup_event, dict):
            return EyeEntryGeometry(
                entry_low=None,
                entry_high=None,
                entry_reference=None,
                entry_geometry_type="NONE",
                entry_status=EntryGeometryStatus.ENTRY_BAND_NOT_ESTABLISHED,
                source_event_keys=[],
                is_confirmed=False,
            )

        family = setup_event.get("family", "")
        evt_key = setup_event.get("event_key", "EVT:UNKNOWN")

        if family in ("DISPLACEMENT_FVG_RETEST", "ZONE_FVG_CONFLUENCE", "BREAKAWAY_FVG_CONTINUATION"):
            fvg_low = setup_event.get("fvg_low")
            fvg_high = setup_event.get("fvg_high")
            if fvg_low is not None and fvg_high is not None:
                low = min(float(fvg_low), float(fvg_high))
                high = max(float(fvg_low), float(fvg_high))
                ref = round((low + high) / 2.0, 2)
                return EyeEntryGeometry(
                    entry_low=low,
                    entry_high=high,
                    entry_reference=ref,
                    entry_geometry_type="FVG_RETEST_BAND",
                    entry_status=EntryGeometryStatus.ACTIVE,
                    source_event_keys=[evt_key],
                    is_confirmed=True,
                )

        reclaim_px = setup_event.get("reclaim_price") or setup_event.get("reclaimed_level") or setup_event.get("entry_reference")
        if reclaim_px is not None:
            px = float(reclaim_px)
            return EyeEntryGeometry(
                entry_low=round(px - 5.0, 2),
                entry_high=round(px + 5.0, 2),
                entry_reference=px,
                entry_geometry_type="STRUCTURAL_ENTRY_BAND",
                entry_status=EntryGeometryStatus.ACTIVE,
                source_event_keys=[evt_key],
                is_confirmed=True,
            )

        return EyeEntryGeometry(
            entry_low=None,
            entry_high=None,
            entry_reference=None,
            entry_geometry_type="NONE",
            entry_status=EntryGeometryStatus.ENTRY_BAND_NOT_ESTABLISHED,
            source_event_keys=[],
            is_confirmed=False,
        )
