"""TradingView fixture import and exact bar-by-bar parity validation.

This module never generates expected Pine results. Parity can only become
proven when an imported fixture identifies TradingView as its source.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from ...core import SharedOrderBlockEngine


REQUIRED_EXPECTED_PATHS = (
    "market_structure.trend", "market_structure.bos", "market_structure.choch",
    "market_structure.upsweep", "market_structure.dnsweep", "market_structure.events",
    "order_blocks.bullish", "order_blocks.bearish",
    "strategy.pending_signal", "strategy.signal_high", "strategy.signal_low",
    "strategy.signal_stop", "strategy.target", "strategy.long_position",
    "strategy.trailing_stop", "strategy.exit_reason", "strategy.used_setups",
    "strategy.signal", "strategy.signal_cancellation", "strategy.session_reset",
    "events.replay", "events.journal", "events.evidence",
    "runtime_serialization", "paper_order",
)


@dataclass(frozen=True)
class ParityMismatch:
    record_index: int
    bar_index: int
    path: str
    expected: Any
    actual: Any


@dataclass(frozen=True)
class ParityReport:
    source: str
    records: int
    matched_records: int
    mismatches: tuple[ParityMismatch, ...]
    parity_proven: bool
    status: str

    def to_mapping(self) -> Dict[str, Any]:
        return {
            "source": self.source, "records": self.records,
            "matched_records": self.matched_records,
            "mismatches": [asdict(item) for item in self.mismatches],
            "parity_proven": self.parity_proven, "status": self.status,
        }


@dataclass(frozen=True)
class TradingViewFixture:
    metadata: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]

    @property
    def source(self) -> str:
        return str(self.metadata.get("source") or "").upper()


class TradingViewFixtureImporter:
    """Load deterministic JSON or CSV+metadata TradingView exports."""

    @classmethod
    def load(cls, path: str | Path) -> TradingViewFixture:
        source = Path(path)
        if source.suffix.lower() == ".json":
            return cls._from_json(source)
        if source.suffix.lower() == ".csv":
            return cls._from_csv(source)
        raise ValueError("BREAKOUT parity fixture must be JSON or CSV")

    @classmethod
    def _from_json(cls, path: Path) -> TradingViewFixture:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("fixture root must be an object")
        return cls._validate(value.get("metadata"), value.get("records"))

    @classmethod
    def _from_csv(cls, path: Path) -> TradingViewFixture:
        metadata_path = path.with_suffix(".metadata.json")
        if not metadata_path.is_file():
            raise ValueError("CSV fixture requires a .metadata.json sidecar")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    expected = json.loads(row["expected_json"])
                    records.append({
                        "bar": {
                            "index": int(row["bar_index"]), "timestamp": row["timestamp"],
                            "open": float(row["open"]), "high": float(row["high"]),
                            "low": float(row["low"]), "close": float(row["close"]),
                            "volume": float(row["volume"]),
                            "confirmed": row["confirmed"].strip().lower() == "true",
                        },
                        "expected": expected,
                    })
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid BREAKOUT parity CSV row") from exc
        return cls._validate(metadata, records)

    @classmethod
    def _validate(cls, metadata: Any, records: Any) -> TradingViewFixture:
        if not isinstance(metadata, Mapping) or not isinstance(records, list):
            raise ValueError("fixture metadata and records are required")
        if metadata.get("schema_version") != 1:
            raise ValueError("unsupported BREAKOUT parity fixture schema")
        if str(metadata.get("strategy") or "").upper() != "BREAKOUT MAIN":
            raise ValueError("fixture strategy must be BREAKOUT MAIN")
        required_metadata = ("source", "pine_version", "pine_source_sha256", "symbol", "timeframe", "timezone")
        if any(metadata.get(field) in (None, "") for field in required_metadata):
            raise ValueError("fixture source metadata is incomplete")
        if metadata.get("pine_version") != 5:
            raise ValueError("fixture Pine version must be 5")
        if re.fullmatch(r"[0-9a-fA-F]{64}", str(metadata.get("pine_source_sha256"))) is None:
            raise ValueError("fixture Pine source hash must be SHA-256")
        normalized = []
        previous_index: Optional[int] = None
        for record in records:
            if not isinstance(record, Mapping) or not isinstance(record.get("bar"), Mapping) or not isinstance(record.get("expected"), Mapping):
                raise ValueError("every fixture record requires bar and expected objects")
            bar = dict(record["bar"])
            cls._validate_bar(bar)
            if previous_index is not None and int(bar["index"]) <= previous_index:
                raise ValueError("fixture bars must be strictly increasing")
            previous_index = int(bar["index"])
            expected = dict(record["expected"])
            missing = [path for path in REQUIRED_EXPECTED_PATHS if not cls._has_path(expected, path)]
            if missing:
                raise ValueError(f"fixture expected state is incomplete: {', '.join(missing)}")
            normalized.append({"bar": bar, "expected": expected})
        return TradingViewFixture(dict(metadata), tuple(normalized))

    @staticmethod
    def _validate_bar(bar: Mapping[str, Any]) -> None:
        required = ("index", "timestamp", "open", "high", "low", "close", "volume", "confirmed")
        if any(field not in bar for field in required):
            raise ValueError("fixture bar is incomplete")
        values = tuple(float(bar[field]) for field in ("open", "high", "low", "close", "volume"))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("fixture bar contains non-finite values")
        if values[1] < max(values[0], values[2], values[3]) or values[2] > min(values[0], values[1], values[3]):
            raise ValueError("fixture bar OHLC is invalid")

    @staticmethod
    def _has_path(value: Mapping[str, Any], path: str) -> bool:
        current: Any = value
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return False
            current = current[part]
        return True


class BreakoutMainParityValidator:
    """Exact recursive comparison with an explicit numeric tolerance."""

    def __init__(self, *, numeric_tolerance: float = 0.0) -> None:
        if numeric_tolerance < 0:
            raise ValueError("numeric tolerance cannot be negative")
        self.numeric_tolerance = float(numeric_tolerance)

    def validate(
        self,
        fixture: TradingViewFixture,
        observer: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> ParityReport:
        mismatches: list[ParityMismatch] = []
        matched = 0
        for record_index, record in enumerate(fixture.records):
            actual = observer(record["bar"])
            before = len(mismatches)
            self._compare(
                record["expected"], actual, path="", record_index=record_index,
                bar_index=int(record["bar"]["index"]), mismatches=mismatches,
            )
            if len(mismatches) == before:
                matched += 1
        authoritative = fixture.source == "TRADINGVIEW"
        proven = authoritative and bool(fixture.records) and not mismatches
        if not authoritative:
            status = "INVALID_NON_TRADINGVIEW_SOURCE"
        elif not fixture.records:
            status = "BLOCKED_NO_TRADINGVIEW_RECORDS"
        elif mismatches:
            status = "PARITY_MISMATCH"
        else:
            status = "TRADINGVIEW_PARITY_PROVEN"
        return ParityReport(fixture.source, len(fixture.records), matched, tuple(mismatches), proven, status)

    def _compare(self, expected: Any, actual: Any, *, path: str, record_index: int, bar_index: int, mismatches: list[ParityMismatch]) -> None:
        if isinstance(expected, Mapping):
            if not isinstance(actual, Mapping):
                mismatches.append(ParityMismatch(record_index, bar_index, path or "$", expected, actual))
                return
            for key, expected_value in expected.items():
                child = f"{path}.{key}" if path else str(key)
                if key not in actual:
                    mismatches.append(ParityMismatch(record_index, bar_index, child, expected_value, "<MISSING>"))
                else:
                    self._compare(expected_value, actual[key], path=child, record_index=record_index, bar_index=bar_index, mismatches=mismatches)
            return
        if isinstance(expected, list):
            if not isinstance(actual, (list, tuple)) or len(expected) != len(actual):
                mismatches.append(ParityMismatch(record_index, bar_index, path, expected, actual))
                return
            for index, expected_value in enumerate(expected):
                self._compare(expected_value, actual[index], path=f"{path}[{index}]", record_index=record_index, bar_index=bar_index, mismatches=mismatches)
            return
        equal = self._equal(expected, actual)
        if not equal:
            mismatches.append(ParityMismatch(record_index, bar_index, path, expected, actual))

    def _equal(self, expected: Any, actual: Any) -> bool:
        if isinstance(expected, bool) or isinstance(actual, bool):
            return expected is actual
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return math.isclose(float(expected), float(actual), rel_tol=0.0, abs_tol=self.numeric_tolerance)
        return expected == actual


def capture_runtime_transition(
    *,
    market_structure: Mapping[str, Any],
    order_blocks: SharedOrderBlockEngine,
    strategy: Mapping[str, Any],
    runtime_serialization: str,
    paper_order: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Normalize authoritative runtime output to the fixture comparison shape."""

    structure_state = dict(market_structure.get("state") or {})
    structure_events = list(market_structure.get("events") or [])
    current_bar = strategy.get("bar_index")
    current_events = [item for item in structure_events if item.get("bar_index") == current_bar]
    pending = strategy.get("pending_signal")
    position = strategy.get("position_state")
    return {
        "market_structure": {
            "trend": structure_state.get("trend"), "bos": structure_state.get("bos"),
            "choch": structure_state.get("choch"), "upsweep": structure_state.get("upsweep"),
            "dnsweep": structure_state.get("dnsweep"),
            "events": current_events,
        },
        "order_blocks": {
            "bullish": [item.to_mapping() for item in order_blocks.bullish],
            "bearish": [item.to_mapping() for item in order_blocks.bearish],
        },
        "strategy": {
            "pending_signal": pending,
            "signal_high": pending.get("high") if isinstance(pending, Mapping) else None,
            "signal_low": pending.get("low") if isinstance(pending, Mapping) else None,
            "signal_stop": pending.get("stop") if isinstance(pending, Mapping) else None,
            "target": (position or pending or {}).get("target") if isinstance(position or pending, Mapping) else None,
            "long_position": position,
            "trailing_stop": position.get("stop") if isinstance(position, Mapping) else None,
            "exit_reason": strategy.get("reason") if strategy.get("signal") == "SELL" else None,
            "used_setups": list(strategy.get("used_setup_locations") or []),
            "signal": strategy.get("signal"),
            "signal_cancellation": next((item.get("event") for item in strategy.get("events") or [] if str(item.get("event") or "").startswith("SIGNAL_CANCELLED")), None),
            "session_reset": any(item.get("event") == "DAILY_RESET" for item in strategy.get("events") or []),
        },
        "events": {
            "replay": list(strategy.get("replay_events") or []),
            "journal": list(strategy.get("journal_events") or []),
            "evidence": list(strategy.get("evidence_events") or []),
        },
        "runtime_serialization": json.loads(runtime_serialization),
        "paper_order": dict(paper_order) if paper_order is not None else None,
    }
