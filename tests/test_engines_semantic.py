import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.premium_intelligence.regime import PremiumRegimeEngine
from src.premium_intelligence.lead import PremiumLeadEngine
from src.premium_intelligence.sae import StrikeAttentionEngine
from src.premium_intelligence.sme import StrikeMigrationEngine
from src.premium_intelligence.dgp import DealerGammaPressureProxy

class MockStraddle:
    def __init__(self, status="OK", expiry="2026-08-04", atm_strike=24500, straddle_price=200.0, ce_symbol="CE", pe_symbol="PE"):
        self.status = status
        self.expiry = expiry
        self.atm_strike = atm_strike
        self.straddle_price = straddle_price
        self.ce_symbol = ce_symbol
        self.pe_symbol = pe_symbol
        self.velocity = 0.0
        self.acceleration = 0.0
        self.session_high = 200.0
        self.session_low = 200.0
        self.session_range_position_pct = 0.0
        self.expansion_state = "BALANCED"
        self.blockers = []

    def __getattr__(self, item):
        return 0.0

def get_fresh_ts():
    return datetime.now(timezone.utc).isoformat()

def test_pre_valid_synchronized():
    engine = PremiumRegimeEngine()
    ce = {"ltp": 100.0}
    pe = {"ltp": 100.0}
    straddle = MockStraddle()
    snap = engine.evaluate_regime(straddle_res=straddle, ce_leg=ce, pe_leg=pe, source_timestamp=get_fresh_ts())
    assert snap.regime != "NO_DATA"
    assert snap.data_state == "LIVE"

def test_pre_missing_ce():
    engine = PremiumRegimeEngine()
    pe = {"ltp": 100.0}
    straddle = MockStraddle()
    snap = engine.evaluate_regime(straddle_res=straddle, ce_leg=None, pe_leg=pe, source_timestamp=get_fresh_ts())
    assert snap.regime == "NO_DATA"

def test_pre_stale_source():
    engine = PremiumRegimeEngine()
    ce = {"ltp": 100.0}
    pe = {"ltp": 100.0}
    straddle = MockStraddle()
    snap = engine.evaluate_regime(straddle_res=straddle, ce_leg=ce, pe_leg=pe, source_timestamp="2000-01-01T10:00:00Z")
    assert snap.data_state == "STALE"
    assert snap.regime == "STALE"

def test_pli_missing_side():
    engine = PremiumLeadEngine()
    straddle = MockStraddle()
    snap = engine.evaluate_lead(straddle_res=straddle, ce_leg=None, pe_leg={"ltp": 100.0}, source_timestamp=get_fresh_ts())
    assert snap.lead_side == "NO_DATA"

def test_pli_stale_source():
    engine = PremiumLeadEngine()
    straddle = MockStraddle()
    snap = engine.evaluate_lead(straddle_res=straddle, ce_leg={"ltp": 100.0}, pe_leg={"ltp": 100.0}, source_timestamp="2000-01-01T10:00:00Z")
    assert snap.lead_side == "STALE"

def test_sae_missing_ladder():
    engine = StrikeAttentionEngine()
    snap = engine.evaluate(option_chain=[])
    assert snap.top_strike is None

def test_sae_shuffle_invariant():
    engine = StrikeAttentionEngine()
    chain1 = [{"strike": 24500, "volume": 1000}, {"strike": 24600, "volume": 2000}]
    chain2 = [{"strike": 24600, "volume": 2000}, {"strike": 24500, "volume": 1000}]
    snap1 = engine.evaluate(option_chain=chain1)
    snap2 = engine.evaluate(option_chain=chain2)
    assert snap1.top_strike == snap2.top_strike

def test_sme_insufficient_history():
    engine = StrikeMigrationEngine()
    engine._sae_history = []
    snap = engine.evaluate(current_top_strike=24500, previous_top_strike=24500)
    assert snap.migration_state == "INSUFFICIENT_HISTORY"

def test_sme_genuine_migration():
    engine = StrikeMigrationEngine()
    engine.record_sae_snapshot("ts1", 24500, [])
    engine.record_sae_snapshot("ts2", 24600, [])
    snap = engine.evaluate(current_top_strike=24600, previous_top_strike=24500)
    assert snap.migration_direction == "UPWARD"

def test_sme_no_default_strike():
    engine = StrikeMigrationEngine()
    snap = engine.evaluate()
    assert snap.migration_state == "INSUFFICIENT_HISTORY"

def test_dgp_inferred_proxy():
    engine = DealerGammaPressureProxy()
    snap = engine.evaluate(spot_price=24500.0, atm_strike=24500)
    assert snap.proxy_confidence == "INFERRED_PROXY"

def test_dgp_missing_inputs():
    engine = DealerGammaPressureProxy()
    snap = engine.evaluate()
    assert snap.proxy_confidence == "NOT_AVAILABLE"

def test_mutation_synthetic_strike_generation():
    engine = StrikeAttentionEngine()
    snap = engine.evaluate(option_chain=[])
    assert len(snap.ranked_strikes) == 0

def test_mutation_missing_to_zero_conversion():
    engine = PremiumRegimeEngine()
    straddle = MockStraddle(straddle_price=0.0)
    snap = engine.evaluate_regime(straddle_res=straddle, ce_leg=None, pe_leg={"ltp": 100.0}, source_timestamp=get_fresh_ts())
    assert snap.regime == "NO_DATA"
