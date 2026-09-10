from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from time import sleep

from src.api.oracle_fast_lane import OracleFastLane
from src.argus.fusion_eod import FusionShadowEODAnalyzer
from src.argus.fusion_shadow import EXECUTION_INFLUENCE, FUSION_VERSION, FusionShadowEngine
from src.order_flow.recorder import OrderFlowEvidenceRecorder


class Recorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict, str]] = []

    def submit(self, event_type, payload, key):
        self.records.append((event_type, dict(payload), key))
        return True


def flow(*, result="PRICE HOLDING AGAINST SELLERS", what="PRICE HOLDING AGAINST SELLERS", ltp=100.0, quality="GOOD"):
    return {
        "data_quality": quality,
        "directional_state": "DATA_LOCKED" if quality == "UNUSABLE" else "NEUTRAL",
        "flow_pulse": {
            "source_timestamp": "2026-08-12T09:15:00+05:30",
            "futures": {"ltp": ltp, "invalidation": 95.0, "target_1": 105.0, "target_2": 110.0},
            "semantic": {"pressure": "SELLING STRONG", "result": result},
            "reaction": {"state": "SELLERS ABSORBED"},
            "what_happened": what,
            "live_health": {"status": "LIVE"},
        },
    }


def argus(*, ce_bid=9.0, ce_ask=10.0, pe_bid=11.0, pe_ask=12.0, ce_oi=100, pe_oi=100, futures_ltp=None, lot_size=None):
    return {
        "data": {
            "underlying": {
                "atm_strike": 100.0,
                "ltp": 100.0,
                "expiry": "2026-08-18",
                "source_event_time": "2026-08-12T09:15:00+05:30",
                "receipt_timestamp": "2026-08-12T09:15:00+05:30",
            },
            "futures": {"ltp": futures_ltp, "source_timestamp": "2026-08-12T09:15:00+05:30"} if futures_ltp is not None else {},
            "atm_window": [{
                "strike": 100.0,
                "ce": {"security_id": "CE100", "top_bid_price": ce_bid, "top_ask_price": ce_ask, "ltp": (ce_bid + ce_ask) / 2, "oi": ce_oi, "volume": 1000, "lot_size": lot_size},
                "pe": {"security_id": "PE100", "top_bid_price": pe_bid, "top_ask_price": pe_ask, "ltp": (pe_bid + pe_ask) / 2, "oi": pe_oi, "volume": 1000, "lot_size": lot_size},
            }],
        }
    }


def engine(recorder=None):
    return FusionShadowEngine(recorder=recorder, now=lambda: "2026-08-12T09:15:00+05:30")


def test_shadow_is_explicitly_non_authoritative_and_never_creates_a_transport_owner():
    result = engine().projection()
    assert result["fusion_version"] == FUSION_VERSION
    assert result["execution_influence"] == EXECUTION_INFLUENCE == "ZERO"
    assert result["execution_authority"] is False
    assert result["broker_submission"] is False
    assert not hasattr(engine(), "subscribe")


def test_wait_to_watch_emits_once_and_identical_projection_does_not_duplicate_alert_event():
    recorder = Recorder()
    subject = engine(recorder)
    assert subject.ingest_flow(flow())["fusion"]["state"] == "WATCH"
    first = subject.projection()["state_event_id"]
    assert subject.ingest_flow(flow())["fusion"]["state"] == "WATCH"
    assert subject.projection()["state_event_id"] == first
    state_events = [row for row in recorder.records if row[0] == "ARGUS_FUSION_STATE_EVENT"]
    assert len(state_events) == 1


def test_watch_setup_trigger_is_temporal_and_not_a_magic_score_gate():
    subject = engine()
    subject.ingest_flow(flow())
    high_score_without_structure = flow(what="PRICE HOLDING AGAINST SELLERS")
    high_score_without_structure["alignment_score"] = 99
    assert subject.ingest_flow(high_score_without_structure)["fusion"]["state"] == "WATCH"
    assert subject.ingest_flow(flow(what="STRUCTURE RECLAIMED"))["fusion"]["state"] == "SETUP"
    assert subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE"))["fusion"]["state"] == "TRIGGER"


def test_data_locked_blocks_a_new_shadow_trigger_and_preserves_unknown_options():
    subject = engine()
    locked = subject.ingest_flow(flow(quality="UNUSABLE"))
    assert locked["fusion"]["state"] == "DATA_LOCKED"
    assert locked["data_quality"]["lock_reasons"]
    assert locked["fusion"]["evidence"]["options"]["state"] == "UNKNOWN"
    assert subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE", quality="UNUSABLE"))["fusion"]["state"] == "DATA_LOCKED"


def test_missing_flow_is_unknown_not_global_data_locked_when_argus_futures_and_options_are_current():
    subject = engine()
    subject.ingest_argus(argus(futures_ltp=100.0))
    result = subject.ingest_argus(argus(ce_bid=14.0, ce_ask=15.0, pe_bid=8.0, pe_ask=9.0, futures_ltp=101.0))
    assert result["fusion"]["state"] == "WAIT"
    assert result["data_quality"]["state"] == "FUTURES_OPTIONS_LIVE_FLOW_UNKNOWN"
    assert result["fusion"]["evidence"]["flow"]["availability"] == "UNKNOWN"
    assert result["fusion"]["evidence"]["options"]["state"] == "SUPPORTIVE"


def test_explicit_availability_contract_keeps_optional_families_evaluable():
    subject = engine()
    only_futures = subject.ingest_argus(argus(futures_ltp=100.0))
    assert only_futures["fusion"]["state"] == "WAIT"
    assert only_futures["data_quality"]["futures_availability"] == "FRESH"
    assert only_futures["data_quality"]["flow_availability"] == "UNKNOWN"
    assert only_futures["data_quality"]["options_availability"] == "AVAILABLE"

    flow_with_unknown_options = engine().ingest_flow(flow())
    assert flow_with_unknown_options["fusion"]["state"] == "WATCH"
    assert flow_with_unknown_options["data_quality"]["futures_availability"] == "FRESH"
    assert flow_with_unknown_options["data_quality"]["flow_availability"] == "AVAILABLE"
    assert flow_with_unknown_options["data_quality"]["options_availability"] == "UNKNOWN"


def test_stale_authoritative_futures_lock_even_when_other_evidence_exists():
    subject = engine()
    subject.ingest_argus(argus())
    result = subject.ingest_flow(
        flow(),
        transport={
            "instruments": [{"role": "NIFTY_FUTURE", "freshness_state": "STALE"}],
            "BASKET_HEALTH": "DATA_DEGRADED",
        },
    )
    assert result["fusion"]["state"] == "DATA_LOCKED"
    assert result["data_quality"]["futures_availability"] == "STALE"
    assert "FUTURES_PACKET_STALE" in result["data_quality"]["lock_reasons"]


def test_transition_reason_and_missing_evidence_are_observable_without_gating():
    result = engine().ingest_argus(argus(futures_ltp=100.0))
    assert result["fusion"]["transition_reason"] == "NO_MEANINGFUL_TRANSITION_EVIDENCE"
    assert "FLOW_UNKNOWN" in result["fusion"]["transition_blockers"]
    assert "OPTIONS_RESPONSE_UNKNOWN" in result["fusion"]["transition_blockers"]


def test_missing_authoritative_futures_still_locks_with_an_explicit_boundary():
    subject = engine()
    result = subject.ingest_argus(argus())
    assert result["fusion"]["state"] == "DATA_LOCKED"
    assert "FUTURES_NOT_AVAILABLE" in result["data_quality"]["lock_reasons"]


def test_market_closed_retains_last_valid_state_without_claiming_a_new_market_regime():
    subject = engine()
    subject.ingest_flow(flow())
    result = subject.ingest_flow(flow(), transport={"MARKET_SESSION": "CLOSED", "BASKET_HEALTH": "MARKET_CLOSED"})
    assert result["market_closed"] is True
    assert result["data_quality"]["state"] == "MARKET_CLOSED"
    assert result["last_valid_market_state"]["fusion_state"] == "WATCH"


def test_state_anchor_freezes_quotes_and_later_premium_cannot_mutate_its_evidence():
    subject = engine()
    subject.ingest_argus(argus())
    watch = subject.ingest_flow(flow())
    frozen = deepcopy(watch["premium_tracker"]["WATCH"]["state_event"]["state_snapshot"])
    subject.ingest_argus(argus(ce_bid=14.0, ce_ask=15.0, pe_bid=8.0, pe_ask=9.0, ce_oi=90, pe_oi=90))
    latest = subject.projection()
    current_frozen = latest["premium_tracker"]["WATCH"]["state_event"]["state_snapshot"]
    assert current_frozen == frozen
    live_entries = latest["premium_tracker"]["WATCH"]["live"]["entries"]
    assert live_entries["CE100"]["start_ask"] == 10.0
    assert live_entries["CE100"]["live_bid"] == 14.0
    assert live_entries["CE100"]["premium_since_state_percent"] == 40.0


def test_bid_ask_truth_immutable_append_only_trade_and_mfe_mae_r_milestone():
    recorder = Recorder()
    subject = engine(recorder)
    subject.ingest_argus(argus(lot_size=65))
    subject.ingest_flow(flow())
    subject.ingest_flow(flow(what="STRUCTURE RECLAIMED"))
    triggered = subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE", ltp=100.0))
    trade = triggered["today_shadow_trades"][0]
    assert trade["entry"]["ask"] == 10.0
    assert trade["entry"]["bid"] == 9.0
    assert trade["entry"]["truth"] == "ASK_FOR_HYPOTHETICAL_LONG_OPTION"
    assert trade["structural_invalidation"] == 95.0
    subject.ingest_argus(argus(ce_bid=14.0, ce_ask=15.0, pe_bid=8.0, pe_ask=9.0, lot_size=65))
    subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE", ltp=106.0))
    current = subject.projection()["today_shadow_trades"][0]
    assert current["mfe_percent"] == 40.0
    assert current["mae_percent"] == -10.0
    assert current["current_r"] == 1.2
    assert current["shadow_pnl_rupees"] == 260.0
    assert current["r_milestones"]["+1R"] is True
    trade_events = [row for row in recorder.records if row[0].startswith("ARGUS_FUSION_TRADE")]
    assert len(trade_events) >= 2
    assert trade_events[0][1]["event_type"] == "ARGUS_FUSION_TRADE_OPENED"


def test_hero_and_fusion_are_independent_and_two_way_does_not_create_trade():
    subject = engine()
    bullish = flow(result="PRICE RISING WITH BUYERS", what="TREND CONTINUES")
    bullish["flow_pulse"]["semantic"]["pressure"] = "BUYING STRONG"
    bullish["flow_pulse"]["reaction"] = {"state": "BUYERS WORKING"}
    result = subject.ingest_flow(bullish)
    assert result["hero"]["state"] == "STRONG BULL TREND · CONTINUATION"
    assert result["fusion"]["state"] == "WAIT"
    assert result["today_shadow_trades"] == []


def test_eod_analyzer_consumes_append_only_ledger_without_live_engine_access():
    class EodRecorder:
        def read_fusion_session(self, session):
            return [{"event_type": "ARGUS_FUSION_STATE_EVENT", "state_event_id": "one", "to": {"fusion_state": "WATCH", "hero_state": "REVERSAL BUILDING ↑"}}]

        def health(self):
            return {"RECORDER_DROPS": 0}

    report = FusionShadowEODAnalyzer(EodRecorder()).analyze_session("2026-08-12")
    assert report["source"] == "ARGUS_FUSION_SHADOW_APPEND_ONLY_LEDGER"
    assert report["state_counts"]["watch"] == 1
    assert report["execution_influence"] == "ZERO"


def test_eod_analyzer_is_deterministic_for_the_same_append_only_rows():
    class EodRecorder:
        def health(self):
            return {"RECORDER_DROPS": 0}

    rows = [{
        "event_type": "ARGUS_FUSION_STATE_EVENT", "state_event_id": "one",
        "state_timestamp": "2026-08-12T09:15:00+05:30",
        "to": {"fusion_state": "WATCH", "hero_state": "REVERSAL BUILDING ↑"},
    }]
    analyzer = FusionShadowEODAnalyzer(EodRecorder())
    assert analyzer.analyze_rows(rows, session_id="2026-08-12") == analyzer.analyze_rows(rows, session_id="2026-08-12")


def test_options_remain_unknown_until_two_real_snapshots_then_report_only_observed_response():
    subject = engine()
    first = subject.ingest_argus(argus())
    assert first["fusion"]["evidence"]["options"]["state"] == "UNKNOWN"
    second = subject.ingest_argus(argus(ce_bid=14.0, ce_ask=15.0, pe_bid=8.0, pe_ask=9.0, ce_oi=90, pe_oi=110))
    observed = second["fusion"]["evidence"]["options"]
    assert observed["state"] == "SUPPORTIVE"
    assert observed["direction"] == "BULLISH"


def test_watch_setup_trigger_each_gets_a_distinct_frozen_premium_anchor():
    subject = engine()
    subject.ingest_argus(argus())
    subject.ingest_flow(flow())
    subject.ingest_flow(flow(what="STRUCTURE RECLAIMED"))
    subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE"))
    anchors = subject.projection()["premium_tracker"]
    assert set(anchors) == {"WATCH", "SETUP", "TRIGGER"}
    ids = {anchors[name]["state_event"]["state_event_id"] for name in anchors}
    assert len(ids) == 3
    subject.ingest_argus(argus(ce_bid=14.0, ce_ask=15.0, pe_bid=8.0, pe_ask=9.0))
    for name in anchors:
        live = subject.projection()["premium_tracker"][name]["live"]["entries"]
        assert live["CE100"]["live_bid"] == 14.0


def test_invalidated_shadow_trade_is_retained_and_written_as_a_new_append_only_record():
    recorder = Recorder()
    subject = engine(recorder)
    subject.ingest_argus(argus())
    subject.ingest_flow(flow())
    subject.ingest_flow(flow(what="STRUCTURE RECLAIMED"))
    subject.ingest_flow(flow(what="BREAKOUT ACCEPTANCE"))
    original = deepcopy(subject.projection()["today_shadow_trades"][0])
    invalidating = flow(result="PRICE FALLING WITH SELLERS", what="BULLISH INVALIDATED", ltp=94.0)
    subject.ingest_flow(invalidating)
    latest = subject.projection()
    assert latest["fusion"]["state"] == "INVALIDATED"
    assert latest["today_shadow_trades"][0]["trade_id"] == original["trade_id"]
    assert latest["today_shadow_trades"][0]["status"] == "INVALIDATED"
    assert any(event_type == "ARGUS_FUSION_TRADE_UPDATE" for event_type, _, _ in recorder.records)


def test_unknown_structural_levels_remain_research_unknown_not_fake_levels():
    subject = engine()
    subject.ingest_argus(argus())
    no_levels = flow()
    no_levels["flow_pulse"]["futures"].update({"invalidation": None, "target_1": None, "target_2": None})
    subject.ingest_flow(no_levels)
    subject.ingest_flow({**no_levels, "flow_pulse": {**no_levels["flow_pulse"], "what_happened": "STRUCTURE RECLAIMED"}})
    triggered = subject.ingest_flow({**no_levels, "flow_pulse": {**no_levels["flow_pulse"], "what_happened": "BREAKOUT ACCEPTANCE"}})
    trade = triggered["today_shadow_trades"][0]
    assert trade["structural_invalidation"] is None
    assert trade["targets"]["status"] == "UNVALIDATED"
    assert "STRUCTURAL_INVALIDATION_UNVALIDATED" in trade["missing_evidence"]


def test_single_recorder_worker_owns_the_fusion_ledger(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence", coalesce_ms=0.0)
    recorder.start()
    subject = engine(recorder)
    subject.ingest_flow(flow())
    recorder.stop()
    rows = recorder.read_fusion_session("2026-08-12")
    assert len(rows) == 1
    assert rows[0]["event_type"] == "ARGUS_FUSION_STATE_EVENT"
    assert recorder.health()["RECORDER_ALIVE"] is False


def test_restart_replay_cannot_duplicate_the_same_frozen_state_event(tmp_path):
    root = tmp_path / "evidence"
    first = OrderFlowEvidenceRecorder(root, coalesce_ms=0.0)
    first.start()
    engine(first).ingest_flow(flow())
    first.stop()
    second = OrderFlowEvidenceRecorder(root, coalesce_ms=0.0)
    second.start()
    engine(second).ingest_flow(flow())
    second.stop()
    assert len(second.read_fusion_session("2026-08-12")) == 1


def test_fast_lane_publishes_the_same_immutable_fusion_revision_without_engine_recompute():
    subject = engine()
    subject.ingest_flow(flow())
    lane = OracleFastLane(
        base_provider=lambda: {"feeds": {}},
        providers={"fusion_shadow": subject.projection},
        interval_seconds=0.01,
    )
    lane.start()
    try:
        for _ in range(40):
            try:
                body, _ = lane.response()
            except RuntimeError:
                sleep(0.02)
                continue
            snapshot = json.loads(body)
            if "fusion_shadow" in snapshot.get("feeds", {}):
                break
            sleep(0.02)
        else:
            raise AssertionError("fusion feed did not reach Fast Lane")
    finally:
        lane.stop()
    feed = snapshot["feeds"]["fusion_shadow"]
    assert feed["ok"] is True
    assert feed["data"]["state_event_id"] == subject.projection()["state_event_id"]
    assert snapshot["safety"]["execution_influence"] == "ZERO"


def test_replay_reports_every_requested_checkpoint_and_zero_transition_truthfully(tmp_path):
    input_path = tmp_path / "genuine_argus.jsonl"
    output_path = tmp_path / "replay.json"
    rows = []
    for minute in ("13:45", "14:14", "14:17", "14:20", "14:25", "14:29", "14:30", "14:32", "14:54"):
        rows.append({
            "observation_timestamp": f"2026-08-12T{minute}:00+05:30",
            "spot": 24400.0,
            "expiry": "2026-08-18",
            "futures_evidence": {"ltp": 24420.0, "source_timestamp": f"2026-08-12T{minute}:00+05:30"},
            "option_chain_evidence": [{
                "strike": 24400.0,
                "CE": {"security_id": "CE", "bid_price": 10.0, "ask_price": 11.0, "ltp": 10.5, "oi": 100},
                "PE": {"security_id": "PE", "bid_price": 10.0, "ask_price": 11.0, "ltp": 10.5, "oi": 100},
            }],
        })
    input_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/replay_argus_fusion_shadow_v0.py", "--input", str(input_path), "--output", str(output_path)],
        cwd=root, check=True, capture_output=True, text=True,
    )
    assert completed.returncode == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["replay_determinism"] == "PASS"
    assert report["result"]["zero_transitions"] is True
    assert report["replay_state_detection"] == "UNKNOWN"
    assert [row["requested_ist"] for row in report["result"]["forensic_checkpoints"]] == [
        "13:45", "14:14", "14:17", "14:20", "14:25", "14:29", "14:30", "14:32", "14:54",
    ]
    assert report["result"]["premium_counterfactual"]["TRIGGER"]["status"] == "UNKNOWN"
