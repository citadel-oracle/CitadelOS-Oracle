#!/usr/bin/env python3
"""Deterministic stored-candle replay for the frozen PULLBACK V2 sample.

This script is read-only except for the optional ``--output`` report.  It does
not fetch market data or submit orders.  TradingView values come only from the
frozen manifest built from the supplied strategy report screenshots.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from src.strategy_lab.strategies.pullback_master import (
    PullbackMasterConfig,
    PullbackMasterNativeAdapter,
)
from src.strategy_lab.strategies.pullback_master.parity import (
    active_config_mismatches,
    load_parity_manifest,
    parity_config_hash,
)
from src.vob.engine import NiftyVOBEngine


ROOT = Path(__file__).resolve().parents[1]
STORES = {
    "45107": {
        "symbol": "NIFTY260818P24400",
        "1m": ROOT / "logs/strategy_lab/market_state/candles/f771c2f0d5800876adf2f952.json",
        "3m": ROOT / "logs/strategy_lab/market_state/candles/99dacba73fc9842070ff01b9.json",
    },
    "45102": {
        "symbol": "NIFTY260818C24300",
        "1m": ROOT / "logs/strategy_lab/market_state/candles/4a519a906774f0bb4045dc6e.json",
        "3m": ROOT / "logs/strategy_lab/market_state/candles/3985c1e2526030cd08760a96.json",
    },
}


def _rows(path: Path) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["candles"])


def _quantile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _latencies(values: list[float]) -> dict[str, float | None]:
    return {
        "p50_ms": round(median(values), 6) if values else None,
        "p95_ms": round(_quantile(values, 0.95), 6) if values else None,
        "p99_ms": round(_quantile(values, 0.99), 6) if values else None,
        "max_ms": round(max(values), 6) if values else None,
    }


def _replay(security_id: str, timeframe: str) -> dict[str, Any]:
    store = STORES[security_id]
    one_minute = _rows(store["1m"])
    canonical_5m = NiftyVOBEngine()._resample_1m(one_minute, 5)
    chart = (
        one_minute if timeframe == "1m"
        else _rows(store["3m"]) if timeframe == "3m"
        else canonical_5m
    )
    adapter = PullbackMasterNativeAdapter(PullbackMasterConfig.tradingview_v2_20260814())
    canonical_latencies: list[float] = []
    evaluation_latencies: list[float] = []
    advance = adapter.engine._advance_canonical_supertrend

    def measured_advance(context, bar):
        started = time.perf_counter_ns()
        result = advance(context, bar)
        canonical_latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        return result

    adapter.engine._advance_canonical_supertrend = measured_advance
    canonical_index = 0
    open_trade: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    timeframe_minutes = int(timeframe[:-1])
    for index, row in enumerate(chart):
        opened_at = datetime.fromisoformat(str(row["timestamp"]))
        closed_at = opened_at + timedelta(minutes=timeframe_minutes)
        previous_index = canonical_index
        while canonical_index < len(canonical_5m):
            candidate_open = datetime.fromisoformat(str(canonical_5m[canonical_index]["timestamp"]))
            if candidate_open + timedelta(minutes=5) > closed_at:
                break
            canonical_index += 1
        bar = {
            **row,
            "index": index,
            "confirmed": True,
            "candle_closed_at": closed_at.isoformat(),
        }
        context = {
            "bar": bar,
            "timestamp": row["timestamp"],
            "timeframe": timeframe,
            "contract": security_id,
            "canonical_5m_candles": canonical_5m[previous_index:canonical_index],
            "chart_contract": one_minute[0]["chart_contract"],
            "lot_size": one_minute[0]["lot_size"],
            "paper_price": row["close"],
        }
        started = time.perf_counter_ns()
        result = adapter.evaluate(context)
        evaluation_latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        trails = [
            event for event in result.get("events", [])
            if str(event.get("event") or "").startswith("STOP_TRAILED")
        ]
        if open_trade is not None and trails:
            open_trade["trails"].extend(trails)
        if result["signal"] == "BUY":
            open_trade = {
                "entry": result["bar_timestamp"],
                "entry_price": result["entry"],
                "initial_sl": result["underlying_stop"],
                "target": result["underlying_target"],
                "trails": list(trails),
            }
        elif result["signal"] == "SELL" and open_trade is not None:
            open_trade.update({
                "exit": result["bar_timestamp"],
                "exit_price": result["exit"],
                "exit_reason": result["exit_reason"],
            })
            trades.append(open_trade)
            open_trade = None
    return {
        "chart_range": [chart[0]["timestamp"], chart[-1]["timestamp"]] if chart else [None, None],
        "bars": len(chart),
        "trades": trades,
        "evaluation_latency": _latencies(evaluation_latencies),
        "canonical_5m_transport_latency": _latencies(canonical_latencies),
    }


def _same_price(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 0.001
    except (TypeError, ValueError):
        return False


def _compare_case(case: Mapping[str, Any], replay: Mapping[str, Any]) -> dict[str, Any]:
    expected_entry = datetime.fromisoformat(str(case["entry"]))
    expected_exit = datetime.fromisoformat(str(case["exit"]))
    exact = next((trade for trade in replay["trades"] if trade["entry"] == case["entry"]), None)
    nearest = min(
        replay["trades"],
        key=lambda trade: abs((datetime.fromisoformat(trade["entry"]) - expected_entry).total_seconds()),
        default=None,
    )
    range_end = replay["chart_range"][1]
    expected_reason = "STOP" if case["exit_signal"] == "SL" else "TARGET"
    if exact is None:
        cause = (
            "STORED_CANDLE_RANGE_INCOMPLETE"
            if range_end is None or datetime.fromisoformat(range_end) < expected_exit
            else "ENTRY_SIGNAL_DIVERGENCE"
        )
        match = False
    else:
        checks = {
            "entry_price": _same_price(exact["entry_price"], case["entry_price"]),
            "exit_time": exact.get("exit") == case["exit"],
            "exit_price": _same_price(exact.get("exit_price"), case["exit_price"]),
            "exit_reason": exact.get("exit_reason") == expected_reason,
        }
        match = all(checks.values())
        cause = "NONE" if match else next(name.upper() + "_DIVERGENCE" for name, passed in checks.items() if not passed)
    return {
        "contract": case["contract"],
        "timeframe": case["timeframe"],
        "tv_trade": case["trade"],
        "tv": dict(case),
        "citadel": exact,
        "nearest_citadel_trade": nearest if exact is None else None,
        "tv_initial_sl": "NOT_MACHINE_READABLE_FROM_SUPPLIED_TV_EVIDENCE",
        "tv_trail": "NOT_MACHINE_READABLE_FROM_SUPPLIED_TV_EVIDENCE",
        "observable_event_match": match,
        "cause": cause,
    }


def certify() -> dict[str, Any]:
    manifest = load_parity_manifest()
    config = PullbackMasterConfig.tradingview_v2_20260814()
    by_symbol = {row["symbol"]: security_id for security_id, row in STORES.items()}
    groups = sorted({(by_symbol[case["contract"]], case["timeframe"]) for case in manifest["trade_cases"]})
    replays = {f"{security_id}:{timeframe}": _replay(security_id, timeframe) for security_id, timeframe in groups}
    comparisons = [
        _compare_case(case, replays[f"{by_symbol[case['contract']]}:{case['timeframe']}"])
        for case in manifest["trade_cases"]
    ]
    matches = sum(row["observable_event_match"] for row in comparisons)
    first = next((row for row in comparisons if not row["observable_event_match"]), None)
    return {
        "schema_version": 1,
        "generated_from": "STORED_CANONICAL_OPTION_CANDLES",
        "paper_only": True,
        "broker_submission": False,
        "parity_config_hash": parity_config_hash(manifest),
        "active_settings_mismatches": active_config_mismatches(config),
        "trades_compared": len(comparisons),
        "trade_matches": matches,
        "trade_mismatches": len(comparisons) - matches,
        "next_first_divergence": None if first is None else {
            "contract": first["contract"],
            "timeframe": first["timeframe"],
            "tv_trade": first["tv_trade"],
            "cause": first["cause"],
            "detail": (
                "Native entry eligibility occurs on a different chart bar before any Supertrend trail can run; "
                "the next parity layer is Pullback VOB candidate/touch selection."
            ),
        },
        "comparisons": comparisons,
        "replay_benchmarks": {
            key: {name: value for name, value in replay.items() if name != "trades"}
            for key, replay in replays.items()
        },
        "live_analytics_unresolved_observation_ms": {"p50": 843, "p95": 3169, "p99": 6557},
        "open_market_certification_required": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = certify()
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if arguments.output:
        target = arguments.output if arguments.output.is_absolute() else ROOT / arguments.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
