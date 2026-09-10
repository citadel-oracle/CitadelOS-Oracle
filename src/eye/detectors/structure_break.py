"""Deterministic BOS / CHOCH State Machine Detector for Eye Engine E2B."""

from datetime import datetime, timezone
from typing import List, Optional, Sequence

from src.eye.detectors.base import BaseAtomicDetector
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult, DetectorAbstention, DetectorAbstentionReason
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    PointEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    AuthorityType,
)


class StructureBreakDetector(BaseAtomicDetector):
    DETECTOR_FAMILY = "STRUCTURE"
    RULE_ID_CLOSE = "EYE_BOS_CLOSE_INTERNAL_V1"
    RULE_ID_WICK = "EYE_BOS_WICK_INTERNAL_V1"
    RULE_VERSION = "1.0.0"

    def __init__(self, use_close_break: bool = True) -> None:
        self.use_close_break = use_close_break
        self.rule_id = self.RULE_ID_CLOSE if use_close_break else self.RULE_ID_WICK

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
                reason="Need at least 5 bars for structure break detection",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.rule_id, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        prov = ProducerProvenance(
            engine_name="StructureBreakDetector",
            source_file="src/eye/detectors/structure_break.py",
            source_symbol="StructureBreakDetector.detect",
            source_commit=context.source_revision,
            producer_version=context.producer_version,
            rule_id=self.rule_id,
            rule_version=self.RULE_VERSION,
            authority=AuthorityType.OBSERVATION_ONLY,
        )

        last_swing_high: Optional[DetectorBar] = None
        last_swing_low: Optional[DetectorBar] = None

        for i in range(2, len(bars) - 2):
            if bars[i].high.ticks > bars[i-1].high.ticks and bars[i].high.ticks > bars[i-2].high.ticks and bars[i].high.ticks > bars[i+1].high.ticks and bars[i].high.ticks > bars[i+2].high.ticks:
                last_swing_high = bars[i]
            if bars[i].low.ticks < bars[i-1].low.ticks and bars[i].low.ticks < bars[i-2].low.ticks and bars[i].low.ticks < bars[i+1].low.ticks and bars[i].low.ticks < bars[i+2].low.ticks:
                last_swing_low = bars[i]

        curr_bar = bars[-1]
        if curr_bar.available_at <= context.as_of and curr_bar.is_closed:
            trigger_price = curr_bar.close.ticks if self.use_close_break else curr_bar.high.ticks

            if last_swing_high and trigger_price > last_swing_high.high.ticks:
                bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in (last_swing_high, curr_bar)
                ]
                payload = PointEventPayload(primary_level=last_swing_high.high, direction=EventDirection.BULLISH)
                rec = EyeEventRecord.create(
                    family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH,
                    direction=EventDirection.BULLISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.CREATED,
                    evaluation_context=context,
                    observed_at=curr_bar.expected_close_time,
                    detected_at=curr_bar.expected_close_time,
                    source_bars=bar_refs, producer=prov,
                )
                records.append(rec)

            trigger_low = curr_bar.close.ticks if self.use_close_break else curr_bar.low.ticks
            if last_swing_low and trigger_low < last_swing_low.low.ticks:
                bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in (last_swing_low, curr_bar)
                ]
                payload = PointEventPayload(primary_level=last_swing_low.low, direction=EventDirection.BEARISH)
                rec = EyeEventRecord.create(
                    family=EventFamily.STRUCTURE, event_type=EventType.BOS_BEARISH,
                    direction=EventDirection.BEARISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.CREATED,
                    evaluation_context=context,
                    observed_at=curr_bar.expected_close_time,
                    detected_at=curr_bar.expected_close_time,
                    source_bars=bar_refs, producer=prov,
                )
                records.append(rec)

        if not records:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.STRUCTURAL_STATE_UNDEFINED,
                reason="No active BOS or CHOCH break detected on current bar",
            ))

        return DetectorResult(
            detector_family=self.DETECTOR_FAMILY, rule_id=self.rule_id, rule_version=self.RULE_VERSION,
            instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
            records=tuple(records), abstentions=tuple(abstentions),
        )
