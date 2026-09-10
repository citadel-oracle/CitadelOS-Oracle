"""Atomic Swing State Detector for Eye Engine E2B."""

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


class SwingStateDetector(BaseAtomicDetector):
    DETECTOR_FAMILY = "STRUCTURE"
    RULE_ID = "EYE_SWING_FRACTAL_L2_R2_V1"
    RULE_VERSION = "1.0.0"

    def __init__(self, left_bars: int = 2, right_bars: int = 2) -> None:
        self.left_bars = left_bars
        self.right_bars = right_bars

    def detect(
        self,
        bars: Sequence[DetectorBar],
        context: DetectorContext,
    ) -> DetectorResult:
        records: List[EyeEventRecord] = []
        abstentions: List[DetectorAbstention] = []

        min_len = self.left_bars + 1 + self.right_bars
        if len(bars) < min_len:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INSUFFICIENT_BARS,
                reason=f"Need at least {min_len} bars for L={self.left_bars}, R={self.right_bars} swing detection",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        prov = ProducerProvenance(
            engine_name="SwingStateDetector",
            source_file="src/eye/detectors/swing_state.py",
            source_symbol="SwingStateDetector.detect",
            source_commit=context.source_revision,
            producer_version=context.producer_version,
            rule_id=self.RULE_ID,
            rule_version=self.RULE_VERSION,
            authority=AuthorityType.OBSERVATION_ONLY,
        )

        for i in range(self.left_bars, len(bars) - self.right_bars):
            pivot_bar = bars[i]

            # Right-side confirmation bar
            confirm_bar = bars[i + self.right_bars]
            if not confirm_bar.is_closed or confirm_bar.available_at > context.as_of:
                continue

            # Swing High Check
            is_high = True
            for k in range(i - self.left_bars, i + self.right_bars + 1):
                if k != i and bars[k].high.ticks >= pivot_bar.high.ticks:
                    is_high = False
                    break

            if is_high:
                source_bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in bars[i - self.left_bars : i + self.right_bars + 1]
                ]
                payload = PointEventPayload(primary_level=pivot_bar.high, direction=EventDirection.BEARISH)
                rec = EyeEventRecord.create(
                    family=EventFamily.STRUCTURE, event_type=EventType.SWING_HIGH,
                    direction=EventDirection.BEARISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.ACTIVE,
                    evaluation_context=context,
                    observed_at=pivot_bar.expected_close_time,
                    detected_at=confirm_bar.expected_close_time,
                    source_bars=source_bar_refs, producer=prov,
                )
                records.append(rec)

            # Swing Low Check
            is_low = True
            for k in range(i - self.left_bars, i + self.right_bars + 1):
                if k != i and bars[k].low.ticks <= pivot_bar.low.ticks:
                    is_low = False
                    break

            if is_low:
                source_bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in bars[i - self.left_bars : i + self.right_bars + 1]
                ]
                payload = PointEventPayload(primary_level=pivot_bar.low, direction=EventDirection.BULLISH)
                rec = EyeEventRecord.create(
                    family=EventFamily.STRUCTURE, event_type=EventType.SWING_LOW,
                    direction=EventDirection.BULLISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.ACTIVE,
                    evaluation_context=context,
                    observed_at=pivot_bar.expected_close_time,
                    detected_at=confirm_bar.expected_close_time,
                    source_bars=source_bar_refs, producer=prov,
                )
                records.append(rec)

        if not records:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.SWING_NOT_CONFIRMED,
                reason="No confirmed swing high or low in bar sequence",
            ))

        return DetectorResult(
            detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID, rule_version=self.RULE_VERSION,
            instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
            records=tuple(records), abstentions=tuple(abstentions),
        )
