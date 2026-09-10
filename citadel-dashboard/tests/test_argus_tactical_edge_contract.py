"""Static frontend contract for the canonical ARGUS PRIME panel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
OPTIONS = (
    ROOT / "src/components/institutional/OptionsStructurePanel.tsx"
).read_text(encoding="utf-8")
COMPONENT = (
    ROOT / "src/components/institutional/ArgusPrimePanel.tsx"
).read_text(encoding="utf-8")
STYLES = (
    ROOT / "src/components/institutional/ArgusPrimePanel.module.css"
).read_text(encoding="utf-8")
FIXTURES = (
    ROOT / "src/app/argus-prime-fixtures/page.tsx"
).read_text(encoding="utf-8")


def test_argus_prime_is_integrated_once_inside_options_structure():
    assert PAGE.count("<ArgusPrimePanel") == 1
    assert PAGE.count("<ArgusTacticalEdgePanel") == 0
    assert PAGE.count("<ArgusWriterDominatedPanel") == 1
    assert "data={argus.data?.data?.tactical_edge}" in PAGE
    assert "isStale={Boolean(argus.error)}" not in PAGE
    assert OPTIONS.index("<ArgusFlowEdge") < OPTIONS.index("{argusWriter}")
    assert OPTIONS.index("{argusWriter}") < OPTIONS.index("{tacticalEdge}")
    assert OPTIONS.index("{tacticalEdge}") < OPTIONS.index("<ContractColumn")


def test_argus_prime_visual_fixtures_are_isolated_and_explicitly_test_only():
    for state in (
        "'call'",
        "'put'",
        "'hold'",
        "'retest-active'",
        "'retest-confirmed'",
        "'gamma-armed'",
    ):
        assert state in FIXTURES
    assert "TEST FIXTURE · ARGUS PRIME" in FIXTURES
    assert "NO PRODUCTION DATA" in FIXTURES
    assert "execution_influence: 'ZERO'" in FIXTURES
    assert "<ArgusPrimePanel data={makeFixture(state)} />" in FIXTURES


def test_prime_renders_only_backend_canonical_projection():
    assert "const prime = data?.argus_prime" in COMPONENT
    assert "fetch(" not in COMPONENT
    assert "axios" not in COMPONENT
    for field in (
        "argus_prime_score",
        "direction",
        "move_state",
        "hero_state",
        "recommended_contract",
        "pressure_price_state",
        "smart_flow_score",
        "wall_outcome_score",
        "reversal_score",
        "gamma_regime_score",
        "gamma_blast_score",
        "source_timestamp",
        "snapshot_id",
    ):
        assert field in COMPONENT


def test_locked_command_surface_is_present():
    for label in (
        "ARGUS PRIME / PROBABLE FLOW",
        "CONFIRMED COMMAND STATE",
        "BUY LEVELS",
        "TACTICAL SUMMARY",
        "LIVE OI PCR",
        "DHAN OPTION CHAIN",
        "ARGUS PRIME SCORE",
        "Money Flow",
        "Wall Outcome",
        "Gamma Proxy",
        "Futures Confirmation",
        "EXPIRY GAMMA BLAST",
        "STRONGEST STRUCTURAL STRIKE",
        "OI MIGRATION",
        "ENHANCED STRIKE SPINE",
        "WHY",
        "RISK SHAPE",
        "FULL QUANT EVIDENCE",
    ):
        assert label in COMPONENT


def test_call_put_hold_visual_contract_and_safety_truth():
    assert "direction === 'CALL'" in COMPONENT
    assert "direction === 'PUT'" in COMPONENT
    assert "styles.hold" in COMPONENT
    assert ".call {" in STYLES
    assert ".put {" in STYLES
    assert ".hold {" in STYLES
    assert "ADVISORY ONLY" in COMPONENT
    assert "EXECUTION INFLUENCE ZERO" in COMPONENT
    assert "prime?.live_pcr" in COMPONENT
    assert "prime?.selected_contract_technicals" in COMPONENT
    assert "prime?.best_strike_stack" in COMPONENT
    assert "prime?.stability" in COMPONENT
    assert "prime?.raw_direction" in COMPONENT
    assert "prime?.retest_status" in COMPONENT
    assert "prime?.invalidation_text" in COMPONENT


def test_fast_read_retest_flow_and_strike_arrow_contract():
    assert "RETEST_CONFIRMED" in COMPONENT
    assert "RETEST_ACTIVE" in COMPONENT
    assert "Canonical trigger unavailable" in COMPONENT
    assert "CALL_BUYING" in COMPONENT
    assert "CALL_WRITING" in COMPONENT
    assert "PUT_BUYING" in COMPONENT
    assert "PUT_WRITING" in COMPONENT
    assert "SHORT_COVERING" in COMPONENT
    assert "LONG_UNWINDING" in COMPONENT
    assert "row.directional_arrow" in COMPONENT
    assert "row.is_strongest_pressure" in COMPONENT
    assert "row.wall_strength" in COMPONENT
    assert ".tacticalSummary" in STYLES
    assert ".buyLevels" in STYLES
    assert ".flowPill" in STYLES
    assert ".strongestRow" in STYLES


def test_responsive_motion_and_overflow_contract():
    assert "overflow-x: auto" in STYLES
    assert "@media (prefers-reduced-motion: reduce)" in STYLES
    assert "@media (max-width: 900px)" in STYLES
    assert "@media (max-width: 680px)" in STYLES
    assert "@keyframes ambientRail" in STYLES
    assert ".haloComet" in STYLES
    assert 'aria-label="ARGUS PRIME advisory intelligence"' in COMPONENT
    assert 'aria-label="ARGUS PRIME strike spine"' in COMPONENT


def test_prime_outcome_instruments_are_canonical_and_hierarchical():
    assert "const outcomes = prime?.outcome_engines ?? {}" in COMPONENT
    assert COMPONENT.count("['call_edge', 'CALL']") == 1
    assert COMPONENT.count("['put_edge', 'PUT']") == 1
    assert COMPONENT.count("['hold_edge', 'HOLD']") == 1
    assert COMPONENT.count("['decay_risk', 'DECAY']") == 1
    assert COMPONENT.count("['big_move', 'BIG MOVE']") == 1
    assert COMPONENT.count("['gamma_blast', 'GAMMA BLAST']") == 1
    assert COMPONENT.count("['reversal', 'REVERSAL']") == 1
    assert COMPONENT.index("className={styles.wheelDeck}") < COMPONENT.index(
        "className={styles.spineCard}"
    )
    assert "RAW {number(prime?.raw_score" in COMPONENT
    assert COMPONENT.count("<TacticalHalo") == 2
    assert "compact />" in COMPONENT
    assert "requestAnimationFrame" not in COMPONENT
    assert "setInterval" not in COMPONENT


def test_semantic_flow_and_velocity_visuals_do_not_use_colour_only():
    for value in (
        "CALL_SHORT_COVERING",
        "PUT_SHORT_COVERING",
        "CALL_LONG_UNWINDING",
        "PUT_LONG_UNWINDING",
        "velocity_arrow",
        "oi_acceleration",
        "load_intensity",
        "wall_condition",
    ):
        assert value in COMPONENT
    assert ".loadRail" in STYLES
    assert ".velocity" in STYLES
    assert ".tacticalHalo" in STYLES
    assert ".haloArc" in STYLES
    assert ".compactHalo" in STYLES


def test_argus_prime_uses_locked_typography_tokens_and_semantic_colours():
    assert '--font-display: "Avenir Next Condensed"' in STYLES
    assert '--font-metric: "JetBrains Mono"' in STYLES
    for token in (
        "--citadel-bg-0",
        "--citadel-panel",
        "--citadel-text",
        "--call-core",
        "--put-core",
        "--hold-core",
        "--gamma-core",
        "--stale-core",
    ):
        assert token in STYLES


def test_buy_levels_pcr_stack_and_ambient_light_are_backend_driven():
    for field in (
        "trend.ema_21_zone",
        "trend.ema_50_zone",
        "trend.supertrend_zone",
        "vob.support_buy_zone",
        "vob.breakout_trigger",
        "pcr.oi_pcr",
        "pcr.change_1m",
        "pcr.change_5m",
        "stack?.migration?.path",
    ):
        assert field in COMPONENT
    assert "edgeLight" in COMPONENT
    assert "requestAnimationFrame" not in COMPONENT
    assert "setInterval" not in COMPONENT


def test_truth_semantics_separate_structure_readiness_and_authorization():
    for value in (
        "STRONGEST STRUCTURAL STRIKE",
        "ATM OBSERVATION",
        "AUTHORIZED CONTRACT NONE",
        "TRADE READINESS",
        "PROVIDER EVENT TIME",
        "CHAIN OBSERVED",
        "Dhan Option Chain + NIFTY Futures",
        "REVERSAL NOT SCORED",
    ):
        assert value in COMPONENT
    assert "VOLUME PCR" not in COMPONENT
    assert "SNAPSHOT <b>" not in COMPONENT
    assert "SOURCE <b>{show(prime?.source_timestamp)" not in COMPONENT
