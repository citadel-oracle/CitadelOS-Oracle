from datetime import datetime, timezone

from src.api.v2_integration import V2DashboardIntegration
from src.order_flow.publication import publish_order_flow
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.research import OrderFlowResearchAggregator
from src.order_flow.service import OrderFlowService
from src.oracle_development.oracle_dev_service import OracleDevService

from .helpers import full_packet, identity
from .test_service_replay_gateway import Clock, tick


def test_idle_projection_fails_closed_without_erasing_last_scores():
    clock = Clock()
    service = OrderFlowService(
        clock_ns=clock,
        wall_clock=lambda: datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc),
    )
    service.register_instruments((identity(),))
    projection = service.ingest_tick(tick(full_packet(), receive_ns=1_000_000_000))
    call_score = projection.call_strength
    put_score = projection.put_strength
    clock.value = 25_000_000_000

    latest = service.latest_projection()

    assert latest["projection_state"] == "LAST_GOOD"
    assert latest["directional_state"] == "DATA_LOCKED"
    assert latest["data_quality"] == "UNUSABLE"
    assert latest["action_eligible"] is False
    assert latest["call_strength"] == call_score
    assert latest["put_strength"] == put_score
    assert "FUTURES_FULL_PACKET_STALE" in latest["action_lock_reasons"]


def test_publication_never_authorizes_missing_trade_levels():
    published = publish_order_flow(
        lambda: {
            "snapshot_id": "flow-a",
            "data_quality": "GOOD",
            "directional_state": "CALL",
            "action_eligible": True,
            "action_lock_reasons": [],
            "family_values": {},
            "execution_influence": "ZERO",
        },
        lambda: {"status": "READY", "edge_health": {"maturity": "RESEARCH"}},
    )

    assert published["decision"]["action"] == "WAIT"
    assert published["decision"]["levels_status"] == "UNAVAILABLE"
    assert published["decision"]["contract"] is None
    assert published["decision"]["entry_low"] is None
    assert published["decision"]["invalidation"] is None
    assert published["decision"]["target_1"] is None
    assert published["decision"]["execution_influence"] == "ZERO"
    assert published["diagnostics"]["score_is_probability"] is False


def test_research_aggregates_immutable_stream_and_keeps_outcomes_unknown(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence")
    episode = {
        "episode_id": "episode-a",
        "session_id": "2026-08-07",
        "direction": "CALL",
        "started_at": "2026-08-07T04:45:00+00:00",
        "band_crossings": {60: "t0", 70: "t1"},
        "reversal_states": [{"timestamp": "t1", "state": "STABLE_DIRECTION"}],
        "data_quality": "GOOD",
        "complete": True,
        "final_result": "NEUTRAL_OR_DATA_LOCK",
    }
    recorder.episodes.append("EPISODE_COMPLETED", episode, idempotency_key="completed:episode-a")
    aggregator = OrderFlowResearchAggregator(recorder, tmp_path / "research", interval_seconds=60)

    first = aggregator.aggregate_once()
    second = aggregator.aggregate_once()

    assert first["today"]["completed"] == 1
    assert first["today"]["successful"] is None
    assert first["today"]["failed"] is None
    assert first["shadow_pnl"]["status"] == "NOT_YET_AVAILABLE"
    assert first["edge_health"]["maturity"] == "RESEARCH"
    assert second["today"] == first["today"]
    assert (tmp_path / "research" / "Daily" / "2026-08-07.json").exists()
    assert (tmp_path / "research" / "Validated Learnings.json").exists()


class _NoFetchDhan:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected provider call: {name}")


def test_futures_chart_projection_reuses_cached_candles_and_canonical_vwap(tmp_path):
    now = datetime(2026, 8, 7, 4, 50, tzinfo=timezone.utc)
    service = OracleDevService(
        _NoFetchDhan(), None, None, None, state_root=tmp_path, clock=lambda: now
    )
    service.is_synthetic = False
    service._futures_chart_identity = {
        "contract": "NIFTY-AUG-FUT",
        "security_id": "123",
        "expiry": "2026-08-27",
    }
    service._historical_futures_candles["5m"] = [
        {"time": int(datetime(2026, 8, 7, 4, 45, tzinfo=timezone.utc).timestamp()), "open": 25000.0, "high": 25010.0, "low": 24990.0, "close": 25005.0, "volume": 100},
        {"time": int(datetime(2026, 8, 7, 4, 50, tzinfo=timezone.utc).timestamp()), "open": 25005.0, "high": 25020.0, "low": 25000.0, "close": 25015.0, "volume": 200},
    ]
    service._historical_futures_candles["1m"] = [
        {"time": int(datetime(2026, 8, 7, 4, 49, tzinfo=timezone.utc).timestamp()), "open": 25004.0, "high": 25012.0, "low": 25000.0, "close": 25009.0, "volume": 120},
        {"time": int(datetime(2026, 8, 7, 4, 50, tzinfo=timezone.utc).timestamp()), "open": 25009.0, "high": 25020.0, "low": 25005.0, "close": 25015.0, "volume": 200},
    ]
    service._refresh_futures_chart_cache(now)

    result = service.futures_vwap_projection("5m")

    assert result["status"] == "AVAILABLE"
    assert result["formula_version"] == "ORACLE_DEV_FUTURES_VWAP_V1"
    assert result["security_id"] == "123"
    assert result["candles"][0]["vwap"] == 25001.67
    assert result["candles"][1]["vwap"] == 25008.33
    assert result["session_profile"]["status"] == "AVAILABLE"
    assert result["session_profile"]["val"] <= result["session_profile"]["poc"] <= result["session_profile"]["vah"]
    assert result["current_price"] == 25015.0
    assert result["execution_influence"] == "ZERO"


def test_v2_publishes_order_flow_and_futures_chart_as_advisory_feeds():
    integration = V2DashboardIntegration(
        snapshot=lambda: {"status": {}, "journal_summary": {}, "active_trade": None, "analytics": {}, "optimizer": {}, "scanner": []},
        order_flow=lambda: {"status": "UNAVAILABLE", "execution_influence": "ZERO"},
        futures_chart=lambda: {"status": "UNAVAILABLE", "execution_influence": "ZERO"},
    )
    feeds = integration.dashboard("NIFTY")["feeds"]
    assert feeds["order_flow"]["data"]["execution_influence"] == "ZERO"
    assert feeds["order_flow"]["meta"]["advisory_only"] is True
    assert feeds["futures_chart"]["data"]["execution_influence"] == "ZERO"
    assert feeds["futures_chart"]["meta"]["advisory_only"] is True
