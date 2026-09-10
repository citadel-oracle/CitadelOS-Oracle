import json
import pytest
from typing import Any, Mapping

def run_oracle(payload: Mapping[str, Any]) -> None:
    # A. Bias arithmetic & B. Component sums & C. Normalization & D. Net edge
    decision = payload.get("decision", {})
    quality = payload.get("quality", {})
    
    # We will test the components. The new spec requires exactly 9 components 
    # to be summed to get call_raw and put_raw, then normalized.
    # We will check this once Phase 3 is implemented. For now, we assert the invariants.

    call_score = payload.get("decision", {}).get("call_normalized") or payload.get("pressure", {}).get("call_score")
    put_score = payload.get("decision", {}).get("put_normalized") or payload.get("pressure", {}).get("put_score")
    net_edge = payload.get("decision", {}).get("net_edge") or payload.get("pressure", {}).get("net_edge")
    
    if call_score is not None and put_score is not None:
        assert abs((call_score + put_score) - 100.00) <= 0.01, f"Call + Put = {call_score + put_score}, expected 100.00"
        assert abs(net_edge - (put_score - call_score)) <= 0.01, f"Net edge {net_edge} != put - call ({put_score - call_score})"

    # G. Seven-strike universe integrity
    selection = payload.get("contract_selection", {})
    if selection.get("status") == "AVAILABLE":
        assert selection.get("unique_strike_count") == 7, f"Expected 7 unique strikes, got {selection.get('unique_strike_count')}"
        assert selection.get("CE_count") == 7, f"Expected 7 CE legs, got {selection.get('CE_count')}"
        assert selection.get("PE_count") == 7, f"Expected 7 PE legs, got {selection.get('PE_count')}"

        # H. Contract contribution totals
        ranks = selection.get("all_candidate_ranks", [])
        assert len(ranks) == 14, f"Expected 14 total legs, got {len(ranks)}"
        for leg in ranks:
            expected_score = round(sum(c.get("contribution", 0.0) for c in leg.get("score_breakdown", {}).values()), 2)
            assert abs(leg["contract_score"] - max(0.0, expected_score)) <= 0.01, f"Score mismatch for {leg['trading_symbol']}: {leg['contract_score']} vs {expected_score}"

            # J. Stretch blocking
            if leg.get("stretch_state") in ("STRETCHED", "EXTREME"):
                assert leg["status"] != "CANDIDATE", f"Blocked stretch state {leg['stretch_state']} is a CANDIDATE"
                
            # K. Gamma/IV availability consistency
            if not leg.get("gamma_available"):
                assert leg.get("gamma_risk") == 0.0, f"Gamma unavailable but risk is {leg.get('gamma_risk')}"
                assert leg.get("score_breakdown", {}).get("gamma_risk", {}).get("contribution", 0.0) == 0.0

        # I. Winner eligibility & L. Selected-contract direction consistency
        winner = next((r for r in ranks if r.get("rank") == 1 and r.get("status") == "CANDIDATE"), None)
        active_bias = payload.get("decision", {}).get("direction", "BALANCED")
        
        if active_bias == "BALANCED":
            # No entry ready, ranking is analytical
            pass
        elif active_bias == "CALL" and winner:
            assert winner["side"] == "CE", "CALL bias selected a PE winner"
        elif active_bias == "PUT" and winner:
            assert winner["side"] == "PE", "PUT bias selected a CE winner"

def test_oracle_can_load_sample():
    # Placeholder for actual payload injection
    pass
