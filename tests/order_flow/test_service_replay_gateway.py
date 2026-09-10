import ast
import asyncio
import json
import pickle
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.broker.dhan_full_packet import DhanFullPacketDecoder
from src.broker.dhan_time import normalize_dhan_ltt
from src.api.v2_integration import V2DashboardIntegration
from src.oracle.market_data_gateway import MarketDataGateway
from src.oracle import market_data_gateway as gateway_module
from src.order_flow.contracts import DirectionalState
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.replay import OrderFlowReplayHarness
from src.order_flow.routing import basket_from_argus, gateway_instruments
from src.order_flow.service import OrderFlowService

from .helpers import full_packet, identity


class Clock:
    def __init__(self):
        self.value = 1_000_000_000
    def __call__(self):
        self.value += 50_000
        return self.value


def tick(packet, *, generation=1, receive_ns=1_000_000_000):
    value = DhanFullPacketDecoder.decode_packet(packet).to_dict()
    value.update({
        "feed_generation": generation,
        "feed_receive_ns": receive_ns,
        "decode_done_ns": receive_ns + 10_000,
        "receive_wall_utc": "2026-08-07T04:45:00+00:00",
        "transport_gap_count": 0,
    })
    return value


def test_service_baseline_is_truthful_and_execution_zero():
    clock = Clock()
    service = OrderFlowService(clock_ns=clock, wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    service.register_instruments((identity(),))
    result = service.ingest_tick(tick(full_packet(), receive_ns=1_000_000_000))
    assert result.execution_influence == "ZERO"
    assert result.probability is None
    assert result.action_eligible is False
    assert "SIGNED_FLOW_BASELINE_ONLY" in result.action_lock_reasons
    assert result.call_strength + result.put_strength == pytest.approx(100)


def test_startup_restore_rebuilds_flow_pulse_without_recorder_or_listener_side_effects():
    source = OrderFlowService(clock_ns=Clock())
    source.register_instruments((identity(),))
    canonical = source._market_event(tick(full_packet()))
    payload = asdict(canonical)
    payload.update({
        "feed_receive_monotonic_ns": payload.pop("feed_receive_ns"),
        "decode_done_monotonic_ns": payload.pop("decode_done_ns"),
        "ltt_normalized_epoch": payload.pop("exchange_ltt"),
    })
    restored = OrderFlowService(clock_ns=Clock())
    listener_events = []
    restored.subscribe_flow_pulse(lambda kind, value: listener_events.append((kind, value)))
    result = restored.restore_flow_pulse_session([payload])
    projection = restored.latest_projection()
    assert result["status"] == "RESTORED"
    assert result["futures_updates"] == 1
    assert projection["flow_pulse"]["revision"] == 1
    assert projection["flow_pulse"]["semantic"]["market"] != "UNAVAILABLE"
    assert listener_events == []


def test_journal_recovery_freezes_cutoff_and_resumes_from_trusted_checkpoint(tmp_path):
    source = OrderFlowService(clock_ns=Clock())
    source.register_instruments((identity(),))

    def payload(packet, receive_ns):
        canonical = source._market_event(tick(packet, receive_ns=receive_ns))
        value = asdict(canonical)
        value.update({
            "feed_receive_monotonic_ns": value.pop("feed_receive_ns"),
            "decode_done_monotonic_ns": value.pop("decode_done_ns"),
            "ltt_normalized_epoch": value.pop("exchange_ltt"),
        })
        return value

    journal = tmp_path / "2026-08-07.jsonl"
    checkpoint = tmp_path / "flow-pulse.pickle"
    first = json.dumps({"payload": payload(full_packet(volume=1000), 1_000_000_000)}) + "\n"
    second = json.dumps({"payload": payload(full_packet(volume=1010, ltp=99.9), 1_100_000_000)}) + "\n"
    journal.write_text(first)
    frozen_cutoff = journal.stat().st_size
    with journal.open("a") as handle:
        handle.write(second)

    initial = OrderFlowService(clock_ns=Clock())
    result = initial.restore_flow_pulse_journal(
        journal, checkpoint_path=checkpoint, cutoff_bytes=frozen_cutoff,
    )
    assert result["checkpoint_used"] is False
    assert result["journal_records_read"] == 1
    assert result["journal_final_offset"] == frozen_cutoff
    envelope = pickle.loads(checkpoint.read_bytes())
    checkpoint_body = pickle.loads(envelope["body"])
    assert checkpoint_body["format_version"] == 2
    assert checkpoint_body["cutoff"] == frozen_cutoff
    assert checkpoint_body["record_count"] == 1
    assert checkpoint_body["instrument_universe_fingerprint"]
    assert checkpoint_body["source_timestamp"] == "2026-08-07T04:45:00+00:00"

    resumed = OrderFlowService(clock_ns=Clock())
    resumed_result = resumed.restore_flow_pulse_journal(
        journal, checkpoint_path=checkpoint, cutoff_bytes=journal.stat().st_size,
    )
    assert resumed_result["checkpoint_used"] is True
    assert resumed_result["journal_records_read"] == 1
    assert resumed_result["replayed_packets"] == 1
    assert resumed_result["packets"] == 2
    assert resumed_result["recovery_complete"] is True
    assert resumed_result["live_tail_attached"] is True
    assert resumed_result["source_timestamp"] == "2026-08-07T04:45:00+00:00"
    assert (tmp_path / "flow-pulse.pickle.recovery.json").exists()


def test_checkpoint_accepts_only_runtime_topology_fingerprint_change(tmp_path):
    """A lifecycle/isolation edit must not force a full same-revision replay."""
    source = OrderFlowService(clock_ns=Clock())
    source.register_instruments((identity(),))
    canonical = source._market_event(tick(full_packet()))
    payload = asdict(canonical)
    payload.update({
        "feed_receive_monotonic_ns": payload.pop("feed_receive_ns"),
        "decode_done_monotonic_ns": payload.pop("decode_done_ns"),
        "ltt_normalized_epoch": payload.pop("exchange_ltt"),
    })
    journal = tmp_path / "2026-08-07.jsonl"
    checkpoint = tmp_path / "flow-pulse.pickle"
    journal.write_text(json.dumps({"payload": payload}) + "\n")
    before = {
        "git_head": "same-revision",
        "git_branch": "same-branch",
        "code_fingerprint": "runtime-topology-before",
    }
    after = {**before, "code_fingerprint": "runtime-topology-after"}

    source.restore_flow_pulse_journal(
        journal, checkpoint_path=checkpoint, checkpoint_identity=before,
    )
    resumed = OrderFlowService(clock_ns=Clock())
    result = resumed.restore_flow_pulse_journal(
        journal, checkpoint_path=checkpoint, checkpoint_identity=after,
    )

    assert result["checkpoint_used"] is True
    assert result["checkpoint_compatibility"] == "COMPATIBLE_FLOW_SEMANTICS_RUNTIME_TOPOLOGY_CHANGED"
    assert result["journal_records_read"] == 0


def test_corrupt_checkpoint_falls_back_to_bounded_replay_with_visible_reason(tmp_path):
    source = OrderFlowService(clock_ns=Clock())
    source.register_instruments((identity(),))
    canonical = source._market_event(tick(full_packet()))
    payload = asdict(canonical)
    payload.update({
        "feed_receive_monotonic_ns": payload.pop("feed_receive_ns"),
        "decode_done_monotonic_ns": payload.pop("decode_done_ns"),
        "ltt_normalized_epoch": payload.pop("exchange_ltt"),
    })
    journal = tmp_path / "2026-08-07.jsonl"
    checkpoint = tmp_path / "flow-pulse.pickle"
    journal.write_text(json.dumps({"payload": payload}) + "\n")
    checkpoint.write_bytes(b"corrupt")

    restored = OrderFlowService(clock_ns=Clock())
    result = restored.restore_flow_pulse_journal(journal, checkpoint_path=checkpoint)

    assert result["status"] == "RESTORED"
    assert result["checkpoint_used"] is False
    assert result["checkpoint_compatibility"] != "COMPATIBLE"
    assert result["records_replayed"] == 1


def test_checkpoint_remains_usable_when_live_basket_rolls(tmp_path):
    source = OrderFlowService(clock_ns=Clock())
    source.register_instruments((identity(),))
    canonical = source._market_event(tick(full_packet()))
    payload = asdict(canonical)
    payload.update({
        "feed_receive_monotonic_ns": payload.pop("feed_receive_ns"),
        "decode_done_monotonic_ns": payload.pop("decode_done_ns"),
        "ltt_normalized_epoch": payload.pop("exchange_ltt"),
    })
    journal = tmp_path / "2026-08-07.jsonl"
    checkpoint = tmp_path / "flow-pulse.pickle"
    journal.write_text(json.dumps({"payload": payload}) + "\n")
    source.restore_flow_pulse_journal(journal, checkpoint_path=checkpoint)

    restored = OrderFlowService(clock_ns=Clock())
    restored.register_instruments((identity(security_id="99999"),))
    result = restored.restore_flow_pulse_journal(journal, checkpoint_path=checkpoint)

    assert result["checkpoint_used"] is True
    assert result["checkpoint_universe_status"] == "LIVE_BASKET_DIFFERENT"
    assert result["journal_records_read"] == 0


def test_dhan_ltt_epoch_is_converted_utc_then_ist_exactly_once():
    normalized = normalize_dhan_ltt(
        1786083900, "2026-08-07T06:25:00+00:00"
    )
    assert normalized.raw_epoch == 1786083900
    assert normalized.normalized_epoch == 1786083900
    assert normalized.utc.isoformat() == "2026-08-07T06:25:00+00:00"
    assert normalized.ist.isoformat() == "2026-08-07T11:55:00+05:30"
    assert normalized.receive_ist.isoformat() == "2026-08-07T11:55:00+05:30"
    assert normalized.receive_skew_ms == 0.0
    assert normalized.receive_time_substituted is False
    assert normalized.session_accepted is True


def test_dhan_ltt_suspicious_raw_value_uses_receive_time_without_fixed_offset():
    normalized = normalize_dhan_ltt(
        1786368294, "2026-08-10T07:54:54+00:00"
    )
    assert normalized.raw_utc.isoformat() == "2026-08-10T13:24:54+00:00"
    assert normalized.raw_ist.isoformat() == "2026-08-10T18:54:54+05:30"
    assert normalized.raw_receive_skew_ms == 19_800_000.0
    assert normalized.normalized_epoch == 1786348494
    assert normalized.utc.isoformat() == "2026-08-10T07:54:54+00:00"
    assert normalized.ist.isoformat() == "2026-08-10T13:24:54+05:30"
    assert normalized.receive_skew_ms == 0.0
    assert normalized.raw_ltt_suspicious is True
    assert normalized.receive_time_substituted is True
    assert normalized.session_accepted is True
    assert normalized.event_session_accepted is True


def test_dhan_ltt_suspicious_nonstandard_skew_also_uses_receive_time_not_offset():
    normalized = normalize_dhan_ltt(
        1786366494, "2026-08-10T07:54:54+00:00"
    )
    assert normalized.raw_receive_skew_ms == 18_000_000.0
    assert normalized.normalized_epoch == 1786348494
    assert normalized.raw_ltt_suspicious is True
    assert normalized.receive_time_substituted is True


def test_service_duplicate_event_exactly_once():
    service = OrderFlowService(clock_ns=Clock(), wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    service.register_instruments((identity(),))
    value = tick(full_packet())
    first = service.ingest_tick(value)
    second = service.ingest_tick(value)
    assert second.snapshot_id == first.snapshot_id
    assert service.duplicates_suppressed == 1


def test_service_maps_single_directional_core_to_symmetric_strengths():
    service = OrderFlowService(clock_ns=Clock(), wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    service.register_instruments((identity(),))
    service.ingest_tick(tick(full_packet(volume=1000, bid_qty=300, ask_qty=700)))
    result = service.ingest_tick(tick(full_packet(volume=1050, ltq=50, ltt=1786083901, ltp=100.0, bid_qty=800, ask_qty=250), receive_ns=1_001_000_000))
    assert result.call_strength == pytest.approx(50 + 50 * result.directional_score)
    assert result.put_strength == pytest.approx(50 - 50 * result.directional_score)
    assert result.directional_state in {DirectionalState.CALL, DirectionalState.NEUTRAL}


def test_transport_gap_degrades_and_locks_action():
    service = OrderFlowService(clock_ns=Clock(), wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    service.register_instruments((identity(),))
    value = tick(full_packet())
    value["transport_gap_count"] = 1
    result = service.ingest_tick(value)
    assert result.action_eligible is False


def test_stale_futures_evidence_is_zero_weight_and_data_locked():
    clock = Clock()
    service = OrderFlowService(clock_ns=clock, wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    service.register_instruments((identity(), identity("2", "ATM_CE", "CE", 24500)))
    service.ingest_tick(tick(full_packet(security_id=43210), receive_ns=1_000_000_000))
    clock.value = 10_000_000_000
    result = service.ingest_tick(tick(full_packet(security_id=2), receive_ns=10_000_000_000))
    assert result.directional_state is DirectionalState.DATA_LOCKED
    assert result.directional_score == 0
    assert "FUTURES_FULL_PACKET_STALE" in result.action_lock_reasons


def test_expired_basket_fails_closed():
    clock = Clock()
    service = OrderFlowService(clock_ns=clock, wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc))
    expired = identity()
    from src.order_flow.contracts import InstrumentIdentity
    expired = InstrumentIdentity(expired.exchange_segment, expired.security_id, expired.role, "2020-01-01")
    service.register_instruments((expired,))
    result = service.ingest_tick(tick(full_packet()))
    assert result.directional_state is DirectionalState.DATA_LOCKED
    assert "INSTRUMENT_BASKET_EXPIRED" in result.action_lock_reasons


def test_stale_instrument_basket_fails_closed_without_replacing_identity():
    clock = Clock()
    service = OrderFlowService(
        clock_ns=clock,
        wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc),
    )
    registered = identity()
    service.register_instruments((registered,))
    clock.value = 25_000_000_000
    result = service.ingest_tick(tick(full_packet(), receive_ns=25_000_000_000))
    assert result.directional_state is DirectionalState.DATA_LOCKED
    assert "INSTRUMENT_BASKET_STALE" in result.action_lock_reasons
    assert result.instruments == (registered,)


def test_replay_is_bit_for_bit_deterministic():
    packets = [
        full_packet(volume=1000),
        full_packet(volume=1010, ltt=1786083901, ltq=10),
        full_packet(volume=1025, ltt=1786083902, ltq=15, ltp=100.05, bid=100, ask=100.05),
    ]
    harness = OrderFlowReplayHarness((identity(),))
    first = harness.run(packets)
    second = harness.run(packets)
    assert first["replay_hash"] == second["replay_hash"]
    assert first["projection_hashes"] == second["projection_hashes"]
    assert first["episode_ids"] == second["episode_ids"]


def test_recorder_is_bounded_async_and_idempotent(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=16)
    recorder.start()
    assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": "a"}, "a")
    assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": "a"}, "a")
    recorder.stop()
    rows = recorder.projections.read()
    assert len(rows) == 1
    assert recorder.health()["queue_depth"] == 0


def test_recorder_coalesces_bursts_and_reports_writer_throughput(tmp_path):
    recorder = OrderFlowEvidenceRecorder(
        tmp_path, queue_size=512, batch_size=256, coalesce_ms=5.0
    )
    recorder.start()
    for index in range(256):
        assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": index}, str(index))
    recorder.stop()
    health = recorder.health()
    assert health["queue_depth"] == 0
    assert health["dropped"] == 0
    assert health["writer_rate_per_s"] > 0
    assert health["oldest_queue_age_ms"] == 0


def test_recorder_default_batch_window_reduces_write_amplification_without_loss(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=128)
    recorder.start()
    for index in range(32):
        assert recorder.submit("FLOW_PROJECTION", {"snapshot_id": index}, str(index))
    recorder.stop()
    health = recorder.health()
    assert len(recorder.projections.read()) == 32
    assert health["dropped"] == 0
    assert health["queue_depth"] == 0
    assert health["batching"]["max_age_ms"] == 100.0
    assert health["batching"]["p95_size"] > 1
    assert health["batching"]["last_target"] == 1024
    assert health["batching"]["last_size"] <= health["batching"]["last_target"]


def test_latest_projection_is_cached_and_does_not_wait_for_ingest_lock(monkeypatch):
    service = OrderFlowService(
        clock_ns=Clock(),
        wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc),
    )
    service.register_instruments((identity(),))
    expected = service.ingest_tick(tick(full_packet()))
    locked = Event()
    release = Event()

    def hold_ingest_lock():
        with service._lock:
            locked.set()
            release.wait(1.0)

    holder = Thread(target=hold_ingest_lock)
    holder.start()
    assert locked.wait(0.5)
    monkeypatch.setattr(
        type(expected),
        "to_dict",
        lambda _projection: (_ for _ in ()).throw(AssertionError("reader recomputed projection")),
    )
    started = monotonic()
    latest = service.latest_projection()
    elapsed = monotonic() - started
    release.set()
    holder.join(timeout=1.0)
    assert latest["snapshot_id"] == expected.snapshot_id
    assert elapsed < 0.05


def test_flow_pulse_paper_entry_is_persisted_on_existing_async_episode_stream(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, coalesce_ms=5.0)
    service = OrderFlowService(
        recorder=recorder, clock_ns=Clock(),
        wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc),
    )
    service.register_instruments((identity(), identity("2", "ATM_PE", "PE", 24500)))
    service.start()
    service.ingest_tick(tick(full_packet(volume=1_000), receive_ns=1_000_000_000))
    service.ingest_tick(tick(full_packet(security_id=2, ltt=1786083901, volume=1_100), receive_ns=1_001_000_000))
    service.flow_pulse._episode.update({
        "side": "PE", "state": "EARLY BUY PE", "model": "MODEL 2 · TREND",
        "area": "PDL · 100", "trigger": 100, "invalidation": 101,
        "target_1": 99, "target_2": 98,
    })
    service.ingest_tick(tick(full_packet(ltt=1786083902, volume=1_200), receive_ns=1_002_000_000))
    service.stop()
    paper = [row for row in recorder.episodes.read() if row["event_type"] == "EPISODE_FLOW_PULSE_PAPER_UPDATE"]
    assert len(paper) == 1
    assert paper[0]["payload"]["entry_ask"] == 100.0
    assert paper[0]["payload"]["broker_submission"] is False
    assert recorder.paper_sessions() == ["2026-08-07"]
    [indexed] = recorder.read_paper_session("2026-08-07")
    assert indexed["trade_id"] == paper[0]["payload"]["trade_id"]
    assert indexed["execution_influence"] == "ZERO"
    restarted = OrderFlowService(
        recorder=OrderFlowEvidenceRecorder(tmp_path, coalesce_ms=5.0),
        clock_ns=Clock(),
        wall_clock=lambda: datetime(2026, 8, 7, 5, 0, tzinfo=timezone.utc),
    )
    restarted.start()
    try:
        assert restarted.flow_pulse.paper_trades()[0]["trade_id"] == indexed["trade_id"]
    finally:
        restarted.stop()


def test_recorder_captures_duplicate_safe_full_packet_and_transport_events(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=32)
    recorder.register_instruments((identity(),))
    packet = tick(full_packet(), generation=3, receive_ns=8_000_000_000)
    recorder.start()
    assert recorder.submit_full_packet(packet)
    assert recorder.submit_full_packet(packet)
    assert recorder.submit_transport_event(
        "FEED_RECONNECTED",
        {
            "feed_generation": 3,
            "subscription_revision": 2,
            "transport_gap_count": 0,
            "instrument_count": 11,
            "receive_wall_utc": "2026-08-07T04:45:00+00:00",
        },
    )
    recorder.stop()

    raw_path = tmp_path / "raw_full_packets" / "2026-08-07.jsonl"
    raw_rows = OrderFlowEvidenceRecorder(tmp_path).root  # path contract remains stable
    assert raw_rows == tmp_path
    raw = json.loads(raw_path.read_text(encoding="utf-8").splitlines()[0])
    assert len(raw_path.read_text(encoding="utf-8").splitlines()) == 1
    payload = raw["payload"]
    assert payload["instrument_role"] == "NIFTY_FUTURE"
    assert payload["feed_generation"] == 3
    assert payload["feed_receive_monotonic_ns"] == 8_000_000_000
    assert len(payload["depth_5"]) == 5
    assert payload["packet_fingerprint"]
    transport_path = tmp_path / "transport_events" / "2026-08-07.jsonl"
    transport = json.loads(transport_path.read_text(encoding="utf-8").splitlines()[0])
    assert transport["payload"]["event_type"] == "FEED_RECONNECTED"
    assert recorder.health()["raw_written"] == 2
    assert recorder.health()["transport_written"] == 1


def test_recorder_basket_matches_future_and_atm_plus_minus_two(tmp_path):
    identities = [identity()]
    for offset in (-2, -1, 0, 1, 2):
        for side in ("CE", "PE"):
            identities.append(identity(f"{offset}:{side}", f"ATM{offset:+d}_{side}", side, 24500 + offset * 50))
    recorder = OrderFlowEvidenceRecorder(tmp_path)
    recorder.register_instruments(tuple(identities))
    assert recorder.health()["registered_instruments"] == 11
    assert recorder.health()["capture_output"].endswith("raw_full_packets/YYYY-MM-DD.jsonl")


def test_argus_basket_routes_future_and_atm_plus_minus_two():
    rows = []
    for index, strike in enumerate((24300, 24400, 24500, 24600, 24700)):
        rows.append({
            "strike": strike,
            "ce": {"security_id": 100 + index},
            "pe": {"security_id": 200 + index},
        })
    projection = {"data": {
        "underlying": {"atm_strike": 24500, "expiry": "2026-08-13"},
        "futures": {"security_id": 999, "segment": "NSE_FNO", "expiry": "2026-08-27"},
        "atm_window": rows,
    }}
    basket = basket_from_argus(projection)
    assert len(basket) == 11
    assert basket[0].role == "NIFTY_FUTURE"
    assert {item.role for item in basket if item.option_type == "CE"} == {"ATM-2_CE", "ATM-1_CE", "ATM_CE", "ATM+1_CE", "ATM+2_CE"}
    assert len(gateway_instruments(basket)) == 11


def test_incomplete_basket_fails_closed():
    assert basket_from_argus({"data": {}}) == ()
    assert basket_from_argus(None) == ()


def test_expired_persisted_basket_is_never_used_for_bootstrap():
    projection = {"data": {
        "underlying": {"atm_strike": 24500, "expiry": "2020-01-01"},
        "futures": {"security_id": 999, "segment": "NSE_FNO", "expiry": "2020-01-30"},
        "atm_window": [],
    }}
    assert basket_from_argus(projection) == ()


@pytest.mark.asyncio
async def test_gateway_requests_full_packets_and_chunks_deterministically():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway.ws = AsyncMock()
    gateway.subscribe([{"exchange_segment": "NSE_FNO", "security_id": str(index)} for index in range(101)])
    await gateway._send_subscriptions()
    messages = [json.loads(call.args[0]) for call in gateway.ws.send.call_args_list]
    assert [row["RequestCode"] for row in messages] == [21, 21]
    assert [row["InstrumentCount"] for row in messages] == [100, 1]


@pytest.mark.asyncio
async def test_gateway_pushes_late_basket_without_waiting_for_a_market_message():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway.ws = AsyncMock()
    gateway._is_running = True
    gateway._loop = asyncio.get_running_loop()
    gateway._subscription_event = asyncio.Event()
    gateway._subscription_send_lock = asyncio.Lock()
    watcher = asyncio.create_task(gateway._watch_subscriptions())
    try:
        gateway.subscribe([{"exchange_segment": "NSE_FNO", "security_id": "43210"}])
        await asyncio.wait_for(gateway._subscription_event.wait(), timeout=0.1)
        for _ in range(10):
            if gateway.ws.send.await_count:
                break
            await asyncio.sleep(0)
        messages = [json.loads(call.args[0]) for call in gateway.ws.send.call_args_list]
        assert messages == [{
            "RequestCode": 21,
            "InstrumentCount": 1,
            "InstrumentList": [{"ExchangeSegment": "NSE_FNO", "SecurityId": "43210"}],
        }]
        assert gateway._sent_subscription_revision == gateway._subscription_revision
    finally:
        gateway._is_running = False
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_connection_attempts_are_single_flight():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    active = 0
    maximum = 0

    async def attempt():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1

    gateway._connect_and_run = attempt
    await asyncio.gather(gateway._connect_once(), gateway._connect_once())
    assert maximum == 1
    assert gateway.health()["CONNECTION_ATTEMPTS"] == 2
    assert gateway.health()["CONNECTION_ATTEMPT_ACTIVE"] is False


@pytest.mark.asyncio
async def test_gateway_429_has_bounded_backoff_and_explicit_telemetry():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway._backoff_jitter = lambda delay: delay

    async def rejected():
        raise RuntimeError("server rejected WebSocket connection: HTTP 429")

    async def stop_after_backoff(delay):
        assert delay == gateway.RECONNECT_INITIAL_DELAY_SECONDS
        gateway._is_running = False

    gateway._connect_and_run = rejected
    gateway._sleep = stop_after_backoff
    await gateway.start()
    health = gateway.health()
    assert health["LAST_CONNECT_RESULT"] == "REJECTED_HTTP_429"
    assert health["LAST_CONNECT_HTTP_STATUS"] == 429
    assert health["CONNECTION_ATTEMPTS"] == 1
    assert health["LAST_BACKOFF_MS"] is None
    assert gateway._reconnect_delay == gateway.RECONNECT_INITIAL_DELAY_SECONDS * 2


def test_gateway_success_resets_backoff_and_records_success_timestamp():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway._reconnect_delay = 32.0
    gateway._record_connection_success()
    health = gateway.health()
    assert gateway._reconnect_delay == gateway.RECONNECT_INITIAL_DELAY_SECONDS
    assert health["LAST_CONNECT_RESULT"] == "CONNECTED"
    assert health["LAST_CONNECT_HTTP_STATUS"] is None
    assert health["LAST_SUCCESSFUL_CONNECTION_TS"] is not None


def test_gateway_queue_is_bounded_and_coalesces_quote_only_updates():
    gateway = MarketDataGateway(queue_size=16)
    for index in range(16):
        gateway._enqueue_tick({"exchange_segment": 2, "security_id": str(index), "cumulative_volume": 1})
    gateway._enqueue_tick({"exchange_segment": 2, "security_id": "15", "cumulative_volume": 1})
    assert gateway._tick_queue.qsize() == 16
    assert gateway.health()["queue_capacity"] == 16
    assert gateway.health()["coalesced_quote_updates"] == 1


def test_gateway_health_distinguishes_requested_from_actual_packet_receipt(monkeypatch):
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway.ws = SimpleNamespace(closed=False)
    gateway.subscribe([
        {"exchange_segment": "NSE_FNO", "security_id": "58072", "role": "NIFTY_FUTURE"},
        {"exchange_segment": "NSE_FNO", "security_id": "10001", "role": "ATM_CE"},
    ])
    gateway._sent_instruments = list(gateway.instruments)
    gateway._record_packet_receipt(
        {"exchange_segment": 2, "security_id": "58072", "response_code": 8},
        datetime.now(timezone.utc),
    )
    monkeypatch.setattr(gateway_module, "_nse_market_open", lambda _: True)

    health = gateway.health()

    assert health["ACK_STATUS"] == "NOT_AVAILABLE"
    assert health["EXPECTED_INSTRUMENTS"] == 2
    assert health["REQUESTED_INSTRUMENTS"] == 2
    assert health["SUBSCRIPTION_REVISION"] == 1
    assert health["SENT_SUBSCRIPTION_REVISION"] == -1
    assert health["EVER_RECEIVED_INSTRUMENTS"] == 1
    assert health["FRESH_INSTRUMENTS"] == 1
    assert health["STALE_INSTRUMENTS"] == 1
    assert health["BASKET_HEALTH"] == "PARTIALLY_RECEIVING"
    per_security_id = {row["security_id"]: row for row in health["instruments"]}
    assert per_security_id["58072"]["freshness_state"] == "FRESH"
    assert per_security_id["10001"]["freshness_state"] == "STALE"


def test_gateway_open_socket_without_any_required_packets_is_data_degraded(monkeypatch):
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway.ws = SimpleNamespace(closed=False)
    gateway.subscribe([
        {"exchange_segment": "NSE_FNO", "security_id": "58072", "role": "NIFTY_FUTURE"},
    ])
    gateway._sent_instruments = list(gateway.instruments)
    monkeypatch.setattr(gateway_module, "_nse_market_open", lambda _: True)

    health = gateway.health()

    assert health["WS_CONNECTED"] is True
    assert health["EVER_RECEIVED_INSTRUMENTS"] == 0
    assert health["BASKET_HEALTH"] == "DATA_DEGRADED"


def test_gateway_decodes_concatenated_full_packets():
    gateway = MarketDataGateway(queue_size=32)
    gateway._handle_binary_message(full_packet(security_id=1) + full_packet(security_id=2))
    assert gateway._tick_queue.qsize() == 2
    assert gateway._tick_queue.get_nowait()["security_id"] == "1"
    assert gateway._tick_queue.get_nowait()["security_id"] == "2"


def test_hot_path_has_no_forbidden_dependencies():
    root = Path(__file__).parents[2] / "src" / "order_flow"
    forbidden = {"pandas", "requests", "sqlite3", "duckdb", "pyarrow", "openai"}
    imported = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert not (imported & forbidden)


def test_v2_provider_wiring_is_cache_only_and_frontend_untouched():
    root = Path(__file__).parents[2]
    app_source = (root / "app" / "main.py").read_text(encoding="utf-8")
    v2_source = (root / "src" / "api" / "v2_integration.py").read_text(encoding="utf-8")
    assert "publish_order_flow(" in app_source
    assert "order_flow_service.latest_projection" in app_source
    assert "order_flow_research.latest" in app_source
    assert 'calls["order_flow"]' in v2_source
    for advisory_feed in ('"argus"', '"order_flow"', '"futures_chart"', '"oracle"'):
        assert advisory_feed in v2_source
    assert "OracleWorkspacePanel" not in "\n".join(str(path) for path in (root / "src" / "order_flow").glob("*"))


def test_v2_order_flow_feed_is_explicitly_advisory_and_execution_zero():
    service = V2DashboardIntegration(
        snapshot=lambda: {
            "status": {"health": "HEALTHY"},
            "journal_summary": {},
            "active_trade": None,
            "analytics": {"summary": {}},
            "optimizer": {"suggestions": []},
            "scanner": [],
        },
        order_flow=lambda: {
            "status": "UNAVAILABLE",
            "reason": "ORDER_FLOW_PROJECTION_NOT_READY",
            "execution_influence": "ZERO",
        },
    )
    feed = service.dashboard("NIFTY")["feeds"]["order_flow"]
    assert feed["data"]["execution_influence"] == "ZERO"
    assert feed["meta"]["advisory_only"] is True
    assert feed["meta"]["execution_influence"] == 0


def test_no_order_or_broker_submission_surface():
    service = OrderFlowService()
    assert not hasattr(service, "place_order")
    assert not hasattr(service, "submit_order")
    assert service.execution_influence == "ZERO"
