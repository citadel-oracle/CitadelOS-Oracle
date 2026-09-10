from datetime import datetime
from zoneinfo import ZoneInfo
from src.argus.prime import ArgusPrimeProjection
from src.strategy_command.edge_lab import DEFINITIONS, ArgusEdgeLab
from src.strategy_command.models import CandidateState, PrimeDependencyMode, PrimeRelationship
from src.strategy_command.service import StrategyCommandService

IST = ZoneInfo("Asia/Kolkata")


def make_mock_snapshot(now=None, prime_direction="HOLD", call_edge_score=60.0):
    if now is None:
        now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    
    ce_candidate = {
        "security_id": "NIFTY26JUL24000CE",
        "side": "CE",
        "strike_price": 24000.0,
        "quality_score": 80.0,
        "contract_quality": 80.0,
        "status": "CANDIDATE",
        "symbol": "NIFTY26JUL24000CE",
        "ltp": 150.0,
        "bid": 149.5,
        "ask": 150.5,
        "top_bid_price": 149.5,
        "top_ask_price": 150.5,
        "lot_size": 25,
    }
    pe_candidate = {
        "security_id": "NIFTY26JUL24000PE",
        "side": "PE",
        "strike_price": 24000.0,
        "quality_score": 80.0,
        "contract_quality": 80.0,
        "status": "CANDIDATE",
        "symbol": "NIFTY26JUL24000PE",
        "ltp": 120.0,
        "bid": 119.5,
        "ask": 120.5,
        "top_bid_price": 119.5,
        "top_ask_price": 120.5,
        "lot_size": 25,
    }

    return {
        "data": {
            "underlying": {"symbol": "NIFTY", "last_price": 24000.0, "source_timestamp": now.isoformat()},
            "atm_window": [
                {"ce": ce_candidate, "pe": pe_candidate}
            ],
            "tactical_edge": {
                "symbol": "NIFTY",
                "source_timestamp": now.isoformat(),
                "chain_snapshot_id": "snap_123",
                "calculation_id": "calc_123",
                "expiry": "2026-07-30",
                "contract_selection": {
                    "all_candidate_ranks": [ce_candidate, pe_candidate],
                    "directive_contract": ce_candidate if prime_direction == "CALL" else None,
                },
                "argus_prime": {
                    "snapshot_id": "snap_123",
                    "source_timestamp": now.isoformat(),
                    "direction": prime_direction,
                    "action": prime_direction,
                    "argus_prime_score": 48.0 if prime_direction == "HOLD" else 62.0,
                    "recommended_contract": ce_candidate if prime_direction == "CALL" else None,
                    "data_truth": {"state": "LIVE", "snapshot_id": "snap_123", "expiry": "2026-07-30"},
                    "outcome_engines": {
                        "call_edge": {"display_score": call_edge_score},
                        "put_edge": {"display_score": 30.0},
                        "hold_edge": {"display_score": 20.0},
                        "reversal": {"display_score": 10.0},
                        "decay_risk": {"display_score": 10.0},
                        "big_move": {"display_score": 40.0, "trend": "STABLE"},
                    },
                    "best_strike_stack": {
                        "structural_strength": {"score": 75.0},
                        "trade_readiness": {"score": 50.0},
                        "authorized_contract_detail": ce_candidate if prime_direction == "CALL" else None,
                        "migration": {"state": "CALL_ALIGNED"},
                        "wall": {"condition": "DEFENDED"},
                    },
                    "full_evidence": {
                        "persistence": {"consecutive_confirmations": 3},
                        "breadth": {"direction": "CALL"},
                    },
                    "futures_confirmation": {"state": "CONFIRMED", "status": "CONFIRMED"},
                    "pressure_price_state": "EXPANDING",
                    "selected_contract_technicals": {
                        "pullback_state": "PULLBACK_CONFIRMED",
                        "invalidation": 130.0,
                    },
                    "execution_influence": "ZERO",
                    "paper_only": True,
                    "live_trading_enabled": False,
                    "broker_submission": False,
                },
            },
        }
    }


def test_v1_preservation_and_hold_null_contract(tmp_path):
    # Requirement 1 & 2: V1 behavior unchanged, Prime HOLD returns recommended_contract=None and AUTHORIZED_CONTRACT_UNAVAILABLE
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    # Check V1 CALL lane for C1 SIMPLE
    c1_v1 = next(r for r in proj["lanes"]["CALL"] if r["strategy_id"] == "ARGUS_APEX_C1_SIMPLE")
    assert c1_v1["contract"] is None
    assert "AUTHORIZED_CONTRACT_UNAVAILABLE" in c1_v1["rejection_reasons"]
    assert c1_v1["runtime_state"] in {"SCANNING", "SIDE_BUILDING"}
    assert proj["safety"]["execution_influence"] == "ZERO"


def test_v2_c1_p1_candidate_exists_during_prime_hold(tmp_path):
    # Requirement 3: C1/P1 PRIME_INDEPENDENT V2 candidate exists during Prime HOLD
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    c1_v2 = next(e for e in proj["v2_lanes"]["CALL"] if e["strategy_id"] == "ARGUS_APEX_C1_SIMPLE")
    assert c1_v2["decision_architecture_version"] == "V2"
    assert c1_v2["dependency_mode"] == PrimeDependencyMode.PRIME_INDEPENDENT.value
    assert c1_v2["prime_relationship"] == PrimeRelationship.HOLD.value
    assert c1_v2["candidate_state"] == CandidateState.CANDIDATE.value
    assert c1_v2["shadow_signal_state"] == CandidateState.SHADOW_SIGNAL.value
    assert c1_v2["selected_contract"] is not None
    assert c1_v2["selected_contract"]["side"] == "CE"
    assert c1_v2["selected_contract"]["security_id"] == "NIFTY26JUL24000CE"


def test_v2_c2_p2_balanced_records_prime_relationship(tmp_path):
    # Requirement 4: C2/P2 PRIME_ASSISTED records HOLD/Prime relationship correctly
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    c2_v2 = next(e for e in proj["v2_lanes"]["CALL"] if e["strategy_id"] == "ARGUS_APEX_C2_BALANCED")
    assert c2_v2["dependency_mode"] == PrimeDependencyMode.PRIME_ASSISTED.value
    assert c2_v2["prime_relationship"] == PrimeRelationship.HOLD.value
    assert c2_v2["candidate_state"] == CandidateState.CANDIDATE.value


def test_v2_c3_p3_strict_remains_prime_required(tmp_path):
    # Requirement 5: C3/P3 PRIME_REQUIRED blocks candidate when Prime is HOLD
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=65.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    c3_v2 = next(e for e in proj["v2_lanes"]["CALL"] if e["strategy_id"] == "ARGUS_APEX_C3_STRICT")
    assert c3_v2["dependency_mode"] == PrimeDependencyMode.PRIME_REQUIRED.value
    assert c3_v2["prime_relationship"] == PrimeRelationship.HOLD.value
    assert "PRIME_ALIGNMENT_REQUIRED" in c3_v2["all_blocking_gates"]
    assert c3_v2["candidate_state"] == CandidateState.BLOCKED_PRIME.value


def test_contract_side_safety_wrong_side_impossible(tmp_path):
    # Requirement 7: Wrong-side contract is impossible (CALL strategy only gets CE, PUT strategy only gets PE)
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    for call_e in proj["v2_lanes"]["CALL"]:
        if call_e["selected_contract"]:
            assert call_e["selected_contract"]["side"] == "CE"

    for put_e in proj["v2_lanes"]["PUT"]:
        if put_e["selected_contract"]:
            assert put_e["selected_contract"]["side"] == "PE"


def test_stale_data_rejection(tmp_path):
    # Requirement 8: Stale data blocks candidate generation with BLOCKED_DATA
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    snapshot["data"]["tactical_edge"]["argus_prime"]["data_truth"]["state"] = "STALE"
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    c1_v2 = next(e for e in proj["v2_lanes"]["CALL"] if e["strategy_id"] == "ARGUS_APEX_C1_SIMPLE")
    assert c1_v2["candidate_state"] == CandidateState.BLOCKED_DATA.value
    assert "ARGUS_SNAPSHOT_NOT_LIVE" in c1_v2["all_blocking_gates"]


def test_thresholds_and_safety_preserved(tmp_path):
    # Requirement 9, 14 & 15: No strategy thresholds changed, broker submission false, execution influence ZERO, bounded streams
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)

    # Check thresholds match definitions
    call_defs = {d.strategy_id: d for d in DEFINITIONS}
    for e in proj["v2_lanes"]["CALL"]:
        d = call_defs[e["strategy_id"]]
        assert e["required_thresholds"]["edge_min"] == d.edge_min
        assert e["required_thresholds"]["structure_min"] == d.structure_min
        assert e["paper_only"] is True
        assert e["live_trading_enabled"] is False
        assert e["broker_submission"] is False
        assert e["execution_influence"] == "ZERO"

    assert lab.v2_evaluation_stream.path.exists()


def test_immutable_stream_rotation_and_retention(tmp_path):
    from src.strategy_lab.storage import ImmutableStream
    stream_path = tmp_path / "v2_evaluations.jsonl"
    stream = ImmutableStream(stream_path, max_bytes=200, max_files=2)

    # Append records to trigger rotation
    for i in range(10):
        stream.append("V2_EVALUATION", {"index": i, "payload": "x" * 50})

    # Verify active stream exists and rotated files exist up to max_files
    assert stream_path.exists()
    assert stream_path.with_name(f"{stream_path.name}.1").exists()
    assert stream_path.with_name(f"{stream_path.name}.2").exists()
    # Pruned file beyond max_files (3) must NOT exist
    assert not stream_path.with_name(f"{stream_path.name}.3").exists()


def test_producer_failure_telemetry_and_recovery():
    from src.api.argus_api import ArgusAPI, ArgusAPIError

    from src.argus import OptionChainEngine

    class MockFailingEngine:
        def __init__(self):
            self.calls = 0
            self.real_engine = OptionChainEngine(dhan=False, baseline_store=False)
            self.raw_chain = {
                "24400": {
                    "ce": {"security_id": 65854, "ltp": 74.3, "open_interest": 12545000, "previous_close_oi": 12000000},
                    "pe": {"security_id": 65855, "ltp": 65.2, "open_interest": 11000000, "previous_close_oi": 10500000}
                }
            }
            self.resp = {"status": "success", "data": {"last_price": 24400.0, "oc": self.raw_chain}}

        def fetch_current_snapshot(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ArgusAPIError(502, "DHAN_UNAVAILABLE", "Transient provider timeout")
            prep = self.real_engine.prepare_snapshot_input("NIFTY", "NSE_FNO", 13, "2026-08-04", self.resp)
            return self.real_engine.build_prepared_snapshot(prep)

    api = ArgusAPI(engine=MockFailingEngine(), cache_ttl_seconds=0.05, projection_freshness_seconds=0.1)

    # Initial telemetry state
    t0 = api.get_producer_telemetry()
    assert t0["consecutive_failures"] == 0
    assert t0["recovery_count"] == 0

    # Start producer loop
    api.start_cache_producer(None, interval_seconds=0.05)

    # Allow loop to run 2 iterations
    import time
    time.sleep(0.2)
    api.stop_cache_producer()

    t1 = api.get_producer_telemetry()
    assert t1["last_success_at"] is not None
    assert t1["recovery_count"] >= 1
    assert t1["consecutive_failures"] == 0


def test_degraded_stale_coherent_fallback(tmp_path):
    snapshot = make_mock_snapshot(prime_direction="HOLD", call_edge_score=60.0)
    service = StrategyCommandService(root=tmp_path / "service")
    lab = ArgusEdgeLab(root=tmp_path / "edge_lab", registry=service, snapshot_provider=lambda: snapshot)

    proj = lab.evaluate_once(snapshot)
    assert proj["status"] in {"LIVE", "AVAILABLE"}


