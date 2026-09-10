from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.oracle_sol.cognitive_event_bridge import (
    CognitiveEventBridge,
    CognitiveEventTrigger,
)
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.contracts import GeminiReview, PrimarySynthesisOutput, QwenObservation
from src.oracle_sol.evidence_gate import EvidenceGate, GateValidationResult
from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
from src.oracle_sol.thesis_graph import ThesisGraph


ROOT = Path(__file__).resolve().parents[2]
RECORDED = Path(__file__).parent / "fixtures"


def _real_snapshot(status: SystemStatus = SystemStatus.HEALTHY) -> SolEvidenceSnapshot:
    raw = json.loads((RECORDED / "bridge_recorded_snapshot_20260904.json").read_text())
    raw["system_status"] = status
    return SolEvidenceSnapshot(**raw)


def _real_events(limit: int = 12) -> list[MarketEvent]:
    rows = []
    with (RECORDED / "bridge_recorded_events_20260904.jsonl").open() as stream:
        for line in stream:
            if not line.strip():
                continue
            raw = json.loads(line)
            rows.append(MarketEvent(**raw))
            if len(rows) >= limit:
                break
    return rows


class RecordingCoordinator:
    def __init__(self, block: threading.Event | None = None) -> None:
        self.block = block
        self.entered = threading.Event()
        self.packets = []
        self.sessions = []

    def rollover_session(self, session_id: str) -> None:
        self.sessions.append(session_id)

    def execute_cycle(self, packet, force_full_run=False, acceptance_guard=None):
        self.packets.append(packet)
        self.entered.set()
        if self.block is not None:
            assert self.block.wait(timeout=3.0)
        status = "COMMITTED" if acceptance_guard is None or acceptance_guard(packet) else "STALE_RESULT_NOT_PROMOTED"
        return {
            "cycle": {"status": status, "models_attempted": []},
            "cognitive_live": {},
        }


def _trigger(snapshot, event, revision, generation=0, session="2026-09-04"):
    return CognitiveEventTrigger(
        session_id=session,
        session_generation=generation,
        source_revision=revision,
        evidence_frontier=event.event_id,
        source_event_count=revision,
        snapshot=replace(snapshot, market_session_date=session),
        offered_at_monotonic_ns=time.perf_counter_ns(),
    )


def _bridge(tmp_path, events, coordinator):
    graph = ThesisGraph(storage_path=str(tmp_path / "theses.jsonl"))
    return CognitiveEventBridge(
        event_source=lambda: list(events),
        thesis_graph=graph,
        coordinator=coordinator,
        status_path=None,
    )


def test_current_eligible_event_runs_one_cycle(tmp_path):
    events = _real_events(1)
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[0], 1))
        assert bridge.wait_until_idle()
        assert len(coordinator.packets) == 1
        assert coordinator.packets[0].unseen_event_ids == [events[0].event_id]
    finally:
        bridge.stop()


def test_wait_result_does_not_hide_next_unseen_evidence_frontier(tmp_path):
    """Control-path proof only: not a claim that a model detects opportunities."""
    class WaitingCoordinator(RecordingCoordinator):
        def execute_cycle(self, packet, force_full_run=False, acceptance_guard=None):
            result=super().execute_cycle(packet,force_full_run,acceptance_guard)
            result['cognitive_live']={'current_state':'NO_TRADE','entry_window':'WAIT'}
            return result
    events=_real_events(2)
    coordinator=WaitingCoordinator()
    bridge=_bridge(tmp_path,events,coordinator)
    bridge.start('2026-09-04',0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(),events[0],1))
        assert bridge.wait_until_idle()
        assert bridge.offer(_trigger(_real_snapshot(),events[1],2))
        assert bridge.wait_until_idle()
        assert len(coordinator.packets)==2
        assert events[1].event_id in coordinator.packets[-1].unseen_event_ids
        assert not bridge.offer(_trigger(_real_snapshot(),events[1],2))
    finally:
        bridge.stop()


def test_duplicate_same_trigger_x20_runs_once(tmp_path):
    events = _real_events(1)
    release = threading.Event()
    coordinator = RecordingCoordinator(release)
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        trigger = _trigger(_real_snapshot(), events[0], 1)
        results = [bridge.offer(trigger) for _ in range(20)]
        assert results.count(True) == 1
        release.set()
        assert bridge.wait_until_idle()
        telemetry = bridge.get_telemetry()
        assert telemetry["cycles_started"] == 1
        assert telemetry["duplicate_triggers_suppressed"] == 19
    finally:
        release.set()
        bridge.stop()


def test_latest_pending_coalesces_with_complete_cursor_to_frontier_ids(tmp_path):
    events = _real_events(3)
    release = threading.Event()
    coordinator = RecordingCoordinator(release)
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[0], 1))
        assert coordinator.entered.wait(timeout=2.0)
        assert bridge.offer(_trigger(_real_snapshot(), events[1], 2))
        assert bridge.offer(_trigger(_real_snapshot(), events[2], 3))
        release.set()
        assert bridge.wait_until_idle()
        assert len(coordinator.packets) == 2
        assert coordinator.packets[-1].unseen_event_ids == [event.event_id for event in events]
        telemetry = bridge.get_telemetry()
        assert telemetry["coalesced_triggers"] == 1
        assert telemetry["maximum_pending_depth"] == 1
    finally:
        release.set()
        bridge.stop()


def test_out_of_order_source_trigger_cannot_replace_newer_pending_frontier(tmp_path):
    events = _real_events(3)
    release = threading.Event()
    coordinator = RecordingCoordinator(release)
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[0], 1))
        assert coordinator.entered.wait(timeout=2.0)
        assert bridge.offer(_trigger(_real_snapshot(), events[2], 3))
        assert not bridge.offer(_trigger(_real_snapshot(), events[1], 2))
        release.set()
        assert bridge.wait_until_idle()
        assert coordinator.packets[-1].unseen_event_ids[-1] == events[2].event_id
        telemetry = bridge.get_telemetry()
        assert telemetry["last_seen_source_revision"] == 3
        assert telemetry["last_seen_evidence_frontier"] == events[2].event_id
        assert telemetry["stale_source_triggers_rejected"] == 1
    finally:
        release.set()
        bridge.stop()


def test_market_closed_is_healthy_off_market_without_cycle(tmp_path):
    events = _real_events(1)
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert not bridge.offer(_trigger(_real_snapshot(SystemStatus.OFF_MARKET), events[0], 1))
        telemetry = bridge.get_telemetry()
        assert telemetry["bridge_state"] == "RUNNING_OFF_MARKET"
        assert telemetry["cycles_started"] == 0
        assert telemetry["market_closed_rejections"] == 1
    finally:
        bridge.stop()


def test_session_rotation_rejects_old_trigger_and_late_result(tmp_path):
    events = _real_events(2)
    release = threading.Event()
    coordinator = RecordingCoordinator(release)
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 4)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[0], 1, generation=4))
        assert coordinator.entered.wait(timeout=2.0)
        bridge.rotate_session("2026-09-07", 5)
        assert not bridge.offer(_trigger(_real_snapshot(), events[1], 2, generation=4))
        release.set()
        assert bridge.wait_until_idle()
        telemetry = bridge.get_telemetry()
        assert telemetry["current_session_id"] == "2026-09-07"
        assert telemetry["stale_session_triggers_rejected"] == 1
        assert telemetry["stale_results_not_promoted"] == 1
    finally:
        release.set()
        bridge.stop()


def test_slow_coordinator_does_not_block_event_offers(tmp_path):
    events = _real_events(12)
    release = threading.Event()
    coordinator = RecordingCoordinator(release)
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[0], 1))
        assert coordinator.entered.wait(timeout=2.0)
        durations = []
        for revision, event in enumerate(events[1:], 2):
            started = time.perf_counter()
            bridge.offer(_trigger(_real_snapshot(), event, revision))
            durations.append((time.perf_counter() - started) * 1000.0)
        assert max(durations) < 20.0
        assert bridge.get_telemetry()["pending_depth"] == 1
        release.set()
        assert bridge.wait_until_idle()
        assert bridge.get_telemetry()["cycles_started"] == 2
    finally:
        release.set()
        bridge.stop()


def test_concurrent_start_creates_exactly_one_worker(tmp_path):
    events = _real_events(1)
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, events, coordinator)
    calls = []

    def start():
        calls.append(bridge.start("2026-09-04", 0))

    threads = [threading.Thread(target=start) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert calls.count(True) == 1
        assert sum(
            thread.name == "citadel-cognitive-event-bridge" and thread.is_alive()
            for thread in threading.enumerate()
        ) == 1
    finally:
        bridge.stop()


def test_restart_starts_one_worker_and_does_not_restore_pending_trigger(tmp_path):
    events = _real_events(1)
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, events, coordinator)
    assert bridge.start("2026-09-04", 0)
    bridge.stop()
    assert bridge.start("2026-09-04", 0)
    try:
        telemetry = bridge.get_telemetry()
        assert telemetry["worker_alive"] is True
        assert telemetry["pending_trigger_present"] is False
        assert telemetry["cycle_in_flight"] is False
    finally:
        bridge.stop()


def test_packet_preserves_all_unseen_ids_but_bounds_event_bodies(tmp_path):
    events = _real_events(12)
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, events, coordinator)
    bridge.start("2026-09-04", 0)
    try:
        assert bridge.offer(_trigger(_real_snapshot(), events[-1], 12))
        assert bridge.wait_until_idle()
        packet = coordinator.packets[0]
        assert packet.unseen_event_ids == [event.event_id for event in events]
        assert len(packet.unseen_events_summary) == 5
        assert packet.unseen_events_summary[-1]["event_id"] == events[-1].event_id
        assert not any("vob" in evidence_id.lower() for evidence_id in packet.valid_evidence_ids)
    finally:
        bridge.stop()


class _RateHeaders:
    rate_limits = {}


class _Qwen:
    model_name = "qwen/qwen3.8-27b"
    last_http_status = 200
    backend_adapter = _RateHeaders()

    def __init__(self):
        self.calls = 0

    def observe(self, packet):
        self.calls += 1
        return QwenObservation(
            observed_at=datetime.now(timezone.utc).isoformat(),
            input_revision=packet.revision,
            market_phase="OBSERVED",
            continuation_status="TRANSITION_UNRESOLVED",
            current_side_pressure="UNRESOLVED",
            earliest_contradiction={"summary": "NONE", "evidence_ids": []},
            aggression_price_response="UNRESOLVED",
            call_premium_response="UNRESOLVED",
            put_premium_response="UNRESOLVED",
            reversal_watch={"status": "NONE", "direction": "NONE", "why": "", "evidence_ids": []},
            strongest_new_relationship="NONE",
            status="CURRENT",
            latency_ms=1.0,
        )


class _Gemini:
    model_name = "gemini-3.7-flash"

    def __init__(self):
        self.calls = 0

    def review(self, packet):
        self.calls += 1
        return GeminiReview(
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            input_revision=packet.revision,
            interpretation="UNRESOLVED",
            strongest_agreement="NONE",
            strongest_disagreement="NONE",
            relationship_primary_may_have_missed="NONE",
            reversal_risk="UNKNOWN",
            premium_warning="NONE",
            late_state_warning="NONE",
            status="CURRENT",
            latency_ms=1.0,
        )


class _GPT:
    model_name = "openai/gpt-oss-120b"
    last_http_status = 200
    backend_adapter = _RateHeaders()

    def __init__(self, on_call=None):
        self.calls = 0
        self.on_call = on_call

    def synthesize(self, packet, qwen_obs=None, gemini_rev=None):
        self.calls += 1
        if self.on_call:
            self.on_call()
        return PrimarySynthesisOutput(
            current_state="NO_TRADE",
            setup_family="TRANSITION",
            entry_window="WAIT",
            why_now=["Direction is unclear."],
            reversal_watch={
                "direction": "NONE",
                "status": "NONE",
                "first_contradiction": "NONE",
                "what_failed": "NONE",
                "premium_confirmation": "UNRESOLVED",
                "what_still_opposes": "NONE",
                "why_not_confirmed": "No confirmation.",
                "evidence_ids": [],
            },
            option_buyer_side="UNRESOLVED",
            premium_confirmation="UNRESOLVED",
            what_would_change_my_mind=["New evidence."],
            five_hypotheses={},
            evidence_ids=["metric:spot_price"],
            status="CURRENT",
            input_revision=packet.revision,
            synthesized_at=datetime.now(timezone.utc).isoformat(),
            latency_ms=1.0,
        )


class _GateValidGPT(_GPT):
    def synthesize(self, packet, qwen_obs=None, gemini_rev=None):
        result = super().synthesize(packet, qwen_obs, gemini_rev)
        return replace(
            result,
            why_now=[f"Direction is unclear. {packet.unseen_event_ids[-1]}"],
            evidence_ids=[packet.unseen_event_ids[-1]],
        )


class _Gate:
    def __init__(self):
        self.calls = 0

    def validate_and_commit(self, **kwargs):
        self.calls += 1
        return GateValidationResult(False, "SEMANTIC_CLAIM_REJECTED", "mock rejection")


def _packet_from_real_event():
    event = _real_events(1)[0]
    return __import__(
        "src.oracle_sol.brain_packet_compiler", fromlist=["BrainPacketCompiler"]
    ).BrainPacketCompiler().compile_packet(
        "2026-09-04", 1, _real_snapshot(), None, [event], [], []
    )


def _valid_response_for_recorded_event(packet):
    # This is a commit/lifecycle test, not a price fixture. The mutable session
    # close snapshot can legitimately have no spot. Cite the real attached event
    # rather than claiming missing spot evidence exists.
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response
    return json.loads(json.dumps(make_valid_raw_response()).replace(
        "metric:spot_price", packet.unseen_event_ids[-1]))


def test_stale_on_arrival_skips_evidence_gate_commit():
    current = [True]
    gate = _Gate()
    gpt = _GPT(on_call=lambda: current.__setitem__(0, False))
    coordinator = Phase1CognitiveCoordinator(
        thesis_graph=ThesisGraph(),
        evidence_gate=gate,
        quota_governor=CognitiveQuotaGovernor(),
        qwen_sentinel=_Qwen(),
        gpt_synthesizer=gpt,
        gemini_reviewer=_Gemini(),
    )
    payload = coordinator.execute_cycle(
        _packet_from_real_event(),
        acceptance_guard=lambda _packet: current[0],
    )
    assert payload["cycle"]["status"] == "STALE_RESULT_NOT_PROMOTED"
    assert payload["cycle"]["stage"] == "BEFORE_THESIS_COMMIT"
    assert gate.calls == 0
    assert coordinator.last_committed_thesis is None


def test_evidence_gate_commit_guard_is_immediate_and_cursor_stays_unchanged():
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response

    graph = ThesisGraph()
    packet = _packet_from_real_event()
    result = EvidenceGate(graph).validate_and_commit(
        _valid_response_for_recorded_event(packet),
        packet,
        "mock-model",
        "mock-prompt",
        commit_guard=lambda _packet: False,
    )
    assert result.status == "STALE_RESULT_NOT_PROMOTED"
    assert graph.get_cursor() is None
    assert graph.get_active_thesis() is None


def test_same_session_valid_synthesis_commits_and_advances_cursor_once(tmp_path):
    packet = _packet_from_real_event()
    graph = ThesisGraph(storage_path=str(tmp_path / "theses.jsonl"))
    graph.rollover_session(packet.session_id)
    graph.set_acceptance_frontier(packet.session_id, packet.unseen_event_ids[-1])
    coordinator = Phase1CognitiveCoordinator(
        thesis_graph=graph,
        evidence_gate=EvidenceGate(graph),
        quota_governor=CognitiveQuotaGovernor(),
        qwen_sentinel=_Qwen(),
        gpt_synthesizer=_GateValidGPT(),
        gemini_reviewer=_Gemini(),
    )
    payload = coordinator.execute_cycle(packet)
    assert payload["cycle"]["status"] == "COMMITTED"
    assert graph.get_cursor() == packet.unseen_event_ids[-1]
    assert len(graph.get_history(limit=10)) == 1


def test_atomic_graph_frontier_rejects_stale_commit(tmp_path):
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response

    packet = _packet_from_real_event()
    graph = ThesisGraph(storage_path=str(tmp_path / "theses.jsonl"))
    graph.rollover_session(packet.session_id)
    graph.set_acceptance_frontier(packet.session_id, "evt_newer_frontier")
    result = EvidenceGate(graph).validate_and_commit(
        _valid_response_for_recorded_event(packet),
        packet,
        "mock-model",
        "mock-prompt",
    )
    assert result.status == "STALE_RESULT_NOT_PROMOTED"
    assert graph.get_cursor() is None
    assert graph.get_active_thesis() is None


def test_restart_cursor_suppresses_already_committed_provider_cycle(tmp_path):
    events = _real_events(1)
    graph_path = str(tmp_path / "theses.jsonl")
    packet = _packet_from_real_event()
    graph = ThesisGraph(storage_path=graph_path)
    graph.rollover_session(packet.session_id)
    graph.set_acceptance_frontier(packet.session_id, packet.unseen_event_ids[-1])
    gate = EvidenceGate(graph)
    from tests.oracle_sol.test_phase1_cognitive_architecture import make_valid_raw_response
    assert gate.validate_and_commit(
        _valid_response_for_recorded_event(packet), packet, "mock-model", "mock-prompt"
    ).is_valid

    coordinator = RecordingCoordinator()
    restarted = CognitiveEventBridge(
        event_source=lambda: list(events),
        thesis_graph=ThesisGraph(storage_path=graph_path),
        coordinator=coordinator,
        status_path=None,
    )
    restarted.start("2026-09-04", 0)
    try:
        assert restarted.offer(_trigger(_real_snapshot(), events[0], 1))
        assert restarted.wait_until_idle()
        assert coordinator.packets == []
        telemetry = restarted.get_telemetry()
        assert telemetry["already_committed_triggers_skipped"] == 1
        assert telemetry["cycles_completed"] == 1
    finally:
        restarted.stop()


def test_new_session_rearms_after_old_session_rejection(tmp_path):
    old_event = _real_events(1)[0]
    new_event = replace(
        old_event,
        event_id="evt_20260907_rearm",
        session_date="2026-09-07",
        timestamp_utc="2026-09-07T03:45:01+00:00",
    )
    coordinator = RecordingCoordinator()
    bridge = _bridge(tmp_path, [old_event, new_event], coordinator)
    bridge.start("2026-09-04", 1)
    try:
        bridge.rotate_session("2026-09-07", 2)
        assert not bridge.offer(_trigger(_real_snapshot(), old_event, 1, generation=1))
        assert bridge.offer(
            _trigger(_real_snapshot(), new_event, 2, generation=2, session="2026-09-07")
        )
        assert bridge.wait_until_idle()
        assert coordinator.packets[-1].session_id == "2026-09-07"
        assert coordinator.packets[-1].unseen_event_ids == [new_event.event_id]
    finally:
        bridge.stop()


def test_late_old_session_unavailable_result_cannot_repopulate_coordinator_state():
    entered = threading.Event()
    release = threading.Event()

    class BlockingUnavailableQwen(_Qwen):
        def observe(self, packet):
            entered.set()
            assert release.wait(timeout=3.0)
            return replace(super().observe(packet), status="UNAVAILABLE")

    coordinator = Phase1CognitiveCoordinator(
        thesis_graph=ThesisGraph(),
        evidence_gate=_Gate(),
        quota_governor=CognitiveQuotaGovernor(),
        qwen_sentinel=BlockingUnavailableQwen(),
        gpt_synthesizer=_GPT(),
        gemini_reviewer=_Gemini(),
    )
    packet = _packet_from_real_event()
    coordinator.rollover_session(packet.session_id)
    result = {}

    def run():
        result.update(coordinator.execute_cycle(packet, force_full_run=True))

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=2.0)
    coordinator.rollover_session("2026-09-07")
    release.set()
    worker.join(timeout=3.0)
    assert result["cycle"]["status"] == "STALE_RESULT_NOT_PROMOTED"
    assert coordinator.last_qwen_obs is None
    assert coordinator.last_gemini_rev is None
    assert coordinator.last_synthesis is None
    assert coordinator.thesis_graph.get_active_thesis() is None


def test_shared_groq_quota_budget_bounds_both_models_together(monkeypatch):
    governor = CognitiveQuotaGovernor()
    monkeypatch.setattr("src.oracle_sol.quota_governor.time.time", lambda: 1_000.0)
    for index in range(98):
        model = "qwen" if index % 2 == 0 else "gpt_oss"
        assert governor.can_invoke(model)
        governor.record_call_success(model, 1, 1.0)
    assert not governor.can_invoke("qwen")
    assert not governor.can_invoke("gpt_oss")


def test_full_day_scheduler_dry_run_bounds_qwen_gpt_calls(monkeypatch):
    raw_events = [
        json.loads(line)
        for line in (ROOT / "data/sol_shadow/sol_session_events_2026-09-04.jsonl").read_text().splitlines()
        if line.strip()
    ]
    groups = []
    for raw in raw_events:
        key = "_".join(raw["event_id"].split("_", 2)[:2])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(raw)

    qwen, gpt, gemini, gate = _Qwen(), _GPT(), _Gemini(), _Gate()
    governor = CognitiveQuotaGovernor()
    coordinator = Phase1CognitiveCoordinator(
        thesis_graph=ThesisGraph(),
        evidence_gate=gate,
        quota_governor=governor,
        qwen_sentinel=qwen,
        gpt_synthesizer=gpt,
        gemini_reviewer=gemini,
    )
    packet = _packet_from_real_event()
    clock = [0.0]
    monkeypatch.setattr("src.oracle_sol.freshness_scheduler.time.time", lambda: clock[0])
    monkeypatch.setattr("src.oracle_sol.quota_governor.time.time", lambda: clock[0])

    open_session = False
    cycles = 0
    for revision, (_key, rows) in enumerate(groups, 1):
        for row in rows:
            if row["event_type"] == "DATA_QUALITY_SHIFT":
                after = (row.get("supporting_values") or {}).get("after_status")
                if after in {"HEALTHY", "OFF_MARKET"}:
                    open_session = after == "HEALTHY"
        if not open_session:
            continue
        timestamp = datetime.fromisoformat(rows[-1]["timestamp_utc"].replace("Z", "+00:00"))
        clock[0] = timestamp.timestamp()
        event_ids = [row["event_id"] for row in rows]
        coordinator.execute_cycle(
            replace(
                packet,
                packet_id=f"dry_{revision}",
                revision=revision,
                compiled_at=rows[-1]["timestamp_utc"],
                unseen_event_ids=event_ids,
                unseen_events_summary=[],
                packet_hash=f"dry_hash_{revision}",
            )
        )
        cycles += 1

    # The existing shared Groq bootstrap governor is authoritative until real
    # provider headers are observed; it bounds combined Qwen+GPT calls below 100.
    assert cycles > 0
    assert qwen.calls + gpt.calls <= 98
    assert gemini.calls <= 98
    assert max(qwen.calls, gpt.calls, gemini.calls) < cycles


def test_sol_durable_event_transaction_is_the_only_production_offer_boundary(tmp_path):
    from src.oracle_sol.service import SolMarketBrainService

    class NoProvider:
        configured_model = "mock-disabled"
        model_name = "mock-disabled"
        is_configured = False
        api_key = None

    class BridgeSpy:
        def __init__(self):
            self.observed = []
            self.offers = []

        def observe_market_state(self, snapshot, session_id, generation):
            self.observed.append((snapshot.snapshot_id, session_id, generation))

        def offer(self, trigger):
            self.offers.append(trigger)
            return True

        def rotate_session(self, session_id, generation):
            pass

        def stop(self):
            pass

    service = SolMarketBrainService(
        storage_dir=str(tmp_path / "sol"),
        model_adapter=NoProvider(),
        runtime_mode="TEST",
        cognitive_bridge_enabled=False,
    )
    service.worker.stop()
    spy = BridgeSpy()
    service.cognitive_bridge = spy
    try:
        snapshot = _real_snapshot(SystemStatus.HEALTHY)
        assert service.ingest_snapshot(snapshot) is True
        assert len(spy.observed) == 1
        assert len(spy.offers) == 1
        trigger = spy.offers[0]
        persisted = service.memory.get_all_session_events()
        assert persisted
        assert trigger.evidence_frontier == persisted[-1].event_id
        assert trigger.source_revision == service.memory.get_active_story().story_revision
        assert trigger.snapshot is snapshot

        # A byte-identical canonical snapshot produces no new durable event and
        # therefore no second cognitive offer/provider opportunity.
        assert service.ingest_snapshot(snapshot) is True
        assert len(spy.offers) == 1
    finally:
        service.stop()
