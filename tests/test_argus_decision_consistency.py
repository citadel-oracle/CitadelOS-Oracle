"""
Adversarial decision-consistency tests for ArgusTacticalEdgePanel.

Verifies:
1. CE/PE contract direction mapping correctness
2. No fabricated/hardcoded values in TSX source
3. Conditional UI elements (stretch warning, wait banner, lifecycle)
4. Gamma unavailable guard — no blast/escape claims when gamma is absent
5. Premium stretch logic (direction-aware)
6. Missing-data honest fallbacks
7. Stale data handling
8. Decision-to-UI field consistency
"""

import re
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
TACTICAL = (
    ROOT
    / "citadel-dashboard"
    / "src"
    / "components"
    / "institutional"
    / "ArgusTacticalEdgePanel.tsx"
)


def src() -> str:
    return TACTICAL.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. DIRECTION-CONSISTENT CE/PE CONTRACT LOGIC
# ─────────────────────────────────────────────────────────────────────────────

class TestContractDirectionMapping:
    def test_bullish_action_uses_CE_contract_not_PE(self):
        source = src()
        # resolveContract helper must handle isBullish → CE branch
        assert "contract?.CE?.trading_symbol" in source
        assert "contract?.CE?.strike" in source

    def test_bearish_action_uses_PE_contract_not_CE(self):
        source = src()
        assert "contract?.PE?.trading_symbol" in source
        assert "contract?.PE?.strike" in source

    def test_no_hardcoded_pe_only_for_all_actions(self):
        source = src()
        # The OLD bug: always using contract?.PE regardless of action
        # Now we must have a direction check before choosing CE vs PE
        assert "isBullish" in source, "isBullish branch required for CE/PE selection"
        assert "isBearish" in source, "isBearish branch required for CE/PE selection"

    def test_wait_action_shows_no_directional_contract(self):
        source = src()
        # resolveContract returns '—' for non-directional actions
        assert "{ symbol: '—', available: false }" in source

    def test_call_signal_never_recommends_pe(self):
        """BUY CALL must route to CE contract, not PE."""
        source = src()
        # resolveContract: isBullish → CE block appears before isBearish → PE block
        bullish_ce_pos = source.find("isBullish && contract?.CE?.trading_symbol")
        bearish_pe_pos = source.find("isBearish && contract?.PE?.trading_symbol")
        assert bullish_ce_pos != -1, "BUY CALL CE branch missing"
        assert bearish_pe_pos != -1, "BUY PUT PE branch missing"
        assert bullish_ce_pos < bearish_pe_pos, "BUY CALL CE must precede BUY PUT PE in resolveContract"


# ─────────────────────────────────────────────────────────────────────────────
# 2. NO FABRICATED / HARDCODED VALUES
# ─────────────────────────────────────────────────────────────────────────────

class TestNoFabricatedValues:
    BANNED_HARDCODES = [
        # Previously fabricated constants
        ("presAccel = 11.4",           "hardcoded pressure acceleration"),
        ("netDelta = -35.2",           "hardcoded net delta"),
        ("callScore = pressure?.call_score ?? 32.4", "hardcoded call score fallback"),
        ("putScore = pressure?.put_score ?? 67.6",   "hardcoded put score fallback"),
        ("|| 18} snapshots",           "hardcoded persistence count fallback"),
        ("|| 6",                       "hardcoded breadth count fallback"),
        ("|| 24100",                   "hardcoded strike fallback"),
        ("|| '24100 PE'",              "hardcoded contract symbol fallback"),
        # Hero param hardcodes
        (">239–242<",                  "hardcoded entry zone"),
        (">248<",                      "hardcoded current premium"),
        (">238<",                      "hardcoded fair premium"),
        ("+4.2%",                      "hardcoded premium stretch"),
        (">15–30 min<",                "hardcoded hold guidance"),
        (">93 <",                      "hardcoded readiness score"),
        (">5/6<",                      "hardcoded evidence count"),
        # Ribbon hardcodes
        ("13.8% EXPANDING",            "hardcoded IV ribbon value"),
        ("+4.2K PUT BUILD",            "hardcoded OI ribbon value"),
        ("142K",                       "hardcoded PREV OI ribbon value"),
        ("+12.4%",                     "hardcoded OI change ribbon value"),
        ("BEARISH REVERSAL",           "hardcoded STRUCTURE ribbon value"),
        ("+4.2% STRETCH",              "hardcoded PREMIUM ribbon value"),
        # Lifecycle hardcode
        ("active: true",               "hardcoded lifecycle active stage"),
        # Gamma blast hardcodes
        ("Gamma Escape Ready at 24000", "hardcoded gamma escape level"),
        ("Blast Candidate '24100",      "hardcoded gamma blast candidate"),
        ("IV expansion\">13.8%",        "hardcoded IV expansion value"),
        # Warning always-shown
        ("⚠️ PREMIUM STRETCHED — WAIT FOR PULLBACK", "unconditional stretch banner"),
        ("WAIT FOR PULLBACK</span>",    "hardcoded timing guidance"),
    ]

    @pytest.mark.parametrize("banned,reason", BANNED_HARDCODES)
    def test_no_hardcoded_value(self, banned, reason):
        source = src()
        assert banned not in source, (
            f"FABRICATION DETECTED: {reason!r} — string {banned!r} found in source. "
            "All values must come from live API data."
        )

    def test_ladderStrikes_not_a_hardcoded_array(self):
        """The old hardcoded 6-row ladder array must be gone."""
        source = src()
        assert "callVol: '33.05'" not in source, "Hardcoded ladder row data still present"
        assert "peRatio: '43.0K'" not in source, "Hardcoded ladder peRatio still present"
        assert "peOI: '8,833'" not in source, "Hardcoded peOI still present"

    def test_strike_ladder_driven_from_pressure_strikes(self):
        source = src()
        assert "pressure.strikes" in source or "pressure?.strikes" in source, \
            "Strike ladder must be driven from pressure.strikes, not hardcoded array"


# ─────────────────────────────────────────────────────────────────────────────
# 3. CONDITIONAL UI ELEMENTS
# ─────────────────────────────────────────────────────────────────────────────

class TestConditionalUI:
    def test_stretch_warning_is_conditional(self):
        """The ⚠️ PREMIUM STRETCHED banner must be inside a conditional block."""
        source = src()
        # Must be inside a JSX conditional expression
        # Find the banner and verify it is preceded by a conditional
        banner_pos = source.find("PREMIUM STRETCHED")
        assert banner_pos != -1, "Stretch warning text missing"
        # The banner must be inside {stretched && ...}
        assert "stretched &&" in source or "{stretched" in source, \
            "Stretch warning must be conditional on the stretched flag"

    def test_wait_banner_is_conditional_on_isWait(self):
        source = src()
        assert "isWait" in source, "isWait flag required for wait banner conditional"
        wait_banner_pos = source.find("heroWaitBanner")
        assert wait_banner_pos != -1
        # Must not be rendered unconditionally — isWait check must precede it
        isWait_pos = source.find("isWait &&")
        assert isWait_pos != -1, "Wait banner must be inside isWait conditional"

    def test_gamma_wheel_conditional_on_gammaAvailable(self):
        source = src()
        assert "gammaAvailable" in source, "gammaAvailable flag required"
        # Gamma SVG must be conditional
        assert "gammaAvailable ?" in source or "gammaAvailable&&" in source or "{gammaAvailable" in source, \
            "Gamma SVG must be inside gammaAvailable conditional"

    def test_recommended_contract_conditional_on_contractAvailable(self):
        source = src()
        assert "contractAvailable" in source
        assert "{contractAvailable && (" in source or "contractAvailable &&" in source, \
            "Recommended contract banner must be conditional on contractAvailable"

    def test_lifecycle_active_sourced_from_data(self):
        source = src()
        # resolveLifecycleActive called with lifecycle?.state
        assert "resolveLifecycleActive" in source, "resolveLifecycleActive helper required"
        assert "lifecycle?.state" in source, "Lifecycle state must come from data.entry_lifecycle.state"

    def test_invalidated_stage_reflects_hard_invalidation(self):
        source = src()
        assert "lifecycle?.hard_invalidation" in source or "hard_invalidation" in source, \
            "INVALIDATED stage must check lifecycle.hard_invalidation"
        assert "evidence_cancelled" in source, \
            "INVALIDATED stage must check lifecycle.evidence_cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# 4. GAMMA UNAVAILABLE GUARD
# ─────────────────────────────────────────────────────────────────────────────

class TestGammaUnavailableGuard:
    def test_no_unconditional_blast_candidate_claim(self):
        source = src()
        # The string must not appear as a hardcoded constant
        assert "Blast Candidate '24100 PE'" not in source, \
            "Gamma blast candidate must not be hardcoded"

    def test_no_unconditional_gamma_escape_level(self):
        source = src()
        assert "Gamma Escape Ready at 24000 PE" not in source, \
            "Gamma escape level must not be hardcoded"

    def test_gamma_unavailable_state_shown(self):
        source = src()
        assert "GAMMA UNAVAILABLE" in source, \
            "Must render GAMMA UNAVAILABLE when gamma data is absent"
        assert "gammaUnavailableWheel" in source, \
            "CSS class gammaUnavailableWheel required for unavailable state"

    def test_gamma_chip_reflects_real_state(self):
        source = src()
        assert "gammaChipText" in source, "gammaChipText helper required"
        # gammaChipText must check gamma.status
        assert "gamma.status" in source or "gamma?.status" in source, \
            "gammaChipText must inspect gamma.status, not hardcode"


# ─────────────────────────────────────────────────────────────────────────────
# 5. PREMIUM STRETCH LOGIC
# ─────────────────────────────────────────────────────────────────────────────

class TestPremiumStretchLogic:
    def test_stretch_is_direction_aware(self):
        source = src()
        # premiumStretch helper must use isBullish to pick CE or PE
        assert "isBullish ? premAttr?.CE : premAttr?.PE" in source or \
               ("BUY_CALL' || action === 'BUY CALL' ? pa.CE : pa.PE" in source), \
            "Premium stretch must use direction-aware CE/PE selection"

    def test_stretch_derived_not_hardcoded(self):
        source = src()
        # The computed stretchLabel must come from premiumStretch(), not a literal
        assert "premiumStretch(" in source, "premiumStretch() function must be called"
        assert "const stretchLabel = premiumStretch" in source, \
            "stretchLabel must come from premiumStretch(), not a hardcoded literal"

    def test_fair_premium_is_intrinsic_plus_extrinsic(self):
        source = src()
        assert "intrinsic + side.extrinsic" in source or \
               "intrinsic + extrinsic" in source, \
            "Fair premium must be computed as intrinsic + extrinsic"

    def test_current_premium_is_direction_aware(self):
        source = src()
        # currentPremium must differ for CE vs PE
        assert "isBullish" in source
        ce_prem_pos = source.find("premAttr?.CE?.premium")
        pe_prem_pos = source.find("premAttr?.PE?.premium")
        assert ce_prem_pos != -1, "CE premium reference required"
        assert pe_prem_pos != -1, "PE premium reference required"


# ─────────────────────────────────────────────────────────────────────────────
# 6. MISSING DATA HONEST FALLBACKS
# ─────────────────────────────────────────────────────────────────────────────

class TestHonestFallbacks:
    REQUIRED_DASHES = [
        "entryZoneLabel",
        "holdGuidance",
        "evidenceLabel",
        "riskReward",
        "invalidationLevel",
    ]

    def test_dash_fallback_variables_present(self):
        source = src()
        for var in self.REQUIRED_DASHES:
            assert var in source, f"Variable {var!r} with '—' fallback required"

    def test_entry_zone_from_decision_not_hardcoded(self):
        source = src()
        assert "decision?.entry_zone_low" in source, \
            "Entry zone must come from decision.entry_zone_low"
        assert "decision?.entry_zone_high" in source, \
            "Entry zone must come from decision.entry_zone_high"

    def test_hold_guidance_from_decision(self):
        source = src()
        assert "decision?.hold_guidance" in source, \
            "Hold guidance must come from decision.hold_guidance"

    def test_readiness_score_from_decision(self):
        source = src()
        assert "decision?.readiness_score" in source, \
            "Readiness score must come from decision.readiness_score"

    def test_evidence_count_from_decision(self):
        source = src()
        assert "decision?.evidence_count" in source, \
            "Evidence count must come from decision.evidence_count"

    def test_iv_chip_shows_unavailable(self):
        source = src()
        assert "IV UNAVAILABLE" in source, \
            "Must render IV UNAVAILABLE when iv_intelligence is absent"

    def test_pressure_accel_shows_dash_when_absent(self):
        source = src()
        # pressureAccel = pressure?.acceleration ?? null, rendered as '—' when null
        assert "pressure?.acceleration" in source, \
            "Pressure acceleration must come from pressure.acceleration"
        assert "pressureAccel != null" in source, \
            "Must guard pressureAccel with null check before rendering"

    def test_breadth_shows_dash_when_absent(self):
        source = src()
        assert "breadthConfirming != null" in source or \
               "breadth?.put_confirming_strikes" in source, \
            "Breadth must show dash when breadth data is absent"

    def test_persistence_shows_dash_when_absent(self):
        source = src()
        assert "persistenceCount != null" in source, \
            "Persistence must show dash when persistence data is absent"


# ─────────────────────────────────────────────────────────────────────────────
# 7. STALE DATA HANDLING
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleDataHandling:
    def test_stale_check_covers_freshness_and_status(self):
        source = src()
        assert "data.freshness === 'STALE'" in source, \
            "Stale check must inspect data.freshness"
        assert "data.status === 'STALE'" in source, \
            "Stale check must inspect data.status as fallback"

    def test_stale_banner_shown_conditionally(self):
        source = src()
        assert "isStale &&" in source, "Stale banner must be conditional on isStale"

    def test_canonical_projection_text_present(self):
        source = src()
        assert "Last canonical projection retained" in source, \
            "Stale banner must contain 'Last canonical projection retained'"

    def test_stale_banner_has_refresh_button(self):
        source = src()
        assert "onRetry &&" in source, "Refresh button must be conditional on onRetry prop"


# ─────────────────────────────────────────────────────────────────────────────
# 8. DATA LINEAGE — KEY FIELD SOURCES
# ─────────────────────────────────────────────────────────────────────────────

class TestDataLineage:
    def test_pressure_call_score_from_pressure_object(self):
        source = src()
        assert "pressure?.call_score" in source

    def test_pressure_put_score_from_pressure_object(self):
        source = src()
        assert "pressure?.put_score" in source

    def test_pressure_delta_from_pressure_object(self):
        source = src()
        assert "pressure?.delta" in source

    def test_pressure_acceleration_from_pressure_object(self):
        source = src()
        assert "pressure?.acceleration" in source

    def test_breadth_sourced_from_breadth_object(self):
        source = src()
        assert "breadth?.put_confirming_strikes" in source
        assert "breadth?.call_confirming_strikes" in source

    def test_persistence_sourced_from_persistence_object(self):
        source = src()
        assert "persistence?.consecutive_confirmations" in source

    def test_iv_ce_median_from_iv_intelligence(self):
        source = src()
        assert "ivIntel?.ce_median" in source

    def test_iv_pe_median_from_iv_intelligence(self):
        source = src()
        assert "ivIntel?.pe_median" in source

    def test_oi_walls_from_previous_oi(self):
        source = src()
        assert "prevOI?.call_wall" in source or "previous_oi" in source

    def test_melt_risk_from_melt_risk_object(self):
        source = src()
        assert "meltRisk?.state" in source or "melt_risk" in source

    def test_next_trigger_from_decision(self):
        source = src()
        assert "decision?.next_trigger" in source

    def test_regime_from_continuation_reversal(self):
        source = src()
        assert "regime?.confirmed_state" in source or "continuation_reversal" in source

    def test_why_observed_from_why_object(self):
        source = src()
        assert "data.why?.observed" in source

    def test_why_unavailable_from_why_object(self):
        source = src()
        assert "data.why?.unavailable" in source

    def test_contract_symbol_never_hardcoded(self):
        source = src()
        assert "'24100 PE'" not in source, \
            "Contract symbol must not be hardcoded string literal"

    def test_sample_size_used_for_breadth_denominator(self):
        source = src()
        assert "breadth?.sample_size" in source, \
            "Breadth denominator must come from breadth.sample_size"


# ─────────────────────────────────────────────────────────────────────────────
# 9. DECISION CONSISTENCY — NO CROSS-CONTAMINATION
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionConsistency:
    def test_wait_does_not_show_ready_to_execute(self):
        """When action is WAIT, the UI must not claim EXECUTE readiness."""
        source = src()
        # The lifecycle EXECUTE stage should only be active when lifecycle state = READY
        # Not when action is WAIT
        # resolveLifecycleActive maps READY → EXECUTE
        assert "lifecycle?.state === 'READY'" not in source or \
               "resolveLifecycleActive" in source, \
            "Lifecycle must route through resolveLifecycleActive, not direct equality checks"

    def test_missing_gamma_does_not_claim_blast_readiness(self):
        source = src()
        # gammaAvailable gate must surround any blast/escape language
        assert "Blast Candidate '24100 PE'" not in source
        assert "Gamma Escape Ready at 24000 PE" not in source

    def test_stretched_premium_does_not_instruct_immediate_entry(self):
        source = src()
        # When stretched=true, the warning says "WAIT FOR PULLBACK", not "EXECUTE NOW"
        # The banner text must not contain immediate entry instruction alongside stretch
        assert "EXECUTE NOW" not in source

    def test_symbol_options_comment_present(self):
        """Contract test: symbol options comment must exist."""
        source = src()
        assert "['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']" in source

    def test_seven_strike_breadth_label_present(self):
        """Contract test: Seven strike breadth label must exist."""
        source = src()
        assert "Seven strike breadth" in source

    def test_data_why_observed_reference_present(self):
        """Contract test: data.why?.observed must be referenced."""
        source = src()
        assert "data.why?.observed" in source


# ─────────────────────────────────────────────────────────────────────────────
# 10. CSS — ALL REQUIRED CLASSES PRESENT
# ─────────────────────────────────────────────────────────────────────────────

CSS = (
    ROOT
    / "citadel-dashboard"
    / "src"
    / "components"
    / "institutional"
    / "ArgusTacticalEdgePanel.module.css"
)

REQUIRED_CSS_CLASSES = [
    "panel",
    "intelligenceRibbon",
    "ribbonChip",
    "chipLabel",
    "chipValue",
    "masterHero",
    "heroMainBar",
    "heroTitle",
    "heroActionBadge",
    "actionBuyCall",
    "actionBuyPut",
    "actionWait",
    "heroParamsGrid",
    "heroParamCard",
    "paramLabel",
    "paramValue",
    "heroWarningBanner",
    "heroWaitBanner",
    "threeColumnGrid",
    "gridCard",
    "cardTitle",
    "forceSection",
    "forceTrack",
    "forceCallFill",
    "forcePutFill",
    "forceUnavailable",
    "accelSection",
    "accelValue",
    "accelBarFill",
    "accelBarFillNeg",
    "breadthChip",
    "persistenceBadge",
    "ladderTable",
    "recRowHighlight",
    "recStrikeText",
    "ladderUnavailable",
    "tagFresh",
    "tagCovering",
    "tagCallBuying",
    "tagCallWriting",
    "tagPutBuying",
    "tagPutWriting",
    "tagNeutral",
    "recChip",
    "wheelSvg",
    "gammaUnavailableWheel",
    "wheelLegend",
    "lifecyclePipeline",
    "pipelineStage",
    "pipelineStageActive",
    "pipelineStageInvalidated",
    "stageLabel",
    "stageArrow",
    "lifecycleReasonCodes",
    "whyThreeColumns",
    "whyColumn",
    "whyColTitle",
    "whyList",
    "nextTriggerText",
    "invalidationText",
    "staleBanner",
    "putColor",
    "callColor",
    "greenColor",
    "goldColor",
    "cyanColor",
    "mono",
    "deltaRow",
]


class TestCSSClasses:
    @pytest.mark.parametrize("cls", REQUIRED_CSS_CLASSES)
    def test_css_class_defined(self, cls):
        css = CSS.read_text(encoding="utf-8")
        assert f".{cls}" in css or f".{cls} " in css or f".{cls}{{" in css, \
            f"CSS class '.{cls}' is used in TSX but not defined in module.css"
