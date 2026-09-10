"""Offline Deterministic Replay Harness for Eye Engine E2A."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, BarReference, _check_tz
from src.eye.adapter_result import AdapterResult, AdapterAbstention, AdapterAbstentionReason
from src.eye.adapters.structure_v2 import StructureV2Adapter
from src.eye.adapters.bigbeluga import BigBelugaAdapter
from src.eye.adapters.fvg import FVGAdapter
from src.eye.adapters.liquidity import LiquidityAdapter
from src.eye.adapters.oracle_dev import OracleDevAdapter


class ReplayMode(str, Enum):
    INCREMENTAL = "incremental"
    FULL_RECONSTRUCTION = "full-reconstruction"


class PrefixInvarianceStatus(str, Enum):
    PREFIX_STABLE = "PREFIX_STABLE"
    DELAYED_CONFIRMATION = "DELAYED_CONFIRMATION"
    BACKFILLED_AFTER_CONFIRMATION = "BACKFILLED_AFTER_CONFIRMATION"
    REPAINTS_WITH_FUTURE_DATA = "REPAINTS_WITH_FUTURE_DATA"
    LIFECYCLE_REVISION = "LIFECYCLE_REVISION"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, kw_only=True, slots=True)
class ParityComparisonResult:
    producer: str
    is_parity: bool
    incremental_count: int
    full_count: int
    matching_event_keys: Tuple[str, ...]
    mismatches: Tuple[str, ...]
    prefix_invariance_status: PrefixInvarianceStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "is_parity": self.is_parity,
            "incremental_count": self.incremental_count,
            "full_count": self.full_count,
            "matching_event_keys": list(self.matching_event_keys),
            "mismatches": list(self.mismatches),
            "prefix_invariance_status": self.prefix_invariance_status.value,
        }


class OfflineReplayHarness:
    def __init__(self) -> None:
        self._adapters = {
            "structure_v2": StructureV2Adapter(),
            "bigbeluga": BigBelugaAdapter(),
            "fvg": FVGAdapter(),
            "liquidity": LiquidityAdapter(),
            "oracle_dev": OracleDevAdapter(),
        }

    def run_replay(
        self,
        *,
        producer_name: str,
        fixture_bars: Sequence[Mapping[str, Any]],
        instrument_identity: InstrumentIdentity,
        timeframe: str,
        mode: ReplayMode = ReplayMode.INCREMENTAL,
        native_evaluator: Optional[Any] = None,
    ) -> Sequence[AdapterResult]:
        adapter = self._adapters.get(producer_name)
        if not adapter:
            raise ValueError(f"Unknown producer adapter: {producer_name}")

        results: List[AdapterResult] = []

        if mode == ReplayMode.INCREMENTAL:
            for i in range(1, len(fixture_bars) + 1):
                sub_bars = fixture_bars[:i]
                curr_bar = sub_bars[-1]
                t = curr_bar.get("expected_close_time") or curr_bar.get("open_time") or datetime.now(timezone.utc)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)

                native_out = native_evaluator(sub_bars) if native_evaluator else {}
                res = adapter.adapt(
                    native_output=native_out,
                    source_bars=sub_bars,
                    instrument_identity=instrument_identity,
                    timeframe=timeframe,
                    evaluation_context=ctx,
                )
                results.append(res)
        else:
            t = fixture_bars[-1].get("expected_close_time") or fixture_bars[-1].get("open_time") or datetime.now(timezone.utc)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            native_out = native_evaluator(fixture_bars) if native_evaluator else {}
            res = adapter.adapt(
                native_output=native_out,
                source_bars=fixture_bars,
                instrument_identity=instrument_identity,
                timeframe=timeframe,
                evaluation_context=ctx,
            )
            results.append(res)

        return results

    def compare_parity(
        self,
        *,
        producer_name: str,
        fixture_bars: Sequence[Mapping[str, Any]],
        instrument_identity: InstrumentIdentity,
        timeframe: str,
        native_evaluator: Optional[Any] = None,
    ) -> ParityComparisonResult:
        inc_results = self.run_replay(
            producer_name=producer_name,
            fixture_bars=fixture_bars,
            instrument_identity=instrument_identity,
            timeframe=timeframe,
            mode=ReplayMode.INCREMENTAL,
            native_evaluator=native_evaluator,
        )
        full_results = self.run_replay(
            producer_name=producer_name,
            fixture_bars=fixture_bars,
            instrument_identity=instrument_identity,
            timeframe=timeframe,
            mode=ReplayMode.FULL_RECONSTRUCTION,
            native_evaluator=native_evaluator,
        )

        inc_keys = set()
        for r in inc_results:
            for rec in r.records:
                inc_keys.add(rec.event_key)

        full_keys = set()
        for r in full_results:
            for rec in r.records:
                full_keys.add(rec.event_key)

        matching = tuple(sorted(inc_keys.intersection(full_keys)))
        mismatches = tuple(sorted(inc_keys.symmetric_difference(full_keys)))

        is_parity = (len(mismatches) == 0)
        status = PrefixInvarianceStatus.PREFIX_STABLE if is_parity else PrefixInvarianceStatus.DELAYED_CONFIRMATION

        return ParityComparisonResult(
            producer=producer_name,
            is_parity=is_parity,
            incremental_count=len(inc_keys),
            full_count=len(full_keys),
            matching_event_keys=matching,
            mismatches=mismatches,
            prefix_invariance_status=status,
        )
