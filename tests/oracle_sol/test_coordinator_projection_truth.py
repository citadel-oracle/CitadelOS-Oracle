from types import SimpleNamespace
from unittest.mock import Mock

from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator


def test_commit_packaging_does_not_invent_normal_liquidity_or_temporal_direction():
    coordinator = object.__new__(Phase1CognitiveCoordinator)
    coordinator.last_qwen_obs = None
    coordinator.last_gemini_rev = None
    coordinator.evidence_gate = Mock()
    # Control-contract fixture only, no market values, provider or persistence.
    synth = SimpleNamespace(reversal_watch={}, input_revision=1, why_now=[], five_hypotheses={},
        evidence_ids=[], current_state="CALL_DEVELOPING", option_buyer_side="UNRESOLVED",
        what_would_change_my_mind=[], setup_family="UNRESOLVED", entry_window="UNRESOLVED",
        model_name="isolated")
    coordinator._commit_synthesis_to_gate(object(), synth)
    raw = coordinator.evidence_gate.validate_and_commit.call_args.kwargs["raw_response"]
    for key in ("ce_premium_response", "pe_premium_response", "iv_response", "liquidity_or_spread"):
        assert raw["option_buyer_analysis"][key] == "UNRESOLVED"
    assert set(raw["temporal_analysis"].values()) == {"UNRESOLVED"}
