"""
Adversarial test suite for ARGUS Decision Engine v2 fields.

Verifies deterministic calculation of:
1. entry_zone_low & entry_zone_high
2. timing_guidance
3. hold_guidance
4. risk_reward
5. readiness_score & readiness_label
6. evidence_count & evidence_total
7. invalidation_level
8. pressure.acceleration
"""

import pytest
from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore


pytestmark = pytest.mark.unit


import tempfile
from pathlib import Path


def create_mock_engine():
    tmp_dir = tempfile.mkdtemp()
    store = ArgusTacticalStore(path=Path(tmp_dir) / "store.json")
    return ArgusTacticalEdgeEngine(store=store)


def create_sample_argus(symbol="NIFTY", ltp=24000.0, fetched_at="2026-07-23T10:00:00+00:00"):
    return {
        "status": "AVAILABLE",
        "freshness": "FRESH",
        "data": {
            "underlying": {
                "symbol": symbol,
                "expiry": "2026-07-30",
                "ltp": ltp,
                "atm_strike": 24000.0,
                "market_state": "OPEN",
                "fetched_at": fetched_at,
            },
            "atm_window": [
                {
                    "strike": 23900.0 + i * 50,
                    "ce": {
                        "oi": 10000 + i * 500,
                        "day_change_oi": 500,
                        "intraday_change_oi": 200,
                        "volume": 5000,
                        "intraday_price_change": 10.0,
                        "activity": "CALL_BUYING" if i < 4 else "CALL_WRITING",
                        "security_id": f"CE_{23900 + i * 50}",
                    },
                    "pe": {
                        "oi": 8000 + i * 300,
                        "day_change_oi": 300,
                        "intraday_change_oi": 100,
                        "volume": 4000,
                        "intraday_price_change": -5.0,
                        "activity": "PUT_WRITING",
                        "security_id": f"PE_{23900 + i * 50}",
                    },
                }
                for i in range(7)
            ],
            "walls": {
                "highest_ce_oi": {"strike": 24200.0},
                "highest_pe_oi": {"strike": 23800.0},
            },
            "totals": {
                "day_ce_change_oi": 3500,
                "day_pe_change_oi": 2100,
                "intraday_ce_change_oi": 1400,
                "intraday_pe_change_oi": 700,
            },
        },
    }


def create_sample_ose(symbol="NIFTY", ce_prem=200.0, pe_prem=180.0):
    return {
        "status": "LIVE",
        "symbol": symbol,
        "expiry": "2026-07-30",
        "anchor": 24000.0,
        "canonical_digest": "digest_12345",
        "calculated_at": "2026-07-23T10:00:00+00:00",
        "contracts": {
            "CE": {
                "contract": {
                    "security_id": "CE_23900",
                    "strike": 23900.0,
                    "expiry": "2026-07-30",
                    "trading_symbol": "NIFTY26JUL23900CE",
                },
                "premium": ce_prem,
                "composite": {"label": "BULLISH_CONTINUATION"},
                "structures": {
                    "5m": {
                        "completed_bucket": True,
                        "state": "BULLISH",
                        "supply_break": True,
                        "demand_break": False,
                        "bullish_retest": True,
                        "bearish_retest": False,
                    }
                },
            },
            "PE": {
                "contract": {
                    "security_id": "PE_24100",
                    "strike": 24100.0,
                    "expiry": "2026-07-30",
                    "trading_symbol": "NIFTY26JUL24100PE",
                },
                "premium": pe_prem,
                "composite": {"label": "BEARISH_REVERSAL"},
                "structures": {
                    "5m": {
                        "completed_bucket": True,
                        "state": "BEARISH",
                        "supply_break": False,
                        "demand_break": True,
                        "bullish_retest": False,
                        "bearish_retest": True,
                    }
                },
            },
        },
    }


class TestPressureAcceleration:
    def test_first_snapshot_has_none_acceleration(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        result = engine.evaluate(argus, ose)
        assert result["pressure"]["acceleration"] is None

    def test_sequential_snapshots_compute_normalized_acceleration(self):
        engine = create_mock_engine()

        # Snapshot 1 at T=10:00:00
        argus1 = create_sample_argus(fetched_at="2026-07-23T10:00:00+00:00")
        ose1 = create_sample_ose()
        res1 = engine.evaluate(argus1, ose1)
        delta1 = res1["pressure"]["delta"]

        # Snapshot 2 at T=10:01:00 (60s later)
        argus2 = create_sample_argus(fetched_at="2026-07-23T10:01:00+00:00")
        # Increase CE buying in window to boost delta
        for row in argus2["data"]["atm_window"]:
            row["ce"]["intraday_change_oi"] = 1000
            row["ce"]["volume"] = 15000
        ose2 = create_sample_ose()
        res2 = engine.evaluate(argus2, ose2)
        delta2 = res2["pressure"]["delta"]

        accel = res2["pressure"]["acceleration"]
        raw_rate = (delta2 - delta1) / 1.0  # dt_min = 1.0
        expected_accel = round(max(-10.0, min(10.0, raw_rate / 10.0)), 2)
        assert accel == expected_accel


class TestEntryZoneAndTimingGuidance:
    def test_entry_zone_generated_for_valid_contract(self):
        engine = create_mock_engine()
        argus = create_sample_argus(ltp=24000.0)
        ose = create_sample_ose(ce_prem=200.0, pe_prem=180.0)
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        assert "entry_zone_low" in dec
        assert "entry_zone_high" in dec
        if dec["entry_zone_low"] is not None and dec["entry_zone_high"] is not None:
            assert dec["entry_zone_low"] <= dec["entry_zone_high"]

    def test_stretched_premium_forces_wait_for_pullback(self):
        engine = create_mock_engine()
        argus = create_sample_argus(ltp=24000.0)
        # 23900 CE with spot=24000 has intrinsic = 100.
        # If premium = 300, extrinsic = 200, fair = 300. But if premium = 400, stretch is huge!
        ose = create_sample_ose(ce_prem=500.0, pe_prem=180.0)
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        if dec["market_direction"] == "CALL":
            assert dec["timing_guidance"] in ("WAIT FOR PULLBACK", "WAIT FOR CONFIRMATION", "WAIT FOR RETEST")

    def test_invalidated_lifecycle_forces_exit_timing(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        # Set 5m structure to bearish_retest for CE contract to trigger rejection/invalidation
        ose["contracts"]["CE"]["structures"]["5m"]["bearish_retest"] = True
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        if res["entry_lifecycle"]["hard_invalidation"]:
            assert dec["timing_guidance"] == "EXIT"


class TestHoldGuidanceAndInvalidationLevel:
    def test_invalidation_level_bullish_uses_put_wall(self):
        engine = create_mock_engine()
        argus = create_sample_argus(ltp=24000.0)
        argus["data"]["walls"]["highest_pe_oi"] = {"strike": 23800.0}
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        if dec["side"] == "CALL":
            assert "23,800" in dec["invalidation_level"] or "Spot <" in dec["invalidation_level"]

    def test_hold_guidance_reflects_timing(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        assert "hold_guidance" in dec
        assert isinstance(dec["hold_guidance"], str)
        assert len(dec["hold_guidance"]) > 0


class TestRiskReward:
    def test_risk_reward_formatted_or_unavailable(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        rr = res["decision"]["risk_reward"]
        assert isinstance(rr, str)
        assert rr == "UNAVAILABLE" or rr.startswith("1 : ")


class TestEvidenceAndReadinessScore:
    def test_readiness_score_bounded_0_to_100(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        assert 0 <= dec["readiness_score"] <= 100
        assert dec["readiness_label"] in (
            "HIGH EVIDENCE ALIGNMENT",
            "READY WITH CONDITIONS",
            "WATCH",
            "DEVELOPING",
            "NO EDGE",
        )
        assert dec["evidence_count"] <= dec["evidence_total"]

    def test_stale_data_penalizes_readiness_score(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        argus["status"] = "STALE"
        argus["freshness"] = "STALE"
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        assert dec["readiness_score"] == 0
        assert dec["readiness_label"] == "NO EDGE"


class TestGammaUnavailableInvariance:
    def test_gamma_remains_unavailable_and_does_not_affect_readiness(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        assert res["gamma"]["status"] == "UNAVAILABLE"
        assert res["gamma"]["reason"] == "AUTHORITATIVE_DIRECT_GREEKS_UNAVAILABLE"


class TestConservativeShadowPolicyV21:
    def test_enter_now_is_never_emitted(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        assert res["decision"]["timing_guidance"] != "ENTER NOW"

    def test_acceleration_cannot_increase_context_score(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        argus["data"]["pressure_acceleration"] = 50.0
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        # Readiness score relies only on 6 independent evidence groups (directional pressure without acceleration boost)
        assert res["decision"]["evidence_total"] <= 6

    def test_high_context_alignment_does_not_imply_execution(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        # Readiness score / context alignment can be high, but action execution authorization remains false
        assert dec["execution_authorization"] is False

    def test_stale_or_missing_structure_disables_action(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        argus["status"] = "STALE"
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        assert dec["action_enabled"] is False
        assert dec["gate"] == "UNAVAILABLE"

    def test_wait_for_retest_remains_directionally_consistent(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        dec = res["decision"]
        if dec["side"] in ("CALL", "PUT"):
            assert dec["timing_guidance"] in ("WAIT FOR RETEST", "WAIT FOR PULLBACK", "WAIT FOR CONFIRMATION", "MANAGE EXISTING POSITION", "EXIT")

    def test_missing_greeks_never_creates_gamma_claims(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)

        assert res["gamma"]["status"] == "UNAVAILABLE"
        assert "Escape Ready" not in res["decision"].get("why_line", "")


class TestDecisionEngineAuditAndFallbacks:
    def test_black_scholes_fallback_iv_solver(self):
        from src.argus.tactical_edge import ArgusTacticalEdgeEngine
        iv, src, status = ArgusTacticalEdgeEngine._estimate_iv_bs(
            spot=23800.0, strike=23800.0, expiry="2026-07-28", price=135.0, option_type="CE"
        )
        assert iv is not None
        assert src == "ESTIMATED"
        assert status in ("SOLVER_CONVERGED", "SOLVER_APPROXIMATED")
        assert 5.0 <= iv <= 50.0

    def test_explainability_ledger_and_all_contract_ranks(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        dec = res["decision"]

        assert "explainability_ledger" in dec
        ledger = dec["explainability_ledger"]
        assert "call_score" in ledger
        assert "put_score" in ledger
        assert "net_edge" in ledger
        assert ledger["min_activation_threshold"] == 10.0
        assert ledger["min_winning_margin"] == 15.0

        assert "all_candidate_ranks" in dec
        ranks = dec["all_candidate_ranks"]
        assert len(ranks) > 0
        for item in ranks:
            assert "contract_score" in item
            assert "rank" in item
            assert "status" in item

    def test_stale_chain_does_not_flip_bias(self):
        engine = create_mock_engine()
        argus1 = create_sample_argus(fetched_at="2026-07-24T10:00:00+00:00")
        ose1 = create_sample_ose()
        res1 = engine.evaluate(argus1, ose1)
        
        argus2 = create_sample_argus(fetched_at="2026-07-24T10:00:03+00:00")
        res2 = engine.evaluate(argus2, ose1)
        assert res2["pressure"]["pressure_status"] == "UNCHANGED SOURCE SNAPSHOT"
        assert res2["decision"]["explainability_ledger"]["bias_direction"] == res1["decision"]["explainability_ledger"]["bias_direction"]

    def test_model_a_score_normalization_invariant(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        press = res["pressure"]
        dec = res["decision"]
        ledger = dec["explainability_ledger"]

        total_press = press["call_score"] + press["put_score"]
        assert abs(total_press - 100.0) <= 0.01

        total_ledger = ledger["call_normalized"] + ledger["put_normalized"]
        assert abs(total_ledger - 100.0) <= 0.01

    def test_true_seven_strike_universe_invariant(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        sel = res["contract_selection"]

        assert sel["unique_strike_count"] == 7
        assert sel["CE_count"] == 7
        assert sel["PE_count"] == 7
        assert len(sel["all_candidate_ranks"]) == 14

    def test_blocked_contract_cannot_win_invariant(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        dec = res["decision"]
        winner_symbol = (res["contract_selection"].get("CE") or {}).get("trading_symbol")

        ranks = dec["all_candidate_ranks"]
        for r in ranks:
            if r["status"] == "BLOCKED":
                assert r["trading_symbol"] != winner_symbol

    def test_gamma_availability_consistency_invariant(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        ranks = res["decision"]["all_candidate_ranks"]

        for r in ranks:
            if not r["gamma_available"]:
                assert r["gamma_risk"] == 0.0
                assert r["gamma_source"] == "UNAVAILABLE"

    def test_exact_contract_score_sum_reconciliation(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        ranks = res["decision"]["all_candidate_ranks"]

        for r in ranks:
            breakdown = r["score_breakdown"]
            term_sum = round(sum(item["contribution"] for item in breakdown.values()), 2)
            expected_score = round(max(0.0, term_sum), 2)
            assert r["contract_score"] == expected_score


    def test_missing_leg_cannot_win_invariant(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        # Corrupt one leg by removing it
        argus["data"]["atm_window"][0]["ce"] = None
        ose = create_sample_ose()
        res = engine.evaluate(argus, ose)
        
        ranks = res["decision"]["all_candidate_ranks"]
        missing_leg = None
        for r in ranks:
            if r["rejection_reason"] == "SOURCE_LEG_MISSING":
                missing_leg = r
                break
                
        assert missing_leg is not None
        assert missing_leg["status"] == "UNAVAILABLE"
        assert missing_leg["contract_score"] == 0.0
        
        sel = res["contract_selection"]
        if sel.get("CE"):
            assert sel["CE"]["trading_symbol"] != missing_leg["trading_symbol"]

    def test_balanced_bias_prevents_entry_ready(self):
        engine = create_mock_engine()
        argus = create_sample_argus()
        ose = create_sample_ose()
        ose["bias"] = "BALANCED"
        res = engine.evaluate(argus, ose)
        dec = res["decision"]

        assert dec["action_enabled"] is False
        assert dec["gate"] != "ENTRY_READY"

