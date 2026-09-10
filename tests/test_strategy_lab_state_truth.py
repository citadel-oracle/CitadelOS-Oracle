from datetime import datetime, timedelta

import pytest

from src.strategy_lab.state_truth import (
    CandleIdentity,
    CanonicalCandleStore,
    HistoryRequirement,
    authoritative_open_positions,
    reconcile_deployment_positions,
    stable_structure_id,
)
from src.strategy_lab.completed_candle import CompletedCandleContextProvider
from src.strategy_lab.core import OrderBlockBar
from src.strategy_lab.strategies.pullback_master.adapter import PullbackMasterNativeAdapter


IST = datetime.fromisoformat("2026-07-17T09:15:00+05:30").tzinfo


def candle(index, *, timeframe=1, closed=True, source="DHAN_DATA_API"):
    stamp = datetime(2026, 7, 17, 9, 15, tzinfo=IST) + timedelta(minutes=index * timeframe)
    return {
        "timestamp": stamp.isoformat(), "open": 100 + index, "high": 101 + index,
        "low": 99 + index, "close": 100.5 + index, "volume": 1000 + index,
        "source": source, "closed": closed, "is_closed": closed,
        "received_at": (stamp + timedelta(minutes=timeframe)).isoformat(),
    }


@pytest.mark.unit
def test_canonical_store_merges_overlap_idempotently_and_excludes_incomplete(tmp_path):
    store = CanonicalCandleStore(tmp_path, CandleIdentity("NIFTY", "13", "1m"))
    first = store.merge([candle(0), candle(1), candle(2), candle(3, closed=False)])
    second = store.merge([candle(1), candle(2)])
    assert first["loaded_bars"] == 3
    assert first["rejected"] == 1
    assert second["duplicates"] == 2
    assert store.audit()["duplicate_candle_count"] == 0


@pytest.mark.unit
def test_canonical_store_detects_gap_and_current_session_origin(tmp_path):
    store = CanonicalCandleStore(tmp_path, CandleIdentity("NIFTY", "13", "1m"))
    store.merge([candle(0), candle(2)])
    audit = store.audit()
    assert audit["current_session_starts_at_0915"] is True
    assert audit["missing_candle_count"] == 1
    assert audit["missing_timestamps"][0].endswith("09:16:00+05:30")


@pytest.mark.unit
def test_canonical_store_rejects_outside_session_rows_without_false_gap(tmp_path):
    store = CanonicalCandleStore(tmp_path, CandleIdentity("NIFTY", "13", "5m"))
    rows = [candle(73, timeframe=5), candle(74, timeframe=5)]
    outside = {
        **candle(0, timeframe=5),
        "timestamp": "2026-07-17T18:05:00+05:30",
        "received_at": "2026-07-17T18:10:00+05:30",
    }

    result = store.merge([*rows, outside])

    assert result["rejected"] == 1
    assert [row["timestamp"] for row in store.load()] == [
        "2026-07-17T15:20:00+05:30",
        "2026-07-17T15:25:00+05:30",
    ]
    assert store.audit()["missing_timestamps"] == []


@pytest.mark.unit
def test_dynamic_requirement_includes_stabilization_structures_overlap_and_safety():
    one = HistoryRequirement.strategy_lab_default("1m")
    five = HistoryRequirement.strategy_lab_default("5m")
    assert one.required_bars >= 4 * 375
    assert five.required_bars >= 700
    assert one.replay_overlap > 0 and one.safety_buffer > 0


@pytest.mark.unit
def test_readiness_blocks_insufficient_history_and_gaps(tmp_path):
    store = CanonicalCandleStore(tmp_path, CandleIdentity("NIFTY", "13", "1m"))
    store.merge([candle(index) for index in range(10)])
    readiness = store.readiness(HistoryRequirement.strategy_lab_default("1m"), now=datetime(2026, 7, 17, 9, 26, tzinfo=IST))
    assert readiness["DATA_READY"] is False
    assert readiness["not_ready_reason"] == "INSUFFICIENT_HISTORY"


def state(*positions):
    return {"strategy_id": "PB", "positions": list(positions)}


def position(identifier, strategy="PB", status="OPEN", contract=None):
    return {
        "position_id": identifier, "strategy_id": strategy, "status": status,
        "contract": contract or f"SEC-{identifier}", "quantity": 65, "average_price": 100.0,
        "current_price": 102.0, "pnl": 130.0, "pnl_valid": True,
    }


@pytest.mark.unit
@pytest.mark.parametrize("count", [0, 1, 4])
def test_authoritative_open_position_projection_preserves_zero_one_and_four(count):
    rows = authoritative_open_positions([state(*(position(str(index)) for index in range(count)))])
    assert len(rows) == count
    assert len({row["position_id"] for row in rows}) == count


@pytest.mark.unit
def test_closed_and_foreign_scope_rows_are_excluded_by_supplied_strategy_lab_states():
    rows = authoritative_open_positions([state(position("open"), position("closed", status="CLOSED"))])
    assert [row["position_id"] for row in rows] == ["open"]


@pytest.mark.unit
def test_duplicate_position_identity_is_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_OPEN_POSITION_ID"):
        authoritative_open_positions([state(position("same")), state(position("same", strategy="BO"))])


@pytest.mark.unit
def test_deployment_join_represents_multiple_positions_without_first_item_loss():
    strategies = [{"strategy_id": "PB"}, {"strategy_id": "BO"}]
    positions = [position("one"), position("two")]
    rows, reconciliation = reconcile_deployment_positions(strategies, positions)
    assert rows[0]["current_position_count"] == 2
    assert rows[0]["current_position"] is None
    assert rows[0]["position_state"] == "OPEN"
    assert rows[1]["position_state"] == "FLAT"
    assert reconciliation["status"] == "RECONCILED"


@pytest.mark.unit
def test_held_contract_identity_is_not_replaced_by_current_atm():
    held = position("one", contract="HELD-SECURITY")
    rows = authoritative_open_positions([state(held)])
    assert rows[0]["contract"] == "HELD-SECURITY"


@pytest.mark.unit
def test_structure_id_is_stable_across_restart_and_contract_scoped():
    args = dict(security_id="57350", timeframe="1m", origin_timestamp="2026-07-13T09:30:00+05:30", structure_type="ORDER_BLOCK", direction="BULLISH", rule_version="SHARED_CORE_V1")
    before = stable_structure_id(**args)
    after = stable_structure_id(**args)
    rotated = stable_structure_id(**{**args, "security_id": "57399"})
    assert before == after
    assert before != rotated


@pytest.mark.unit
def test_four_session_old_structure_survives_restart_with_immutable_reference_and_forward_lifecycle():
    adapter = PullbackMasterNativeAdapter()
    pipeline = adapter.pipeline
    origin = datetime.fromisoformat("2026-07-13T09:30:00+05:30")
    origin_ms = int(origin.timestamp() * 1000)
    block = pipeline.order_blocks.create_block(
        bull=True,
        boundary=105.0,
        origin=OrderBlockBar(origin_ms, 100.0, 106.0, 99.0, 104.0, 1_000.0),
    )
    context = {
        "symbol": "NIFTY_CE", "contract": "57350", "timeframe": "1m",
        "timestamp": "2026-07-13T09:35:00+05:30",
        "chart_contract": {"expiry": "2026-07-21"},
        "data_readiness": {"reservoir_checksum": "source-checksum"},
    }
    pipeline._catalog_structure(
        structure_type="ORDER_BLOCK", direction="BULLISH", origin=block.loc,
        confirmation=int(datetime.fromisoformat(context["timestamp"]).timestamp() * 1000),
        lower=block.btm, upper=block.top, context=context,
    )
    before = pipeline.reference_for_level(102.0)
    restored = type(pipeline).restore(adapter.engine, pipeline.snapshot())
    after = restored.reference_for_level(102.0)
    assert after == before
    assert after["source_data_checksum"] == "source-checksum"
    assert after["origin_candle"] == origin.isoformat()
    restored._advance_structure_catalog(
        {"timestamp": "2026-07-17T09:30:00+05:30", "high": 103.0, "low": 101.0},
        {**context, "timestamp": "2026-07-17T09:30:00+05:30"},
    )
    touched = restored.snapshot()["structure_catalog"][after["structure_id"]]
    assert touched["state"] == "TOUCHED"
    assert touched["origin_candle"] == origin.isoformat()
    assert touched["lower_bound"] == before["lower_bound"]
    assert touched["upper_bound"] == before["upper_bound"]


@pytest.mark.unit
def test_completed_candle_context_blocks_before_data_ready():
    class Source:
        def load_cache(self):
            return [candle(0)]
        def readiness(self):
            return {"DATA_READY": False, "not_ready_reason": "INSUFFICIENT_HISTORY", "loaded_bars": 1, "required_bars": 100}
    context = CompletedCandleContextProvider(
        candle_source=Source(), argus_provider=lambda: {"status": "available", "data": {}},
        clock=lambda: datetime(2026, 7, 17, 9, 16, tzinfo=IST),
    )()
    assert context["is_closed"] is False
    assert context["data_readiness"]["DATA_READY"] is False
    assert context["source_reason"] == "INSUFFICIENT_HISTORY"


@pytest.mark.unit
def test_argus_cache_ttl_label_does_not_false_block_current_market_snapshot():
    now = datetime(2026, 7, 17, 9, 20, tzinfo=IST)
    class Source:
        def load_cache(self):
            return [candle(4)]
        def readiness(self):
            return {"DATA_READY": True, "loaded_bars": 2_000, "required_bars": 1_594}
    argus = {
        "status": "stale", "freshness": "stale",
        "data": {"underlying": {"market_state": "OPEN", "fetched_at": (now - timedelta(seconds=8)).isoformat()}},
    }
    context = CompletedCandleContextProvider(
        candle_source=Source(), argus_provider=lambda: argus, clock=lambda: now,
    )()
    assert context["is_closed"] is True
    assert context["data_readiness"]["DATA_READY"] is True
