"""
PRE — Premium Regime Engine

Answers: Is the environment suitable for option buying?
Classifies:
  - EARLY_EXPANSION
  - ESTABLISHED_EXPANSION
  - COMPRESSION
  - PREMIUM_MELT
  - MIXED
  - EXHAUSTED_OR_CHASE
  - NO_DATA
  - STALE

Outputs Premium Layer State:
  - BUYING_FRIENDLY
  - WAIT
  - AVOID
  - NO_DATA

HARD RULE: PRE must NOT output BUY CE or BUY PE.
"""

from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional
from src.premium_intelligence.contracts import PremiumRegimeSnapshot
from src.premium_intelligence.straddle import StraddleCalculationResult


class PremiumRegimeEngine:
    def __init__(
        self,
        expansion_velocity_min: float = 1.5,
        melt_risk_min: float = 2.0,
        chase_std_min: float = 2.5,
    ):
        self.expansion_velocity_min = expansion_velocity_min
        self.melt_risk_min = melt_risk_min
        self.chase_std_min = chase_std_min

        # Tracking bar expansion persistence
        self._expansion_bars_count: int = 0

    def evaluate_regime(
        self,
        straddle_res: StraddleCalculationResult,
        ce_leg: Optional[Dict[str, Any]],
        pe_leg: Optional[Dict[str, Any]],
        spot: Optional[float] = None,
        source_timestamp: Optional[str] = None,
    ) -> PremiumRegimeSnapshot:
        snapshot_id = f"pre_{uuid.uuid4().hex[:8]}"

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

        data_state = "LIVE"
        if not source_timestamp:
            data_state = "NO_DATA"
        elif is_stale:
            data_state = "STALE"
            
        if not source_timestamp or is_stale or straddle_res.status != "OK" or not ce_leg or not pe_leg:
            blockers = getattr(straddle_res, "blockers", None) or []
            if not source_timestamp:
                blockers.append("MISSING_SOURCE_TIMESTAMP")
            if is_stale:
                blockers.append("STALE_EVIDENCE")
                
            return PremiumRegimeSnapshot(
                snapshot_id=snapshot_id,
                instrument="NIFTY",
                expiry=straddle_res.expiry,
                atm_strike=straddle_res.atm_strike,
                source_timestamp=source_timestamp,
                data_state=data_state,
                atm_straddle_price=straddle_res.straddle_price if straddle_res else None,
                regime="STALE" if is_stale else "NO_DATA",
                premium_layer_state="NO_DATA",
                blockers=blockers,
                provenance={"engine": "PRE", "status": data_state},
            )

        straddle_price = straddle_res.straddle_price or 0.0
        velocity = straddle_res.velocity
        acceleration = straddle_res.acceleration
        session_change = straddle_res.session_change or 0.0
        bar_change = straddle_res.bar_change or 0.0

        # Track expansion persistence
        if bar_change > 0:
            self._expansion_bars_count += 1
        else:
            self._expansion_bars_count = max(0, self._expansion_bars_count - 1)

        # 0-100 Normalized Indices
        # 1. Expansion Index
        exp_index = min(100.0, max(0.0, 50.0 + (velocity * 10.0) + (self._expansion_bars_count * 5.0)))
        exp_index = round(exp_index, 1)

        # 2. Compression Index
        comp_index = min(100.0, max(0.0, 50.0 - (velocity * 10.0)))
        comp_index = round(comp_index, 1)

        # 3. Melt / Decay Index
        # High theta / small price movement -> high melt
        theta_decay = abs((ce_leg.get("theta") or 0.0) + (pe_leg.get("theta") or 0.0))
        if bar_change <= 0 and straddle_res.session_range_position_pct is not None:
            range_tightness = max(0.0, 50.0 - abs(straddle_res.session_range_position_pct - 50.0))
            melt_index = min(100.0, max(0.0, 30.0 + (theta_decay * 2.0) + (range_tightness * 0.8)))
        else:
            melt_index = min(100.0, max(0.0, 20.0 + (theta_decay * 1.5)))
        melt_index = round(melt_index, 1)

        # 4. Movement Efficiency (spot move vs straddle cost)
        efficiency = 50.0
        if spot is not None and straddle_price > 0:
            # Ratio of spot movement relative to straddle premium
            eff_ratio = min(2.0, abs(session_change) / max(1.0, straddle_price * 0.05))
            efficiency = round(min(100.0, max(0.0, eff_ratio * 50.0)), 1)

        # IV Impulse
        ce_iv = ce_leg.get("iv")
        pe_iv = pe_leg.get("iv")
        iv_impulse = None
        if ce_iv is not None and pe_iv is not None and isinstance(ce_iv, (int, float)):
            iv_impulse = round((ce_iv + pe_iv) / 2.0, 2)

        # Chase / Exhaustion state
        if straddle_res.session_range_position_pct is not None and straddle_res.session_range_position_pct > 92.0 and velocity > 3.0:
            chase_state = "EXHAUSTED"
        elif velocity > 2.0:
            chase_state = "HIGH"
        elif velocity > 0.8:
            chase_state = "MODERATE"
        else:
            chase_state = "LOW"

        # Regime & Premium Layer State Classification
        if chase_state == "EXHAUSTED":
            regime = "EXHAUSTED_OR_CHASE"
            layer_state = "AVOID"
        elif melt_index > 65.0 and bar_change < 0:
            regime = "PREMIUM_MELT"
            layer_state = "AVOID"
        elif velocity < -1.0 or comp_index > 65.0:
            regime = "COMPRESSION"
            layer_state = "WAIT"
        elif self._expansion_bars_count >= 3 and velocity > 0.5:
            regime = "ESTABLISHED_EXPANSION"
            layer_state = "BUYING_FRIENDLY"
        elif velocity >= self.expansion_velocity_min or exp_index > 60.0:
            regime = "EARLY_EXPANSION"
            layer_state = "BUYING_FRIENDLY"
        else:
            regime = "MIXED"
            layer_state = "WAIT"

        why_evidence: Dict[str, Any] = {
            "straddle_price": straddle_price,
            "velocity": velocity,
            "acceleration": acceleration,
            "expansion_bars_count": self._expansion_bars_count,
            "exp_index": exp_index,
            "melt_index": melt_index,
            "efficiency": efficiency,
            "iv_impulse": iv_impulse,
            "spot": spot,
        }

        return PremiumRegimeSnapshot(
            snapshot_id=snapshot_id,
            instrument="NIFTY",
            expiry=straddle_res.expiry,
            atm_strike=straddle_res.atm_strike,
            source_timestamp=source_timestamp,
            data_state="LIVE" if source_timestamp else "RESTORED",
            atm_straddle_price=straddle_price,
            straddle_bar_change=bar_change,
            straddle_session_change=session_change,
            straddle_velocity=velocity,
            straddle_acceleration=acceleration,
            premium_expansion_index=exp_index,
            premium_compression_index=comp_index,
            melt_decay_index=melt_index,
            iv_impulse=iv_impulse,
            movement_efficiency=efficiency,
            chase_exhaustion_state=chase_state,
            regime=regime,
            premium_layer_state=layer_state,
            blockers=[],
            formula_version="v1.0.0",
            provenance=why_evidence,
            execution_influence="ZERO",
        )
