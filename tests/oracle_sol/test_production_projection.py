from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.oracle_sol.event_sourced_memory import EventSourcedMarketMemory
from src.oracle_sol.event_story_builder import MarketEventStoryBuilder
from src.oracle_sol.gemini_adapter import GeminiModelAdapter
from src.oracle_sol.production_projection import project_canonical_oracle_to_sol_feeds
from src.oracle_sol.provenance_guard import ProvenanceGuard
from src.oracle_sol.reasoning_protocol import SolReasoningOrchestrator
from src.oracle_sol.service import SolMarketBrainService
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from src.oracle_sol.thesis_memory import ThesisMemory


FIXTURE = Path(__file__).parent / "fixtures" / "fast_lane_revision_1333.json"


def _recorded_projection() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _project_recorded_frame() -> tuple[dict, object]:
    recorded = _recorded_projection()
    feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=recorded["argus_projection"],
        order_flow_projection=recorded["order_flow_projection"],
        futures_chart_projection=recorded["futures_chart_projection"],
        option_buyer_projection=recorded["option_buyer_projection"],
        transport_health=recorded["transport_health"],
    )
    return recorded, extract_sol_evidence_snapshot(feeds)


def test_real_fast_lane_projection_maps_exact_canonical_values_and_provenance():
    recorded, snapshot = _project_recorded_frame()
    argus = recorded["argus_projection"]["data"]
    flow = recorded["order_flow_projection"]
    chart = recorded["futures_chart_projection"]
    option_intelligence = recorded["option_buyer_projection"]["option_intelligence"]

    assert snapshot.canonical_snapshot_id == flow["snapshot_id"]
    expected_utc = datetime.fromisoformat(
        argus["underlying"]["source_event_time"].replace("Z", "+00:00")
    ).astimezone(timezone.utc).isoformat()
    assert snapshot.timestamp_utc == expected_utc
    assert snapshot.spot_ltp == argus["underlying"]["ltp"]
    assert snapshot.futures_ltp == argus["futures"]["ltp"]
    assert snapshot.futures_basis == argus["futures"]["basis"]
    assert snapshot.futures_security_id == str(argus["futures"]["security_id"])
    assert snapshot.session_vwap == chart["forming_candle"]["vwap"]
    assert snapshot.mlofi_5l == flow["family_values"]["BOOK_PRESSURE"]["mlofi"]
    assert snapshot.atm_iv == option_intelligence["volatility_opportunity"]["atm_iv"]
    assert snapshot.skew_25d == option_intelligence["iv_skew"]["skew_25d_spread"]
    assert snapshot.skew_10d == option_intelligence["iv_skew"]["skew_10d_spread"]
    assert snapshot.zero_gamma_level == option_intelligence["gex"]["zero_gamma_strike"]

    atm_source = argus["atm_window"][1]
    assert snapshot.ce_pricing["security_id"] == atm_source["ce"]["security_id"]
    assert snapshot.ce_pricing["ltp"] == atm_source["ce"]["ltp"]
    assert snapshot.pe_pricing["security_id"] == atm_source["pe"]["security_id"]
    assert snapshot.pe_pricing["ltp"] == atm_source["pe"]["ltp"]
    assert snapshot.strike_ladder[1]["ce_closed_5m_oi"] == -180895.0
    assert snapshot.strike_ladder[1]["pe_closed_5m_oi"] == 547040.0

    sources = snapshot.upstream_source_health["producer_sources"]
    assert sources["order_flow"]["source_id"] == flow["snapshot_id"]
    assert sources["order_flow"]["source_revision"] == flow["revision"]
    assert sources["order_flow"]["source_timestamp"] == flow["generated_at"]
    assert sources["options"]["source_timestamp"] == recorded["option_buyer_projection"]["source_timestamp"]
    assert sources["chart"]["source_timestamp"] == chart["forming_candle"].get("source_timestamp", chart.get("source_timestamp"))
    assert ProvenanceGuard.verify_field_level_allowlist(snapshot.to_dict(), strict=True)


def test_compiler_never_invents_strikes_or_rounds_recorded_levels():
    from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
    _, snapshot = _project_recorded_frame()
    packet = BrainPacketCompiler().compile_packet(snapshot.market_session_date, 1333, snapshot, None, [], [], [])
    expected = {float(value) for value in (snapshot.spot_ltp, snapshot.futures_ltp,
                snapshot.zero_gamma_level, snapshot.session_vwap, snapshot.atm_strike) if value is not None}
    expected.update(float(row["strike"]) for row in snapshot.strike_ladder if row.get("strike") is not None)
    assert set(packet.canonical_levels) == expected
    skew = packet.resolve_evidence("metric:skew_10d")
    assert "10-Delta" in skew["meaning"]
    assert "not 10 days" in skew["limitations"]
    assert skew["unit"] == "IV_PERCENTAGE_POINTS"


def test_invalid_or_naive_source_timestamp_is_not_certified_authentic():
    recorded = _recorded_projection()
    recorded["argus_projection"]["data"]["underlying"]["source_event_time"] = "2026-08-31T10:00:00"
    feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=recorded["argus_projection"],
        order_flow_projection=recorded["order_flow_projection"],
        futures_chart_projection=recorded["futures_chart_projection"],
        option_buyer_projection=recorded["option_buyer_projection"],
        transport_health=recorded["transport_health"],
    )
    snapshot = extract_sol_evidence_snapshot(feeds)
    assert snapshot.timestamp_utc == "2026-08-31T10:00:00"
    assert snapshot.identity_quality == "DEGRADED_INVALID_TIMESTAMP"
    assert snapshot.replay_stable is False
    assert snapshot.system_status.value == "DATA_DEGRADED"


def test_real_projection_preserves_genuinely_absent_or_unit_mismatched_domains():
    _, snapshot = _project_recorded_frame()

    assert snapshot.spot_to_vwap_pts is None
    assert snapshot.current_flow_x is None
    assert snapshot.mlofi_session_extreme is None
    assert snapshot.atm_straddle_price is None
    assert snapshot.straddle_change_5m is None
    assert snapshot.expected_move_pts is None
    assert snapshot.net_gex_inr is None
    assert snapshot.highest_gex_strike is None
    for field in (
        "spot_to_vwap_pts",
        "current_flow_x",
        "mlofi_session_extreme",
        "atm_straddle_price",
        "straddle_change_5m",
        "expected_move_pts",
        "net_gex_inr",
        "highest_gex_strike",
    ):
        assert snapshot.availability_matrix[field] == "UNAVAILABLE"


def test_gemini_reasoning_envelope_contains_the_exact_projected_snapshot(tmp_path: Path):
    _, snapshot = _project_recorded_frame()
    adapter = GeminiModelAdapter(api_key="x")
    orchestrator = SolReasoningOrchestrator(
        model_adapter=adapter,
        thesis_memory=ThesisMemory(storage_dir=str(tmp_path / "thesis")),
        memory=EventSourcedMarketMemory(storage_dir=str(tmp_path / "events")),
    )

    _, beacon, telemetry, envelope = orchestrator.execute_reasoning_cycle(
        snapshot,
        cycle_id="cyc_real_projection_contract",
    )

    envelope_snapshot = envelope.user_payload["snapshot"]
    assert telemetry["real_api_call_occurred"] is False
    assert beacon.market_verdict is None
    assert envelope_snapshot["spot_ltp"] == snapshot.spot_ltp
    assert envelope_snapshot["futures_ltp"] == snapshot.futures_ltp
    assert envelope_snapshot["mlofi_5l"] == snapshot.mlofi_5l
    assert envelope_snapshot["atm_iv"] == snapshot.atm_iv
    assert envelope_snapshot["upstream_source_health"] == snapshot.upstream_source_health


def test_zero_receiving_transport_cannot_make_live_market_snapshot_healthy():
    recorded = _recorded_projection()
    transport = dict(recorded["transport_health"])
    transport["BASKET_HEALTH"] = "DATA_DEGRADED"
    transport["CURRENTLY_RECEIVING_INSTRUMENTS"] = 0
    feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=recorded["argus_projection"],
        order_flow_projection=recorded["order_flow_projection"],
        futures_chart_projection=recorded["futures_chart_projection"],
        option_buyer_projection=recorded["option_buyer_projection"],
        transport_health=transport,
    )

    snapshot = extract_sol_evidence_snapshot(feeds)
    assert snapshot.upstream_source_health["dhan_connected"] is False
    assert snapshot.system_status.value == "UNAVAILABLE"


def _snapshot_with_ce_closed_5m_oi(snapshot, value: float, snapshot_id: str):
    ladder = copy.deepcopy(snapshot.strike_ladder)
    target = next(row for row in ladder if row.get("ce_closed_5m_oi") is not None)
    target["ce_closed_5m_oi"] = value
    return replace(
        snapshot,
        snapshot_id=snapshot_id,
        canonical_snapshot_id=snapshot_id,
        strike_ladder=ladder,
    )


def test_live_float_closed_oi_event_transaction_persists_and_reaches_reasoning(
    tmp_path: Path,
):
    _, recorded_snapshot = _project_recorded_frame()
    # Exact float observations captured from the live 23950 CE failure pair.
    baseline = _snapshot_with_ce_closed_5m_oi(
        recorded_snapshot, -14755.0, "snap_live_float_oi_before"
    )
    current = _snapshot_with_ce_closed_5m_oi(
        recorded_snapshot, 26390.0, "snap_live_float_oi_after"
    )
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=GeminiModelAdapter(api_key="x"),
        runtime_mode="TEST",
    )

    assert service.ingest_snapshot(baseline) is True
    service.worker._queue.join()
    assert service.ingest_snapshot(current) is True
    service.worker._queue.join()

    events = service.memory.get_all_session_events()
    closed_oi_event = next(
        event
        for event in events
        if event.event_type == "CLOSED_OI_DELTA"
        and event.supporting_values.get("after_5m_oi") == 26390.0
    )
    assert closed_oi_event.supporting_values["before_5m_oi"] == -14755.0
    assert closed_oi_event.supporting_values["5m_oi_delta"] == 41145.0
    assert "+41145.0" in closed_oi_event.summary

    persisted_events = (
        tmp_path / f"sol_session_events_{current.market_session_date}.jsonl"
    ).read_text(encoding="utf-8")
    assert closed_oi_event.event_id in persisted_events
    assert service.get_latest_beacon().main_contradiction != "DATA_LINEAGE_CONTAMINATION"

    cycles = service.shadow_ledger.read_recent_cycles(limit=10)
    current_cycle = next(
        cycle for cycle in cycles if cycle["snapshot_id"] == current.snapshot_id
    )
    envelope_snapshot = current_cycle["request_envelope"]["user_payload"]["snapshot"]
    assert envelope_snapshot["strike_ladder"] == current.strike_ladder
    assert current_cycle["status"] == "BLOCKED_NO_API_CREDENTIALS"
    service.worker.stop()


def test_closed_oi_numeric_zero_survives_projection_and_event_persistence(
    tmp_path: Path,
):
    recorded = _recorded_projection()
    original_feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=recorded["argus_projection"],
        order_flow_projection=recorded["order_flow_projection"],
        futures_chart_projection=recorded["futures_chart_projection"],
        option_buyer_projection=recorded["option_buyer_projection"],
        transport_health=recorded["transport_health"],
    )
    baseline = extract_sol_evidence_snapshot(original_feeds)

    zero_recorded = copy.deepcopy(recorded)
    target_sid = next(
        row["ce_security_id"]
        for row in baseline.strike_ladder
        if row.get("ce_closed_5m_oi") is not None
    )
    target_source = next(
        row
        for row in zero_recorded["option_buyer_projection"]["sudden_oi"]["CALL"]["strikes"]
        if str(row.get("security_id")) == str(target_sid)
    )
    target_source["oi_delta_5m"] = 0.0
    zero_feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=zero_recorded["argus_projection"],
        order_flow_projection=zero_recorded["order_flow_projection"],
        futures_chart_projection=zero_recorded["futures_chart_projection"],
        option_buyer_projection=zero_recorded["option_buyer_projection"],
        transport_health=zero_recorded["transport_health"],
    )
    zero_snapshot = extract_sol_evidence_snapshot(zero_feeds)
    zero_row = next(
        row
        for row in zero_snapshot.strike_ladder
        if str(row.get("ce_security_id")) == str(target_sid)
    )
    assert zero_row["ce_closed_5m_oi"] == 0.0

    current = replace(
        zero_snapshot,
        snapshot_id="snap_recorded_zero_closed_oi",
        canonical_snapshot_id="snap_recorded_zero_closed_oi",
    )
    builder = MarketEventStoryBuilder(storage_dir=str(tmp_path))
    builder._current_session_date = baseline.market_session_date
    builder._last_snapshot = baseline
    events = builder.compile_events(current)
    zero_event = next(
        event
        for event in events
        if event.event_type == "CLOSED_OI_DELTA"
        and event.supporting_values.get("after_5m_oi") == 0.0
    )
    memory = EventSourcedMarketMemory(storage_dir=str(tmp_path))
    memory.append_batch(events)

    assert zero_event.supporting_values["after_5m_oi"] == 0.0
    assert "to 0.0" in zero_event.summary
    assert zero_event.event_id in {
        event.event_id for event in memory.get_all_session_events()
    }


def test_recorded_options_oi_domain_is_truthfully_partial(tmp_path: Path):
    _, snapshot = _project_recorded_frame()
    service = SolMarketBrainService(
        storage_dir=str(tmp_path),
        model_adapter=GeminiModelAdapter(api_key="x"),
        runtime_mode="TEST",
    )
    with service._lock:
        service._latest_snapshot = snapshot

    options_oi = service.get_latest_state()["reading_domains"]["options_oi"]

    assert options_oi["status"] == "PARTIAL"
    assert options_oi["option_quotes"] == "AVAILABLE"
    assert options_oi["closed_5m_oi"] == "AVAILABLE"
    assert options_oi["closed_15m_oi"] == "UNAVAILABLE"
    assert options_oi["total_oi"] == "UNAVAILABLE"
    assert options_oi["pcr_oi"] == "UNAVAILABLE"
    service.worker.stop()
