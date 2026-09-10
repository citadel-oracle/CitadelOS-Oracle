"""
Unit & Integration Tests for 21 Probes, SAE, SME, DGP, and 44 Strategy Archetypes.
"""

import json
import pytest
from pathlib import Path

from src.canonical_features.probes import SingleFactorProbeEngine, MANDATORY_PROBES_DEFINITION
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy
from src.strategy_lab.archetypes import StrategyArchetypeRegistry


def test_21_single_factor_probes():
    engine = SingleFactorProbeEngine()
    probes = engine.evaluate_all_probes()
    assert len(probes) == 21
    assert len(MANDATORY_PROBES_DEFINITION) == 21

    probe_ids = set(p.probe_id for p in probes)
    assert len(probe_ids) == 21

    artifact = engine.export_probes_artifact("artifacts/canonical_foundation/single_factor_probes.json")
    assert artifact["total_probes_count"] == 21
    assert Path("artifacts/canonical_foundation/single_factor_probes.json").exists()


def test_strike_attention_engine():
    engine = StrikeAttentionEngine()
    snap = engine.evaluate(atm_strike=24500)
    assert snap.instrument == "NIFTY"
    assert snap.top_strike == 24500
    assert snap.top_strike_score >= 90.0
    assert len(snap.ranked_strikes) == 9
    assert snap.execution_influence == "ZERO"


def test_strike_migration_engine():
    engine = StrikeMigrationEngine()

    # Stationary
    snap1 = engine.evaluate(current_top_strike=24500, previous_top_strike=24500)
    assert snap1.migration_direction == "STATIONARY"
    assert snap1.migration_velocity_pts_per_5m == 0.0

    # Upward migration
    snap2 = engine.evaluate(current_top_strike=24550, previous_top_strike=24500)
    assert snap2.migration_direction == "UPWARD"
    assert snap2.migration_velocity_pts_per_5m == 50.0
    assert snap2.migration_state == "CONTINUATION"


def test_dealer_gamma_pressure_proxy():
    engine = DealerGammaPressureProxy()
    snap = engine.evaluate(spot_price=24510.0, atm_strike=24500)
    assert snap.gamma_pin_strike == 24500
    assert snap.pin_proximity_pts == 10.0
    assert snap.proxy_confidence == "INFERRED_PROXY"
    assert "never directly observed" in snap.note


def test_44_strategy_archetype_registry():
    registry = StrategyArchetypeRegistry()
    archetypes = registry.list_all()
    assert len(archetypes) == 44

    call_count = len([a for a in archetypes if a.side == "CALL"])
    put_count = len([a for a in archetypes if a.side == "PUT"])
    assert call_count == 22
    assert put_count == 22

    artifact = registry.export_universe_artifact("artifacts/canonical_foundation/strategy_universe_44.json")
    assert artifact["target_universe_count"] == 44
    assert Path("artifacts/canonical_foundation/strategy_universe_44.json").exists()
