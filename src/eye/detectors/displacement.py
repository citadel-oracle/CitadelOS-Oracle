"""Measurement-Driven Displacement Detector for Eye Engine E2B."""

from datetime import datetime, timezone
from typing import List, Sequence

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


class DisplacementDetector(BaseAtomicDetector):
    DETECTOR_FAMILY = "DISPLACEMENT"
    RULE_ID = "EYE_DISPLACEMENT_ATR_BODY_V1"
    RULE_VERSION = "1.0.0"

    def __init__(self, min_body_ratio: float = 0.7) -> None:
        self.min_body_ratio = min_body_ratio

    def detect(
        self,
        bars: Sequence[DetectorBar],
        context: DetectorContext,
    ) -> DetectorResult:
        records: List[EyeEventRecord] = []
        abstentions: List[DetectorAbstention] = []

        if not bars:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INSUFFICIENT_BARS,
                reason="No bars provided for displacement detection",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        curr_bar = bars[-1]
        if not curr_bar.is_closed or curr_bar.available_at > context.as_of:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INCOMPLETE_BAR,
                reason="Current bar is not closed or available",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        total_range_ticks = max(curr_bar.high.ticks - curr_bar.low.ticks, 1)
        body_ticks = abs(curr_bar.close.ticks - curr_bar.open.ticks)
        body_ratio = body_ticks / float(total_range_ticks)

        if body_ratio >= self.min_body_ratio:
            is_bullish = curr_bar.close.ticks > curr_bar.open.ticks
            direction = EventDirection.BULLISH if is_bullish else EventDirection.BEARISH
            event_type = EventType.DISPLACEMENT_BULLISH if is_bullish else EventType.DISPLACEMENT_BEARISH

            prov = ProducerProvenance(
                engine_name="DisplacementDetector",
                source_file="src/eye/detectors/displacement.py",
                source_symbol="DisplacementDetector.detect",
                source_commit=context.source_revision,
                producer_version=context.producer_version,
                rule_id=self.RULE_ID,
                rule_version=self.RULE_VERSION,
                authority=AuthorityType.OBSERVATION_ONLY,
            )

            bar_refs = [
                BarReference(
                    instrument_key=curr_bar.instrument_key, timeframe=curr_bar.timeframe,
                    open_time=curr_bar.open_time, expected_close_time=curr_bar.expected_close_time,
                    available_at=curr_bar.available_at, bar_key=curr_bar.bar_key,
                    is_closed=curr_bar.is_closed, source_name=curr_bar.source_name,
                )
            ]
            payload = PointEventPayload(primary_level=curr_bar.close, direction=direction)
            rec = EyeEventRecord.create(
                family=EventFamily.DISPLACEMENT, event_type=event_type,
                direction=direction, instrument=context.instrument,
                timeframe=context.timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED,
                evaluation_context=context,
                observed_at=curr_bar.expected_close_time,
                detected_at=curr_bar.expected_close_time,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)
        else:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.REQUIRED_FEATURE_UNAVAILABLE,
                reason=f"Current bar body ratio {body_ratio:.2f} below threshold {self.min_body_ratio:.2f}",
            ))

        return DetectorResult(
            detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID, rule_version=self.RULE_VERSION,
            instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
            records=tuple(records), abstentions=tuple(abstentions),
        )
