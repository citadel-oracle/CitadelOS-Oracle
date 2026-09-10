"""Comprehensive E2B Atomic Detector Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventType, EventDirection, EventFamily, LifecycleState, AuthorityType
from src.eye.registry import RuleStatus, ProvenanceType
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorAbstentionReason
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.detectors.mtf_coordinator import MultiTimeframeCoordinator
from src.eye.detector_replay import OfflineDetectorReplayHarness
from src.eye.detectors.rule_variants import get_e2b_rule_variants


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def _build_test_bars(prices: list[tuple[float, float, float, float]]):
    t0 = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
    bars = []
    for i, (o, h, l, c) in enumerate(prices):
        t = t0 + timedelta(minutes=5 * i)
        actual_h = max(o, h, c)
        actual_l = min(o, l, c)
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(o * 100)), high=PriceAtom(ticks=int(actual_h * 100)),
            low=PriceAtom(ticks=int(actual_l * 100)), close=PriceAtom(ticks=int(c * 100)), is_closed=True, volume=1000,
        )
        bars.append(bar)
    return bars


# ----------------------------------------------------
# 1. SwingStateDetector Tests
# ----------------------------------------------------

def test_swing_state_causal_confirmation():
    # 5-bar sequence with pivot high at index 2 (24550)
    prices = [
        (24400, 24450, 24390, 24440),
        (24440, 24500, 24430, 24490),
        (24490, 24550, 24480, 24540), # Pivot high at index 2
        (24500, 24510, 24470, 24500), # R1
        (24450, 24480, 24420, 24430), # R2 (Confirms pivot)
    ]
    bars = _build_test_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = SwingStateDetector(left_bars=2, right_bars=2)

    res = detector.detect(bars, ctx)
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.SWING_HIGH
    assert rec.observed_at == bars[2].expected_close_time  # Pivot market time
    assert rec.detected_at == bars[4].expected_close_time  # Right-side confirmation time (NO BACKDATING!)


# ----------------------------------------------------
# 2. StructureBreakDetector Tests
# ----------------------------------------------------

def test_structure_break_bos_bullish():
    prices = [
        (24400, 24450, 24390, 24440),
        (24440, 24500, 24430, 24490),
        (24490, 24550, 24480, 24540), # Swing high
        (24500, 24510, 24470, 24500),
        (24450, 24480, 24420, 24430),
        (24430, 24600, 24430, 24590), # Close break above 24550
    ]
    bars = _build_test_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = StructureBreakDetector(use_close_break=True)

    res = detector.detect(bars, ctx)
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.BOS_BULLISH
    assert rec.payload.primary_level.value == 24550.0


# ----------------------------------------------------
# 3. LiquidityDetector Tests
# ----------------------------------------------------

def test_liquidity_pool_and_sweep():
    prices = [
        (24400, 24500, 24390, 24440), # Touch 1 high = 24500
        (24440, 24480, 24420, 24470),
        (24470, 24500, 24450, 24490), # Touch 2 high = 24500 (Equal Highs Pool!)
        (24470, 24480, 24430, 24460),
        (24460, 24530, 24450, 24480), # Same-bar wick sweep above 24500, close 24480
    ]
    bars = _build_test_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = LiquidityDetector(tolerance_ticks=5)

    res = detector.detect(bars, ctx)
    assert len(res.records) >= 2
    types = [r.event_type for r in res.records]
    assert EventType.LIQUIDITY_POOL_HIGH in types
    assert EventType.LIQUIDITY_SWEEP_HIGH in types


# ----------------------------------------------------
# 4. DisplacementDetector Tests
# ----------------------------------------------------

def test_displacement_expansion():
    prices = [
        (24400, 24420, 24390, 24410),
        (24410, 24550, 24410, 24540), # Large body ratio: body=130, range=140 -> 92%
    ]
    bars = _build_test_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = DisplacementDetector(min_body_ratio=0.7)

    res = detector.detect(bars, ctx)
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.DISPLACEMENT_BULLISH
    assert rec.family == EventFamily.DISPLACEMENT


# ----------------------------------------------------
# 5. FVGClusterDetector Tests
# ----------------------------------------------------

def test_fvg_child_and_aggregate_zones():
    prices = [
        (24400, 24450, 24390, 24440), # Bar 1 high = 24450
        (24440, 24520, 24440, 24510), # Bar 2
        (24510, 24600, 24480, 24590), # Bar 3 low = 24480 (Gap: 24450 - 24480!)
        (24590, 24680, 24560, 24670), # Bar 4 low = 24560 (Second gap!)
    ]
    bars = _build_test_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = FVGClusterDetector()

    res = detector.detect(bars, ctx)
    assert len(res.records) >= 2
    types = [r.event_type for r in res.records]
    assert EventType.FVG_BULLISH in types


# ----------------------------------------------------
# 6. MultiTimeframeCoordinator Tests
# ----------------------------------------------------

def test_mtf_closed_bar_validation():
    coordinator = MultiTimeframeCoordinator()
    bars = _build_test_bars([(24400, 24450, 24390, 24440)])
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[0].expected_close_time)

    # 1 bar is insufficient for 5m HTF completion!
    is_valid, abst = coordinator.validate_htf_completion(bars, "5m", ctx)
    assert is_valid is False
    assert abst.code == DetectorAbstentionReason.INCOMPLETE_HIGHER_TIMEFRAME


# ----------------------------------------------------
# 7. Detector Rule Variants & Authority Safety
# ----------------------------------------------------

def test_e2b_rule_variants_and_authority():
    rules = get_e2b_rule_variants()
    assert len(rules) == 5
    for r in rules:
        assert r.status == RuleStatus.RESEARCH
        assert r.provenance == ProvenanceType.PROPOSED_RESEARCH_VARIANT

    bars = _build_test_bars([(24400, 24450, 24390, 24440)] * 5)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = SwingStateDetector(left_bars=2, right_bars=2)
    res = detector.detect(bars, ctx)
    for rec in res.records:
        assert rec.authority == AuthorityType.OBSERVATION_ONLY
