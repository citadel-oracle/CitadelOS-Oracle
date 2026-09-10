import csv
import json

import pytest

from src.strategy_lab.core import OrderBlock, SharedOrderBlockEngine
from src.strategy_lab.strategies.breakout_main import (
    BreakoutMainParityValidator,
    BreakoutMainStrategyEngine,
    MarketStructureEngine,
    TradingViewFixture,
    TradingViewFixtureImporter,
    capture_runtime_transition,
)


def metadata(source="UNIT_TEST"):
    return {
        "schema_version": 1, "source": source, "strategy": "BREAKOUT MAIN",
        "pine_version": 5, "pine_source_sha256": "0" * 64,
        "symbol": "NIFTY", "timeframe": "1", "timezone": "Asia/Kolkata",
    }


def expected_state(value=0):
    return {
        "market_structure": {"trend": value, "bos": None, "choch": None, "upsweep": False, "dnsweep": False, "events": []},
        "order_blocks": {"bullish": [], "bearish": []},
        "strategy": {
            "pending_signal": None, "signal_high": None, "signal_low": None,
            "signal_stop": None, "target": None, "long_position": None,
            "trailing_stop": None, "exit_reason": None, "used_setups": [],
            "signal": "WAIT", "signal_cancellation": None, "session_reset": False,
        },
        "events": {"replay": [], "journal": [], "evidence": []},
        "runtime_serialization": {}, "paper_order": None,
    }


def bar(index, *, high=101, low=98, close=100, open=99):
    return {
        "index": index, "timestamp": f"2026-07-14T10:0{index}:00+05:30",
        "open": open, "high": high, "low": low, "close": close,
        "volume": 1000, "confirmed": True,
    }


def order_blocks():
    engine = SharedOrderBlockEngine()
    engine.bearish = [
        OrderBlock(False, 100, 99, 99.5, 10, 1000, -1),
        OrderBlock(False, 111, 108, 109.5, 20, 1000, -1),
    ]
    return engine


def pipeline():
    blocks = order_blocks()
    structure = MarketStructureEngine({"window_enabled": False, "pivot_length": 2})
    strategy = BreakoutMainStrategyEngine(order_blocks=blocks)

    def observe(raw_bar):
        structure_result = structure.update(raw_bar)
        strategy_result = strategy.evaluate({"bar": raw_bar, "symbol": "NIFTY", "timeframe": "1m"})
        return capture_runtime_transition(
            market_structure=structure_result, order_blocks=blocks,
            strategy=strategy_result, runtime_serialization=strategy.serialize(),
            paper_order={"signal": strategy_result["signal"]} if strategy_result["signal"] != "WAIT" else None,
        )

    return observe


@pytest.mark.unit
def test_json_fixture_import_requires_complete_bar_scoped_state(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"metadata": metadata(), "records": [{"bar": bar(1), "expected": {}}]}))
    with pytest.raises(ValueError, match="expected state is incomplete"):
        TradingViewFixtureImporter.load(path)

    path.write_text(json.dumps({"metadata": metadata(), "records": [{"bar": bar(1), "expected": expected_state()}]}))
    fixture = TradingViewFixtureImporter.load(path)
    assert fixture.metadata["strategy"] == "BREAKOUT MAIN"
    assert fixture.records[0]["bar"]["index"] == 1


@pytest.mark.unit
def test_csv_fixture_import_uses_required_metadata_sidecar(tmp_path):
    path = tmp_path / "fixture.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "bar_index", "timestamp", "open", "high", "low", "close", "volume", "confirmed", "expected_json",
        ))
        writer.writeheader()
        row = bar(1)
        writer.writerow({
            "bar_index": 1, "timestamp": row["timestamp"], "open": 99,
            "high": 101, "low": 98, "close": 100, "volume": 1000,
            "confirmed": "true", "expected_json": json.dumps(expected_state()),
        })
    with pytest.raises(ValueError, match="metadata"):
        TradingViewFixtureImporter.load(path)
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata()), encoding="utf-8")
    assert len(TradingViewFixtureImporter.load(path).records) == 1


@pytest.mark.unit
def test_bar_order_and_ohlc_validation_are_fail_closed(tmp_path):
    records = [
        {"bar": bar(2), "expected": expected_state()},
        {"bar": bar(1), "expected": expected_state()},
    ]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"metadata": metadata(), "records": records}))
    with pytest.raises(ValueError, match="strictly increasing"):
        TradingViewFixtureImporter.load(path)


@pytest.mark.unit
def test_validator_reports_exact_bar_and_field_mismatch():
    fixture = TradingViewFixture(metadata("TRADINGVIEW"), ({"bar": bar(1), "expected": expected_state(1)},))
    report = BreakoutMainParityValidator().validate(fixture, lambda _: expected_state(0))
    assert report.status == "PARITY_MISMATCH"
    assert report.parity_proven is False
    assert report.mismatches[0].bar_index == 1
    assert report.mismatches[0].path == "market_structure.trend"
    assert report.mismatches[0].expected == 1
    assert report.mismatches[0].actual == 0


@pytest.mark.safety
def test_non_tradingview_or_empty_fixture_can_never_claim_parity():
    record = {"bar": bar(1), "expected": expected_state()}
    internal = TradingViewFixture(metadata("UNIT_TEST"), (record,))
    report = BreakoutMainParityValidator().validate(internal, lambda _: expected_state())
    assert report.matched_records == 1
    assert report.status == "INVALID_NON_TRADINGVIEW_SOURCE"
    assert report.parity_proven is False

    empty = TradingViewFixture(metadata("TRADINGVIEW"), ())
    report = BreakoutMainParityValidator().validate(empty, lambda _: expected_state())
    assert report.status == "BLOCKED_NO_TRADINGVIEW_RECORDS"
    assert report.parity_proven is False


@pytest.mark.unit
def test_numeric_tolerance_is_explicit_and_defaults_to_exact():
    fixture = TradingViewFixture(metadata("TRADINGVIEW"), ({"bar": bar(1), "expected": expected_state(1.00001)},))
    exact = BreakoutMainParityValidator().validate(fixture, lambda _: expected_state(1.0))
    tolerant = BreakoutMainParityValidator(numeric_tolerance=0.001).validate(fixture, lambda _: expected_state(1.0))
    assert exact.status == "PARITY_MISMATCH"
    assert tolerant.status == "TRADINGVIEW_PARITY_PROVEN"


@pytest.mark.unit
def test_deterministic_bar_replay_matches_every_captured_transition():
    bars = [bar(0, high=102, close=101), bar(1, high=103, low=99, close=102), bar(2, open=104, high=109, low=100, close=108)]
    reference = pipeline()
    records = tuple({"bar": item, "expected": reference(item)} for item in bars)
    fixture = TradingViewFixture(metadata("UNIT_TEST"), records)
    report = BreakoutMainParityValidator().validate(fixture, pipeline())
    assert report.records == 3
    assert report.matched_records == 3
    assert report.mismatches == ()
    assert report.parity_proven is False  # deterministic Python replay is not TradingView proof


@pytest.mark.unit
def test_serialization_resume_matches_uninterrupted_runtime_bar_for_bar():
    first = pipeline()
    first_bar = bar(0, high=102, close=101)
    first(first_bar)

    blocks = order_blocks()
    structure = MarketStructureEngine({"window_enabled": False, "pivot_length": 2})
    structure.update(first_bar)
    strategy = BreakoutMainStrategyEngine(order_blocks=blocks)
    strategy.evaluate({"bar": first_bar, "symbol": "NIFTY", "timeframe": "1m"})
    restored_strategy = BreakoutMainStrategyEngine.deserialize(strategy.serialize())
    restored_structure = MarketStructureEngine.restore(structure.snapshot())
    next_bar = bar(1, high=103, low=99, close=102)
    actual = capture_runtime_transition(
        market_structure=restored_structure.update(next_bar),
        order_blocks=restored_strategy.order_blocks,
        strategy=(result := restored_strategy.evaluate({"bar": next_bar, "symbol": "NIFTY", "timeframe": "1m"})),
        runtime_serialization=restored_strategy.serialize(),
        paper_order={"signal": result["signal"]} if result["signal"] != "WAIT" else None,
    )
    uninterrupted = pipeline()
    uninterrupted(first_bar)
    expected = uninterrupted(next_bar)
    assert actual == expected


@pytest.mark.unit
def test_capture_includes_required_transition_contract():
    observe = pipeline()
    transition = observe(bar(0, high=102, close=101))
    for path in (
        ("market_structure", "trend"), ("market_structure", "upsweep"),
        ("order_blocks", "bearish"), ("strategy", "pending_signal"),
        ("strategy", "signal_stop"), ("events", "replay"),
    ):
        assert path[1] in transition[path[0]]
    assert isinstance(transition["runtime_serialization"], dict)
    assert transition["paper_order"] is None
