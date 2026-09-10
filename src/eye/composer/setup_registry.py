"""Setup Registry & Canonical Setup Definitions for Eye Engine E3."""

from typing import Dict, List, Optional
from src.eye.contracts import EventFamily, EventType, EventDirection, AuthorityType
from src.eye.composer.contracts import (
    SetupDefinition,
    PatternStep,
    ContiguityPolicy,
    MatchSkipPolicy,
    EventReusePolicy,
    OverlapPolicy,
)


def get_e3_setup_definitions() -> List[SetupDefinition]:
    """Return all Phase E3 setup definitions (classified by atomic prerequisite support)."""
    
    # 1. LIQUIDITY_SWEEP_RECLAIM
    s1 = SetupDefinition(
        setup_id="EYE_SETUP_LIQUIDITY_SWEEP_RECLAIM_V1",
        setup_version="1.0.0",
        setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Liquidity Pool Sweep and Reclaim",
        status="HISTORICALLY_SUPPORTED_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="POOL_DETECTED",
                accepted_families=(EventFamily.LIQUIDITY,),
                accepted_types=(EventType.LIQUIDITY_POOL_HIGH, EventType.LIQUIDITY_POOL_LOW),
                contiguity=ContiguityPolicy.RELAXED_NEXT,
            ),
            PatternStep(
                step_id="POOL_SWEPT",
                accepted_families=(EventFamily.LIQUIDITY,),
                accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH, EventType.LIQUIDITY_SWEEP_LOW),
                contiguity=ContiguityPolicy.RELAXED_NEXT,
            ),
        ),
    )

    # 2. BREAKOUT_ACCEPTANCE_RETEST
    s2 = SetupDefinition(
        setup_id="EYE_SETUP_BREAKOUT_ACCEPTANCE_RETEST_V1",
        setup_version="1.0.0",
        setup_family="BREAKOUT_ACCEPTANCE_RETEST",
        name="Breakout Acceptance and Retest",
        status="SYNTHETICALLY_TESTABLE_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="BOS_BREAKOUT",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.BOS_BULLISH, EventType.BOS_BEARISH),
            ),
            PatternStep(
                step_id="ACCEPTANCE_RETEST",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.SWING_HIGH, EventType.SWING_LOW),
            ),
        ),
    )

    # 3. FAILED_BREAKOUT_REVERSAL
    s3 = SetupDefinition(
        setup_id="EYE_SETUP_FAILED_BREAKOUT_REVERSAL_V1",
        setup_version="1.0.0",
        setup_family="FAILED_BREAKOUT_REVERSAL",
        name="Failed Breakout Reversal",
        status="SYNTHETICALLY_TESTABLE_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="SWEEP_ATTEMPT",
                accepted_families=(EventFamily.LIQUIDITY,),
                accepted_types=(EventType.LIQUIDITY_SWEEP_HIGH, EventType.LIQUIDITY_SWEEP_LOW),
            ),
            PatternStep(
                step_id="CHOCH_REVERSAL",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.CHOCH_BULLISH, EventType.CHOCH_BEARISH),
            ),
        ),
    )

    # 4. TREND_PULLBACK
    s4 = SetupDefinition(
        setup_id="EYE_SETUP_TREND_PULLBACK_V1",
        setup_version="1.0.0",
        setup_family="TREND_PULLBACK",
        name="Trend Structure Pullback",
        status="SYNTHETICALLY_TESTABLE_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="SWING_LEVEL",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.SWING_HIGH, EventType.SWING_LOW),
            ),
            PatternStep(
                step_id="PULLBACK_REJECT",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.BOS_BULLISH, EventType.BOS_BEARISH),
            ),
        ),
    )

    # 5. COMPRESSION_DISPLACEMENT
    s5 = SetupDefinition(
        setup_id="EYE_SETUP_COMPRESSION_DISPLACEMENT_V1",
        setup_version="1.0.0",
        setup_family="COMPRESSION_DISPLACEMENT",
        name="Compression Volatility Displacement",
        status="SYNTHETICALLY_TESTABLE_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="COMPRESSION_ZONE",
                accepted_families=(EventFamily.ZONE,),
                accepted_types=(EventType.ORDER_BLOCK_BULLISH, EventType.ORDER_BLOCK_BEARISH),
            ),
            PatternStep(
                step_id="DISPLACEMENT_EXPANSION",
                accepted_families=(EventFamily.DISPLACEMENT,),
                accepted_types=(EventType.DISPLACEMENT_BULLISH, EventType.DISPLACEMENT_BEARISH),
            ),
        ),
    )

    # 6. DISPLACEMENT_FVG_RETEST
    s6 = SetupDefinition(
        setup_id="EYE_SETUP_DISPLACEMENT_FVG_RETEST_V1",
        setup_version="1.0.0",
        setup_family="DISPLACEMENT_FVG_RETEST",
        name="Displacement FVG Retest",
        status="HISTORICALLY_SUPPORTED_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="DISPLACEMENT_EXPANSION",
                accepted_families=(EventFamily.DISPLACEMENT,),
                accepted_types=(EventType.DISPLACEMENT_BULLISH, EventType.DISPLACEMENT_BEARISH),
            ),
            PatternStep(
                step_id="FVG_CREATED",
                accepted_families=(EventFamily.IMBALANCE,),
                accepted_types=(EventType.FVG_BULLISH, EventType.FVG_BEARISH),
            ),
        ),
    )

    # 7. BREAKAWAY_FVG_CONTINUATION
    s7 = SetupDefinition(
        setup_id="EYE_SETUP_BREAKAWAY_FVG_CONTINUATION_V1",
        setup_version="1.0.0",
        setup_family="BREAKAWAY_FVG_CONTINUATION",
        name="Breakaway FVG Momentum Continuation",
        status="HISTORICALLY_SUPPORTED_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="STRUCTURE_BOS",
                accepted_families=(EventFamily.STRUCTURE,),
                accepted_types=(EventType.BOS_BULLISH, EventType.BOS_BEARISH),
            ),
            PatternStep(
                step_id="FVG_IMBALANCE",
                accepted_families=(EventFamily.IMBALANCE,),
                accepted_types=(EventType.FVG_BULLISH, EventType.FVG_BEARISH),
            ),
        ),
    )

    # 8. ZONE_FVG_CONFLUENCE
    s8 = SetupDefinition(
        setup_id="EYE_SETUP_ZONE_FVG_CONFLUENCE_V1",
        setup_version="1.0.0",
        setup_family="ZONE_FVG_CONFLUENCE",
        name="Order Block Zone and FVG Confluence",
        status="HISTORICALLY_SUPPORTED_RESEARCH",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(
            PatternStep(
                step_id="ZONE_ORDER_BLOCK",
                accepted_families=(EventFamily.ZONE,),
                accepted_types=(EventType.ORDER_BLOCK_BULLISH, EventType.ORDER_BLOCK_BEARISH),
            ),
            PatternStep(
                step_id="FVG_IMBALANCE",
                accepted_families=(EventFamily.IMBALANCE,),
                accepted_types=(EventType.FVG_BULLISH, EventType.FVG_BEARISH),
            ),
        ),
    )

    # 9. OPTION_PREMIUM_CONFIRMED_CONTINUATION (UNRESOLVED)
    s9 = SetupDefinition(
        setup_id="EYE_SETUP_OPTION_PREMIUM_CONFIRMED_CONTINUATION_V1",
        setup_version="1.0.0",
        setup_family="OPTION_PREMIUM_CONFIRMED_CONTINUATION",
        name="Option Premium Confirmed Continuation",
        status="UNRESOLVED",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(),
    )

    # 10. OPTION_PREMIUM_CONFIRMED_REVERSAL (UNRESOLVED)
    s10 = SetupDefinition(
        setup_id="EYE_SETUP_OPTION_PREMIUM_CONFIRMED_REVERSAL_V1",
        setup_version="1.0.0",
        setup_family="OPTION_PREMIUM_CONFIRMED_REVERSAL",
        name="Option Premium Confirmed Reversal",
        status="UNRESOLVED",
        provenance="PROPOSED_RESEARCH_SETUP",
        steps=(),
    )

    return [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10]


def get_setup_definition_by_id(setup_id: str) -> Optional[SetupDefinition]:
    for sd in get_e3_setup_definitions():
        if sd.setup_id == setup_id:
            return sd
    return None
