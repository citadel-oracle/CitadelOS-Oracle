"""Liquidity Pools, Sweeps, Breaks and Reclaims Detector for Eye Engine E2B."""

from datetime import datetime, timezone
from typing import List, Sequence

from src.eye.detectors.base import BaseAtomicDetector
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult, DetectorAbstention, DetectorAbstentionReason
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    PointEventPayload,
    ZoneEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    AuthorityType,
)


class LiquidityDetector(BaseAtomicDetector):
    DETECTOR_FAMILY = "LIQUIDITY"
    RULE_ID_POOL = "EYE_LIQUIDITY_EQUAL_HIGH_ATR_V1"
    RULE_ID_SWEEP = "EYE_SWEEP_WICK_CLOSE_INSIDE_V1"
    RULE_VERSION = "1.0.0"

    def __init__(self, tolerance_ticks: int = 5) -> None:
        self.tolerance_ticks = tolerance_ticks

    def detect(
        self,
        bars: Sequence[DetectorBar],
        context: DetectorContext,
    ) -> DetectorResult:
        records: List[EyeEventRecord] = []
        abstentions: List[DetectorAbstention] = []

        if len(bars) < 5:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INSUFFICIENT_BARS,
                reason="Need at least 5 bars for liquidity detection",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID_POOL, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        prov = ProducerProvenance(
            engine_name="LiquidityDetector",
            source_file="src/eye/detectors/liquidity.py",
            source_symbol="LiquidityDetector.detect",
            source_commit=context.source_revision,
            producer_version=context.producer_version,
            rule_id=self.RULE_ID_POOL,
            rule_version=self.RULE_VERSION,
            authority=AuthorityType.OBSERVATION_ONLY,
        )

        curr_bar = bars[-1]
        if not curr_bar.is_closed or curr_bar.available_at > context.as_of:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INCOMPLETE_BAR,
                reason="Current bar is not closed or available",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID_POOL, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        for i in range(len(bars) - 2):
            b1 = bars[i]
            for j in range(i + 1, len(bars) - 1):
                b2 = bars[j]
                # Equal Highs Pool
                if abs(b1.high.ticks - b2.high.ticks) <= self.tolerance_ticks:
                    bar_refs = [
                        BarReference(
                            instrument_key=b.instrument_key, timeframe=b.timeframe,
                            open_time=b.open_time, expected_close_time=b.expected_close_time,
                            available_at=b.available_at, bar_key=b.bar_key,
                            is_closed=b.is_closed, source_name=b.source_name,
                        )
                        for b in (b1, b2)
                    ]
                    payload = PointEventPayload(primary_level=b1.high, direction=EventDirection.BEARISH)
                    rec = EyeEventRecord.create(
                        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_HIGH,
                        direction=EventDirection.BEARISH, instrument=context.instrument,
                        timeframe=context.timeframe, payload=payload,
                        detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                        lifecycle_state=LifecycleState.ACTIVE,
                        evaluation_context=context,
                        observed_at=b2.expected_close_time,
                        detected_at=b2.expected_close_time,
                        source_bars=bar_refs, producer=prov,
                    )
                    records.append(rec)

                    if curr_bar.high.ticks > b1.high.ticks and curr_bar.close.ticks < b1.high.ticks:
                        sweep_refs = bar_refs + [
                            BarReference(
                                instrument_key=curr_bar.instrument_key, timeframe=curr_bar.timeframe,
                                open_time=curr_bar.open_time, expected_close_time=curr_bar.expected_close_time,
                                available_at=curr_bar.available_at, bar_key=curr_bar.bar_key,
                                is_closed=curr_bar.is_closed, source_name=curr_bar.source_name,
                            )
                        ]
                        prov_sweep = ProducerProvenance(
                            engine_name="LiquidityDetector",
                            source_file="src/eye/detectors/liquidity.py",
                            source_symbol="LiquidityDetector.detect",
                            source_commit=context.source_revision,
                            producer_version=context.producer_version,
                            rule_id=self.RULE_ID_SWEEP,
                            rule_version=self.RULE_VERSION,
                            authority=AuthorityType.OBSERVATION_ONLY,
                        )
                        payload_sweep = PointEventPayload(primary_level=b1.high, breached_level=curr_bar.high, direction=EventDirection.BEARISH)
                        rec_sweep = EyeEventRecord.create(
                            family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
                            direction=EventDirection.BEARISH, instrument=context.instrument,
                            timeframe=context.timeframe, payload=payload_sweep,
                            detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                            lifecycle_state=LifecycleState.ACTIVE,
                            evaluation_context=context,
                            observed_at=curr_bar.expected_close_time,
                            detected_at=curr_bar.expected_close_time,
                            source_bars=sweep_refs, producer=prov_sweep,
                        )
                        records.append(rec_sweep)

                # Equal Lows Pool
                if abs(b1.low.ticks - b2.low.ticks) <= self.tolerance_ticks:
                    bar_refs = [
                        BarReference(
                            instrument_key=b.instrument_key, timeframe=b.timeframe,
                            open_time=b.open_time, expected_close_time=b.expected_close_time,
                            available_at=b.available_at, bar_key=b.bar_key,
                            is_closed=b.is_closed, source_name=b.source_name,
                        )
                        for b in (b1, b2)
                    ]
                    payload = PointEventPayload(primary_level=b1.low, direction=EventDirection.BULLISH)
                    rec = EyeEventRecord.create(
                        family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_POOL_LOW,
                        direction=EventDirection.BULLISH, instrument=context.instrument,
                        timeframe=context.timeframe, payload=payload,
                        detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                        lifecycle_state=LifecycleState.ACTIVE,
                        evaluation_context=context,
                        observed_at=b2.expected_close_time,
                        detected_at=b2.expected_close_time,
                        source_bars=bar_refs, producer=prov,
                    )
                    records.append(rec)

                    if curr_bar.low.ticks < b1.low.ticks and curr_bar.close.ticks > b1.low.ticks:
                        sweep_refs = bar_refs + [
                            BarReference(
                                instrument_key=curr_bar.instrument_key, timeframe=curr_bar.timeframe,
                                open_time=curr_bar.open_time, expected_close_time=curr_bar.expected_close_time,
                                available_at=curr_bar.available_at, bar_key=curr_bar.bar_key,
                                is_closed=curr_bar.is_closed, source_name=curr_bar.source_name,
                            )
                        ]
                        prov_sweep = ProducerProvenance(
                            engine_name="LiquidityDetector",
                            source_file="src/eye/detectors/liquidity.py",
                            source_symbol="LiquidityDetector.detect",
                            source_commit=context.source_revision,
                            producer_version=context.producer_version,
                            rule_id=self.RULE_ID_SWEEP,
                            rule_version=self.RULE_VERSION,
                            authority=AuthorityType.OBSERVATION_ONLY,
                        )
                        payload_sweep = PointEventPayload(primary_level=b1.low, breached_level=curr_bar.low, direction=EventDirection.BULLISH)
                        rec_sweep = EyeEventRecord.create(
                            family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_LOW,
                            direction=EventDirection.BULLISH, instrument=context.instrument,
                            timeframe=context.timeframe, payload=payload_sweep,
                            detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                            lifecycle_state=LifecycleState.ACTIVE,
                            evaluation_context=context,
                            observed_at=curr_bar.expected_close_time,
                            detected_at=curr_bar.expected_close_time,
                            source_bars=sweep_refs, producer=prov_sweep,
                        )
                        records.append(rec_sweep)

        if not records:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.LIQUIDITY_POOL_NOT_CONFIRMED,
                reason="No active equal highs/lows pool or sweep detected",
            ))

        return DetectorResult(
            detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID_POOL, rule_version=self.RULE_VERSION,
            instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
            records=tuple(records), abstentions=tuple(abstentions),
        )
