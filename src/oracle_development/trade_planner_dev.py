"""Trade planner and sizing engine for the Oracle Development segment."""

from typing import Any, Dict, Optional


class OracleDevTradePlanner:
    """Computes targets, structural stops, and conviction-locked lot sizes."""

    def __init__(self, max_configured_lots: int = 10):
        self.max_configured_lots = max_configured_lots

    def compute_conviction_ceiling(self, scores: Dict[str, Any], pa_aligned: bool, vob_aligned: bool, deriv_aligned: bool) -> int:
        """Determines the conviction ceiling lot size based on alignment factor combinations."""
        total_score = scores.get("total_score") or 0.0
        
        # All factors highest-grade, score >= 85, no veto
        if total_score >= 85.0 and pa_aligned and vob_aligned and deriv_aligned and scores.get("risk_approved") and scores.get("guardian_ready"):
            return 10
        
        # PA + VOB + Derivatives aligned
        if pa_aligned and vob_aligned and deriv_aligned:
            return 5
            
        # PA + VOB aligned
        if pa_aligned and vob_aligned:
            return 3
            
        # Valid VOB only OR PA only
        if pa_aligned or vob_aligned:
            return 1
            
        return 0

    def plan_trade(
        self,
        setup_family: str,
        direction: str,
        entry_price: float,
        structural_sl_price: float,
        scores: Dict[str, Any],
        pa_aligned: bool,
        vob_aligned: bool,
        deriv_aligned: bool,
        risk_lots: int = 10,
        capital_lots: int = 10,
        liquidity_lots: int = 10
    ) -> Dict[str, Any]:
        """Calculates sizing lot limits and target targets based on structural invalidations."""

        # FAIL-CLOSED GATE: any gate veto (INSUFFICIENT_HISTORY, STALE_CURRENT_SESSION, etc.)
        # must force approved_lots to 0.  Explicit `is False` so callers that omit these
        # keys (e.g. isolated unit tests for the planner) are unaffected.
        conviction_ceiling = 0
        if scores.get("risk_approved") is False or scores.get("guardian_ready") is False:
            approved_lots = 0

        else:
            conviction_ceiling = self.compute_conviction_ceiling(scores, pa_aligned, vob_aligned, deriv_aligned)

            # Final approved lots = min of conviction, risk, capital, liquidity, and configured maximum
            approved_lots = min(
                conviction_ceiling,
                risk_lots,
                capital_lots,
                liquidity_lots,
                self.max_configured_lots
            )
            # Ensure it is at least 0
            approved_lots = max(0, approved_lots)


        # SL Distance
        sl_distance = abs(entry_price - structural_sl_price)
        if sl_distance <= 0:
            sl_distance = 5.0 # default min distance

        # Target 1 is at least 1.5x the SL distance
        target_distance = 1.5 * sl_distance
        
        if direction == "CALL":
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance

        return {
            "conviction_ceiling": conviction_ceiling,
            "approved_lots": approved_lots,
            "entry_price": entry_price,
            "structural_sl": structural_sl_price,
            "target_price": target_price,
            "sl_distance": sl_distance,
            "target_distance": target_distance,
            "rr_ratio": round(target_distance / sl_distance, 2) if sl_distance > 0 else 1.5
        }
