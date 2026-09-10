"""
PLI — Premium Lead Index Engine

Classifies directional option lead:
  - CALL_LEAD
  - PUT_LEAD
  - MIXED
  - TWO_SIDED_EXPANSION
  - TWO_SIDED_COMPRESSION
  - NO_DATA
  - STALE

Hard Rules:
  - Raw volume or OI is NOT smart-money direction.
  - Do NOT infer dealer positioning from public OI.
  - Rising straddle alone is NOT directional.
  - Do NOT substitute unavailable Greeks.
  - Record all inputs & blockers in WHY evidence.
"""

from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional
from src.premium_intelligence.contracts import PremiumLeadSnapshot
from src.premium_intelligence.straddle import StraddleCalculationResult


class PremiumLeadEngine:
    def __init__(self, lead_differential_min: float = 15.0):
        self.lead_differential_min = lead_differential_min
        self._prev_ce_ltp: Optional[float] = None
        self._prev_pe_ltp: Optional[float] = None

    def evaluate_lead(
        self,
        straddle_res: StraddleCalculationResult,
        ce_leg: Optional[Dict[str, Any]],
        pe_leg: Optional[Dict[str, Any]],
        spot: Optional[float] = None,
        source_timestamp: Optional[str] = None,
    ) -> PremiumLeadSnapshot:
        snapshot_id = f"pli_{uuid.uuid4().hex[:8]}"

        is_stale = False
        if source_timestamp:
            try:
                from datetime import datetime, timezone
                ts_str = source_timestamp.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > 300:
                    is_stale = True
            except Exception:
                pass

        data_quality = "HIGH"
        if not source_timestamp:
            data_quality = "NO_DATA"
        elif is_stale:
            data_quality = "STALE"

        if not source_timestamp or is_stale or straddle_res.status != "OK" or not ce_leg or not pe_leg:
            blockers = getattr(straddle_res, "blockers", None) or []
            if not source_timestamp:
                blockers.append("MISSING_SOURCE_TIMESTAMP")
            if is_stale:
                blockers.append("STALE_EVIDENCE")

            return PremiumLeadSnapshot(
                snapshot_id=snapshot_id,
                instrument="NIFTY",
                expiry=straddle_res.expiry,
                atm_strike=straddle_res.atm_strike,
                source_timestamp=source_timestamp,
                atm_straddle_price=straddle_res.straddle_price if straddle_res else None,
                lead_side="STALE" if is_stale else "NO_DATA",
                data_quality=data_quality,
                blockers=blockers,
                provenance={"engine": "PLI", "status": data_quality},
            )

        ce_ltp = ce_leg.get("ltp") or 0.0
        pe_ltp = pe_leg.get("ltp") or 0.0

        # Calculate leg price changes
        ce_prev = self._prev_ce_ltp if self._prev_ce_ltp is not None else ce_leg.get("baseline_ltp") or ce_ltp
        pe_prev = self._prev_pe_ltp if self._prev_pe_ltp is not None else pe_leg.get("baseline_ltp") or pe_ltp

        ce_change = round(ce_ltp - ce_prev, 2)
        pe_change = round(pe_ltp - pe_prev, 2)

        self._prev_ce_ltp = ce_ltp
        self._prev_pe_ltp = pe_ltp

        # Compute normalized 0-100 lead indices
        total_abs = abs(ce_change) + abs(pe_change)
        if total_abs > 0:
            # Shift to positive domain
            ce_base = max(0.0, ce_change + 50.0)
            pe_base = max(0.0, pe_change + 50.0)
            sum_base = ce_base + pe_base
            ce_index = round((ce_base / sum_base) * 100.0, 1) if sum_base > 0 else 50.0
            pe_index = round((pe_base / sum_base) * 100.0, 1) if sum_base > 0 else 50.0
        else:
            ce_index = 50.0
            pe_index = 50.0

        # Optional Greeks delta adjustment (if valid delta exists)
        ce_delta = ce_leg.get("delta")
        pe_delta = pe_leg.get("delta")
        greeks_available = (
            ce_delta is not None and pe_delta is not None and isinstance(ce_delta, (int, float))
        )

        why_evidence: Dict[str, Any] = {
            "ce_ltp": ce_ltp,
            "pe_ltp": pe_ltp,
            "ce_change": ce_change,
            "pe_change": pe_change,
            "greeks_available": greeks_available,
            "ce_volume": ce_leg.get("volume"),
            "pe_volume": pe_leg.get("volume"),
            "oi_not_used_for_direction": True,
        }

        # Classification logic
        if ce_change > 0 and pe_change > 0:
            expansion_structure = "TWO_SIDED"
            if abs(ce_index - pe_index) < self.lead_differential_min:
                lead_side = "TWO_SIDED_EXPANSION"
            elif ce_index > pe_index:
                lead_side = "CALL_LEAD"
            else:
                lead_side = "PUT_LEAD"
        elif ce_change < 0 and pe_change < 0:
            expansion_structure = "BALANCED"
            if abs(ce_index - pe_index) < self.lead_differential_min:
                lead_side = "TWO_SIDED_COMPRESSION"
            elif ce_index > pe_index:
                lead_side = "CALL_LEAD"
            else:
                lead_side = "PUT_LEAD"
        elif ce_change > 0 and pe_change <= 0:
            expansion_structure = "ONE_SIDED"
            lead_side = "CALL_LEAD"
        elif pe_change > 0 and ce_change <= 0:
            expansion_structure = "ONE_SIDED"
            lead_side = "PUT_LEAD"
        else:
            expansion_structure = "BALANCED"
            lead_side = "MIXED"

        lead_strength = round(abs(ce_index - pe_index), 1)

        session_range = {
            "high": straddle_res.session_high,
            "low": straddle_res.session_low,
            "position_pct": straddle_res.session_range_position_pct,
        }

        return PremiumLeadSnapshot(
            snapshot_id=snapshot_id,
            instrument="NIFTY",
            expiry=straddle_res.expiry,
            atm_strike=straddle_res.atm_strike,
            source_timestamp=source_timestamp,
            atm_ce_symbol=straddle_res.ce_symbol,
            atm_ce_premium=ce_ltp,
            atm_pe_symbol=straddle_res.pe_symbol,
            atm_pe_premium=pe_ltp,
            atm_straddle_price=straddle_res.straddle_price,
            ce_premium_change=ce_change,
            pe_premium_change=pe_change,
            ce_normalized_lead_index=ce_index,
            pe_normalized_lead_index=pe_index,
            lead_side=lead_side,
            lead_strength=lead_strength,
            lead_acceleration=straddle_res.acceleration,
            expansion_structure=expansion_structure,
            session_straddle_range=session_range,
            data_quality="HIGH",
            blockers=[],
            formula_version="v1.0.0",
            provenance=why_evidence,
            execution_influence="ZERO",
        )
