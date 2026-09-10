"""Unit tests for PersonalStrategySignal display text and tone presentation contracts."""
from src.eye.personal_strategies.contracts import (
    PersonalStrategySignal,
    StrategyLifecycleState,
)


def test_display_text_and_tone_contracts():
    sig_scanning = PersonalStrategySignal(
        signal_id="sig_1",
        strategy_id="S01",
        strategy_name="BB RSI MOMENTUM",
        short_label="BB-RSI",
        strategy_version="1.0",
        state=StrategyLifecycleState.SCANNING,
        direction="BUY_CE",
        match_count=0,
        match_total=2,
        satisfied_conditions=[],
        missing_conditions=["RSI > 65"],
        next_required_event="WAIT FOR BREAKOUT",
        contract_status="RESOLVED",
        preferred_contract=None,
        geometry_status="ESTABLISHING",
        entry_band=None,
        structural_sl=None,
        informational_targets={},
        risk_status="APPROVED",
        blocker=None,
        execution_status="FAIL_CLOSED",
        event_timestamp="15:00:00",
        source_timestamp="15:00:00",
        freshness=0.0,
        cycle_id="cycle_1",
    )
    assert sig_scanning.display_text == "SCANNING PERSONAL STRATEGIES"
    assert sig_scanning.display_tone == "neutral"
    d_scanning = sig_scanning.to_dict()
    assert d_scanning["display_text"] == "SCANNING PERSONAL STRATEGIES"
    assert d_scanning["display_tone"] == "neutral"

    sig_detected = PersonalStrategySignal(
        signal_id="sig_2",
        strategy_id="S05",
        strategy_name="BB CPR BREAKOUT",
        short_label="BB-CPR",
        strategy_version="1.0",
        state=StrategyLifecycleState.DETECTED,
        direction="BUY_PE",
        match_count=2,
        match_total=2,
        satisfied_conditions=["Condition 1", "Condition 2"],
        missing_conditions=[],
        next_required_event="ENTER",
        contract_status="RESOLVED",
        preferred_contract=None,
        geometry_status="CONFIRMED",
        entry_band=None,
        structural_sl=None,
        informational_targets={},
        risk_status="APPROVED",
        blocker=None,
        execution_status="FAIL_CLOSED",
        event_timestamp="15:00:00",
        source_timestamp="15:00:00",
        freshness=0.0,
        cycle_id="cycle_2",
    )
    assert sig_detected.display_text == "BB-CPR DETECTED"
    assert sig_detected.display_tone == "positive"

    sig_blocked = PersonalStrategySignal(
        signal_id="sig_3",
        strategy_id="S06",
        strategy_name="OPENING MOMENTUM RECOVERY",
        short_label="OPENING MOMENTUM",
        strategy_version="1.0",
        state=StrategyLifecycleState.BLOCKED,
        direction="BUY_CE",
        match_count=1,
        match_total=2,
        satisfied_conditions=["Condition 1"],
        missing_conditions=["BUYING_CLASSIFIER_PROVIDER"],
        next_required_event="PROVIDER_REQUIRED",
        contract_status="RESOLVED",
        preferred_contract=None,
        geometry_status="ESTABLISHING",
        entry_band=None,
        structural_sl=None,
        informational_targets={},
        risk_status="BLOCKED",
        blocker="S06_BUYING_PROVIDER_MISSING",
        execution_status="FAIL_CLOSED",
        event_timestamp="15:00:00",
        source_timestamp="15:00:00",
        freshness=0.0,
        cycle_id="cycle_3",
    )
    assert sig_blocked.display_text == "OPENING MOMENTUM • S06_BUYING_PROVIDER_MISSING"
    assert sig_blocked.display_tone == "negative"
