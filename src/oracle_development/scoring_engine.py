"""Complete scoring engine and event fingerprint canonicalization for the Oracle Development segment."""

import hashlib
from typing import Any, Dict, List, Optional, Tuple


class OracleDevScoringEngine:
    """Calculates the composite score (PA 30 + VOB 25 + Derivatives 25 + Execution 20)."""

    def __init__(self):
        pass

    @staticmethod
    def generate_fingerprint(
        instrument: str,
        direction: str,
        timeframe: str,
        structural_location: str,
        trigger_candle_time: int,
        event_time: int,
        parent_trade_family: str
    ) -> str:
        """Generates a unique canonical hash representing one unique market event."""
        payload = (
            f"{instrument}:{direction}:{timeframe}:{structural_location}:"
            f"{trigger_candle_time}:{event_time}:{parent_trade_family}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def compute_scores(
        self,
        pa_analysis: Dict[str, Any],
        vob_data: Dict[str, Any],
        deriv_data: Dict[str, Any],
        exec_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculates the individual scores and the consolidated total score out of 100."""
        import math
        
        def safe_score(val: Any, max_val: float) -> float:
            try:
                f_val = float(val)
                if math.isnan(f_val) or math.isinf(f_val):
                    return 0.0
                return round(max(0.0, min(max_val, f_val)), 2)
            except (ValueError, TypeError):
                return 0.0

        # 1. Price Action Score (already computed and capped at 30 inside PriceActionAnalyzer)
        pa_score = safe_score(pa_analysis.get("score"), 30.0)
        pa_factors = pa_analysis.get("factors") or {}
        
        # 2. VOB Score (Max 25)
        vob_score = 0.0
        vob_factors = {}
        
        proximity = safe_score(vob_data.get("proximity_points"), 10.0)
        ratio = safe_score(vob_data.get("volume_ratio_points"), 10.0)
        disp = safe_score(vob_data.get("displacement_points"), 5.0)
        
        vob_score = safe_score(proximity + ratio + disp, 25.0)
        vob_factors["proximity"] = {"score": proximity, "status": "green" if proximity >= 7 else "grey", "val": vob_data.get("proximity_desc", "N/A")}
        vob_factors["volume_ratio"] = {"score": ratio, "status": "green" if ratio >= 7 else "grey", "val": vob_data.get("ratio_desc", "N/A")}
        vob_factors["displacement"] = {"score": disp, "status": "green" if disp >= 3 else "grey", "val": vob_data.get("displacement_desc", "N/A")}
        vob_state = vob_data.get("vob_state", "WAITING_DATA")
        vob_factors["state"] = {
            "score": 0.0,
            "status": "green" if vob_state in ("ACTIVE_ZONE", "NO_ACTIVE_ZONE") else "red",
            "val": vob_state
        }

        # 3. Derivatives Score (Max 25)
        deriv_score = 0.0
        deriv_factors = {}
        
        argus_pts = safe_score(deriv_data.get("argus_points"), 5.0)
        ose_pts = safe_score(deriv_data.get("ose_points"), 5.0)
        ssi_oic_pts = safe_score(deriv_data.get("ssi_oic_points"), 5.0)
        chain_change_pts = safe_score(deriv_data.get("chain_change_points"), 5.0)
        writer_wall_pts = safe_score(deriv_data.get("writer_wall_points"), 3.0)
        futures_pts = safe_score(deriv_data.get("futures_points"), 2.0)
        
        deriv_score = safe_score(argus_pts + ose_pts + ssi_oic_pts + chain_change_pts + writer_wall_pts + futures_pts, 25.0)
        
        deriv_factors["option_flow"] = {"score": argus_pts, "status": "green" if argus_pts >= 4 else "grey", "val": deriv_data.get("argus_desc", "N/A")}
        deriv_factors["order_pressure"] = {"score": ose_pts, "status": "green" if ose_pts >= 4 else "grey", "val": deriv_data.get("ose_desc", "N/A")}
        deriv_factors["ssi_oic"] = {"score": ssi_oic_pts, "status": "green" if ssi_oic_pts >= 4 else "grey", "val": deriv_data.get("ssi_oic_desc", "N/A")}
        deriv_factors["chain_changes"] = {"score": chain_change_pts, "status": "green" if chain_change_pts >= 4 else "grey", "val": deriv_data.get("chain_desc", "N/A")}
        deriv_factors["writer_wall"] = {"score": writer_wall_pts, "status": "green" if writer_wall_pts >= 2 else "grey", "val": deriv_data.get("wall_desc", "N/A")}
        deriv_factors["futures_trend"] = {"score": futures_pts, "status": "green" if futures_pts >= 1.5 else "grey", "val": deriv_data.get("futures_desc", "N/A")}
        
        derv_bpm = safe_score(deriv_data.get("derv_bpm"), 100.0)
        atr_normalized_derv = safe_score(deriv_data.get("atr_normalized_derv"), 100.0)
        derv_unit = deriv_data.get("derv_unit", "bps/min")
        deriv_factors["derv_metric"] = {
            "score": 0.0,
            "status": "green" if abs(atr_normalized_derv) < 1.5 else "amber",
            "val": f"{derv_bpm:.2f} {derv_unit} (ATR-scaled: {atr_normalized_derv:.2f})"
        }

        # 4. Execution + Protection Score (Max 20)
        exec_score = 0.0
        exec_factors = {}
        
        risk_approved = exec_data.get("risk_approved") is True
        guardian_ready = exec_data.get("guardian_ready") is True
        blocker = exec_data.get("blocker")
        
        contract_pts = safe_score(exec_data.get("contract_integrity_points"), 4.0)
        freshness_pts = safe_score(exec_data.get("quote_freshness_points"), 4.0)
        strike_pts = safe_score(exec_data.get("strike_eligibility_points"), 4.0)
        liquidity_pts = safe_score(exec_data.get("liquidity_spread_points"), 4.0)
        chase_pts = safe_score(exec_data.get("chase_points"), 4.0)
        
        if risk_approved and guardian_ready:
            exec_score = safe_score(contract_pts + freshness_pts + strike_pts + liquidity_pts + chase_pts, 20.0)
        else:
            exec_score = 0.0
            
        exec_factors["contract_integrity"] = {"score": contract_pts, "status": "green" if contract_pts >= 3 else "grey", "val": exec_data.get("contract_desc", "N/A")}
        exec_factors["quote_freshness"] = {"score": freshness_pts, "status": "green" if freshness_pts >= 3 else "red", "val": exec_data.get("freshness_desc", "N/A")}
        exec_factors["strike_eligibility"] = {"score": strike_pts, "status": "green" if strike_pts >= 3 else "red", "val": exec_data.get("strike_desc", "N/A")}
        exec_factors["liquidity_spread"] = {"score": liquidity_pts, "status": "green" if liquidity_pts >= 3 else "grey", "val": exec_data.get("liquidity_desc", "N/A")}
        exec_factors["chase_limit"] = {"score": chase_pts, "status": "green" if chase_pts >= 3 else "amber", "val": exec_data.get("chase_desc", "N/A")}
        
        risk_val = "APPROVED"
        if not risk_approved:
            risk_val = f"BLOCKED: {blocker}"
            if blocker in ("INSUFFICIENT_HISTORY", "CONTRACT_ROLLOVER_PENDING"):
                risk_val += f" (Need {exec_data.get('required_count', 0)}, Got {exec_data.get('actual_count', 0)}, Missing {exec_data.get('missing_count', 0)})"
        exec_factors["risk_gate"] = {"score": 0.0, "status": "green" if risk_approved else "red", "val": risk_val}
        
        guard_val = "READY"
        if not guardian_ready:
            guard_val = f"BLOCKED: {blocker}"
            if blocker in ("INSUFFICIENT_HISTORY", "CONTRACT_ROLLOVER_PENDING"):
                guard_val += f" (Missing {exec_data.get('missing_count', 0)})"
        exec_factors["guardian_gate"] = {"score": 0.0, "status": "green" if guardian_ready else "red", "val": guard_val}

        total_score = safe_score(pa_score + vob_score + deriv_score + exec_score, 100.0)
        
        # Consolidation of factors
        all_contributors = {}
        for k, v in pa_factors.items():
            all_contributors[f"PA_{k}"] = v
        for k, v in vob_factors.items():
            all_contributors[f"VOB_{k}"] = v
        for k, v in deriv_factors.items():
            all_contributors[f"DERIV_{k}"] = v
        for k, v in exec_factors.items():
            all_contributors[f"EXEC_{k}"] = v
 
        return {
            "total_score": total_score,
            "pa_score": pa_score,
            "vob_score": vob_score,
            "deriv_score": deriv_score,
            "exec_score": exec_score,
            "all_contributors": all_contributors,
            "risk_approved": risk_approved,
            "guardian_ready": guardian_ready
        }
