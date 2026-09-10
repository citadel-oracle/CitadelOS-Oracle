"""Static contracts for the additive ARGUS Fusion Shadow Oracle surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/oracle/page.tsx").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "src/components/institutional/OracleWorkspacePanel.tsx").read_text(encoding="utf-8")
COMPONENT = (
    ROOT / "src/components/institutional/ArgusFusionShadowPanel.tsx"
).read_text(encoding="utf-8")
STYLES = (
    ROOT / "src/components/institutional/ArgusFusionShadowPanel.module.css"
).read_text(encoding="utf-8")


def test_oracle_binds_the_additive_canonical_fusion_feed_once():
    assert "feedSelectors.fusionShadow" in PAGE
    assert PAGE.count("fusionShadow={fusionShadow}") == 1
    assert WORKSPACE.count("<ArgusFusionShadowPanel") == 1
    assert WORKSPACE.index("<OracleFuturesVwapChart") < WORKSPACE.index("<ArgusFusionShadowPanel") < WORKSPACE.index("<FlowPulseStoreBridge")
    assert "<OracleWorkspacePanel" in PAGE


def test_transition_alerts_are_event_identity_deduplicated_and_never_browser_alerts():
    assert "state_event_id" in COMPONENT
    assert "seenTransitions" in COMPONENT
    assert "transitionStreamInitialized" in COMPONENT
    assert "alert(" not in COMPONENT
    assert "toast" in COMPONENT


def test_sound_requires_a_user_gesture_and_reduced_motion_is_supported():
    assert "armAudio" in COMPONENT
    assert "AudioContext" in COMPONENT
    assert "context.resume()" in COMPONENT
    assert "prefers-reduced-motion:reduce" in STYLES
    assert "data-reduced" in COMPONENT


def test_premium_and_ladder_surface_preserve_shadow_research_truth():
    for value in (
        "State first. Outcome afterward.",
        "ASK at hypothetical entry · BID for live research exit",
        "NO LEVELS LOCKED",
        "UNVALIDATED",
        "ZERO EXECUTION INFLUENCE",
        "ARGUS_FUSION_SHADOW_V0",
        "MARKET CLOSED",
        "LAST VALID STATE",
        "QUANT DESK · SHADOW",
        "P&L ₹",
    ):
        assert value in COMPONENT


def test_fusion_surface_keeps_missing_flow_unknown_without_false_data_locked_copy():
    assert "FUTURES_OPTIONS_LIVE_FLOW_UNKNOWN" not in COMPONENT
    assert "flowEvidence.availability" in COMPONENT
    assert "marketClosed" in COMPONENT
    assert "boundaryBreath" in STYLES
    assert "quantDesk" in STYLES
