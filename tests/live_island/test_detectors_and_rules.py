"""Deterministic Unit Tests for Live Island Detectors, Thresholds, Guards, and Adapters."""

import time
import pytest

from src.oracle.live_island.adapters import (
    BuyersWritersAdapter,
    BuildupAdapter,
    GammaBlastAdapter,
    GexAdapter,
    MaxPainAdapter,
)
from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.detectors import IndiaVixDetector, LivePcrDetector
from src.oracle.live_island.guards import SnapshotSuppressionGuard, StableUniverseGuard
from src.oracle.live_island.registry import LiveIslandRegistry


def test_vix_detector_boundary():
    """Verifies VIX triggers only at or above >= 2.0% change."""
    registry = LiveIslandRegistry(vix_min_change_pct=2.0)
    detector = IndiaVixDetector(registry=registry, window_seconds=60.0)

    # Baseline tick: VIX = 14.0
    ev0 = detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.0, "ltt": 1000})
    assert ev0 is None

    # Sub-threshold tick: 14.0 -> 14.27 (+1.928% < 2.0%)
    ev_sub = detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.27, "ltt": 1001})
    assert ev_sub is None

    # Threshold-crossing tick: 14.0 -> 14.29 (+2.071% >= 2.0%)
    ev_super = detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.29, "ltt": 1002})
    assert ev_super is not None
    assert ev_super.id == "vix"
    assert ev_super.numeric_trend == NumericTrend.UP.value
    assert ev_super.event_bias == EventBias.BEARISH.value  # VIX spike is bearish/risk
    assert ev_super.change_percent == pytest.approx(2.07, abs=0.05)


def test_pcr_detector_boundary():
    """Verifies PCR triggers at or above >= 5.0% change."""
    registry = LiveIslandRegistry(pcr_min_change_pct=5.0)
    detector = LivePcrDetector(registry=registry, window_seconds=120.0)

    # Seed baseline: 100k CE, 100k PE -> PCR = 1.00
    detector.on_tick({"instrument_key": "NSE_FO|CE_1", "instrument_type": "CE", "oi": 100_000})
    detector.on_tick({"instrument_key": "NSE_FO|PE_1", "instrument_type": "PE", "oi": 100_000})

    # Sub-threshold: PE rises to 104k (+4.0% < 5.0%)
    ev_sub = detector.on_tick({"instrument_key": "NSE_FO|PE_1", "instrument_type": "PE", "oi": 104_000})
    assert ev_sub is None

    # Threshold-crossing: PE rises to 106k (+6.0% >= 5.0%)
    ev_super = detector.on_tick({"instrument_key": "NSE_FO|PE_1", "instrument_type": "PE", "oi": 106_000})
    assert ev_super is not None
    assert ev_super.id == "pcr"
    assert ev_super.numeric_trend == NumericTrend.UP.value
    assert ev_super.event_bias == EventBias.BULLISH.value  # PCR surge is bullish
    assert float(ev_super.current_value) == pytest.approx(1.06, abs=0.01)


def test_buyers_writers_5pp_boundary():
    """Verifies Buyers/Writers triggers at >= 5.0 percentage points shift."""
    registry = LiveIslandRegistry(buyers_writers_min_change_pp=5.0)
    adapter = BuyersWritersAdapter(registry=registry)

    # Baseline: 50% buyers, 50% writers
    assert adapter.on_dominance_update(50.0, 50.0) is None

    # Sub-threshold: 54.0% (+4.0pp < 5.0pp)
    assert adapter.on_dominance_update(54.0, 46.0) is None

    # Threshold-crossing: 55.5% (+5.5pp >= 5.0pp)
    ev = adapter.on_dominance_update(55.5, 44.5)
    assert ev is not None
    assert ev.id == "buyers_writers"
    assert ev.change_pp == 5.5
    assert ev.numeric_trend == NumericTrend.UP.value
    assert ev.event_bias == EventBias.BULLISH.value


def test_gex_polarity_flip():
    """Verifies GEX polarity flip emits critical event in both directions."""
    adapter = GexAdapter()

    # Initial state: Positive GEX (+50Cr)
    assert adapter.on_gex_update(500_000_000.0) is None

    # Minor variation within same pole: Positive GEX (+60Cr)
    assert adapter.on_gex_update(600_000_000.0) is None

    # Flip to Negative GEX (-20Cr)
    ev_neg = adapter.on_gex_update(-200_000_000.0)
    assert ev_neg is not None
    assert ev_neg.id == "gex"
    assert ev_neg.archetype == ArchetypeType.POLARITY.value
    assert ev_neg.event_bias == EventBias.BEARISH.value
    assert ev_neg.severity == SeverityLevel.CRITICAL.value
    assert ev_neg.archetype_data["prevPole"] == "+GEX"
    assert ev_neg.archetype_data["currPole"] == "-GEX"

    # Flip back to Positive GEX (+10Cr)
    ev_pos = adapter.on_gex_update(100_000_000.0)
    assert ev_pos is not None
    assert ev_pos.event_bias == EventBias.BULLISH.value
    assert ev_pos.archetype_data["prevPole"] == "-GEX"
    assert ev_pos.archetype_data["currPole"] == "+GEX"


def test_stable_universe_guard():
    """Verifies that dropping or adding strikes during ATM rolls does not create artificial jumps."""
    guard = StableUniverseGuard()
    guard.update_universe(["STRIKE_24000", "STRIKE_24050", "STRIKE_24100"])

    baseline_data = {
        "STRIKE_24000": 1000,
        "STRIKE_24050": 2000,
        "STRIKE_24100": 3000,
    }

    # Spot moves up: STRIKE_24000 dropped, STRIKE_24150 added
    current_data = {
        "STRIKE_24050": 2100,
        "STRIKE_24100": 3050,
        "STRIKE_24150": 5000,  # Newly added strike
    }

    curr_intersect, base_intersect, common_count = guard.get_common_intersection(current_data, baseline_data)
    assert common_count == 2
    assert set(curr_intersect.keys()) == {"STRIKE_24050", "STRIKE_24100"}
    assert set(base_intersect.keys()) == {"STRIKE_24050", "STRIKE_24100"}
    assert "STRIKE_24150" not in curr_intersect  # Excluded from delta comparison!


def test_snapshot_suppression_guard():
    """Verifies that snapshot packets or reconnect epochs do not emit market alerts."""
    suppression = SnapshotSuppressionGuard()
    suppression.on_feed_epoch_change(1)
    suppression.set_baseline_ready(False)

    detector = IndiaVixDetector(suppression_guard=suppression)

    # 1. Snapshot packet (is_snapshot = True)
    ev_snap = detector.on_tick({
        "instrument_key": "NSE_INDEX|India VIX",
        "ltp": 25.0,
        "is_snapshot": True,
        "feed_epoch": 1,
    })
    assert ev_snap is None

    # 2. Live packet arriving before BASELINE_READY
    ev_live_early = detector.on_tick({
        "instrument_key": "NSE_INDEX|India VIX",
        "ltp": 25.0,
        "is_snapshot": False,
        "feed_epoch": 1,
    })
    assert ev_live_early is None

    # 3. Once BASELINE_READY, live delta is permitted
    suppression.set_baseline_ready(True)
    detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 20.0, "feed_epoch": 1})
    ev_armed = detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 21.0, "feed_epoch": 1})
    assert ev_armed is not None  # +5% change triggers!


def test_counter_bias_buildup_unsuppressed():
    """Verifies quad-state buildup transitions are emitted faithfully regardless of bias."""
    adapter = BuildupAdapter()

    # Initial state
    assert adapter.on_strike_buildup("24500", "LONG_BUILDUP") is None

    # Strike flips to SHORT_BUILDUP (bearish)
    ev = adapter.on_strike_buildup("24500", "SHORT_BUILDUP")
    assert ev is not None
    assert ev.event_bias == EventBias.BEARISH.value
    assert ev.numeric_trend == NumericTrend.DOWN.value
    assert "SHORT BUILDUP" in ev.current_value
