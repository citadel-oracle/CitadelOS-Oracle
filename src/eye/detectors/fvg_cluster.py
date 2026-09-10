"""Non-Destructive FVG Child & Aggregate Cluster Detector for Eye Engine E2B."""

from datetime import datetime, timezone
from typing import List, Sequence

from src.eye.detectors.base import BaseAtomicDetector
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult, DetectorAbstention, DetectorAbstentionReason
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    ZoneEventPayload,
    RelationshipEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
    AuthorityType,
)


class FVGClusterDetector(BaseAtomicDetector):
    DETECTOR_FAMILY = "IMBALANCE"
    RULE_ID_CHILD = "EYE_FVG_THREE_BAR_V1"
    RULE_ID_AGG = "EYE_FVG_OVERLAP_AGGREGATE_V1"
    RULE_VERSION = "1.0.0"

    def detect(
        self,
        bars: Sequence[DetectorBar],
        context: DetectorContext,
    ) -> DetectorResult:
        records: List[EyeEventRecord] = []
        abstentions: List[DetectorAbstention] = []

        if len(bars) < 3:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.INSUFFICIENT_BARS,
                reason="Need at least 3 bars for FVG detection",
            ))
            return DetectorResult(
                detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID_CHILD, rule_version=self.RULE_VERSION,
                instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
                records=tuple(records), abstentions=tuple(abstentions),
            )

        prov = ProducerProvenance(
            engine_name="FVGClusterDetector",
            source_file="src/eye/detectors/fvg_cluster.py",
            source_symbol="FVGClusterDetector.detect",
            source_commit=context.source_revision,
            producer_version=context.producer_version,
            rule_id=self.RULE_ID_CHILD,
            rule_version=self.RULE_VERSION,
            authority=AuthorityType.OBSERVATION_ONLY,
        )

        child_records: List[EyeEventRecord] = []

        for i in range(len(bars) - 2):
            b1, b2, b3 = bars[i], bars[i+1], bars[i+2]
            if not b3.is_closed or b3.available_at > context.as_of:
                continue

            # Bullish FVG: Low of bar 3 > High of bar 1
            if b3.low.ticks > b1.high.ticks:
                bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in (b1, b2, b3)
                ]
                payload = ZoneEventPayload(lower=b1.high, upper=b3.low, zone_role="IMBALANCE")
                rec = EyeEventRecord.create(
                    family=EventFamily.IMBALANCE, event_type=EventType.FVG_BULLISH,
                    direction=EventDirection.BULLISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.ACTIVE,
                    evaluation_context=context,
                    observed_at=b3.expected_close_time,
                    detected_at=b3.expected_close_time,
                    source_bars=bar_refs, producer=prov,
                )
                child_records.append(rec)

            # Bearish FVG: High of bar 3 < Low of bar 1
            if b3.high.ticks < b1.low.ticks:
                bar_refs = [
                    BarReference(
                        instrument_key=b.instrument_key, timeframe=b.timeframe,
                        open_time=b.open_time, expected_close_time=b.expected_close_time,
                        available_at=b.available_at, bar_key=b.bar_key,
                        is_closed=b.is_closed, source_name=b.source_name,
                    )
                    for b in (b1, b2, b3)
                ]
                payload = ZoneEventPayload(lower=b3.high, upper=b1.low, zone_role="IMBALANCE")
                rec = EyeEventRecord.create(
                    family=EventFamily.IMBALANCE, event_type=EventType.FVG_BEARISH,
                    direction=EventDirection.BEARISH, instrument=context.instrument,
                    timeframe=context.timeframe, payload=payload,
                    detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                    lifecycle_state=LifecycleState.ACTIVE,
                    evaluation_context=context,
                    observed_at=b3.expected_close_time,
                    detected_at=b3.expected_close_time,
                    source_bars=bar_refs, producer=prov,
                )
                child_records.append(rec)

        records.extend(child_records)

        # Derived aggregate event if 2+ child FVGs overlap
        if len(child_records) >= 2:
            child_keys = tuple(r.event_key for r in child_records)
            prov_agg = ProducerProvenance(
                engine_name="FVGClusterDetector",
                source_file="src/eye/detectors/fvg_cluster.py",
                source_symbol="FVGClusterDetector.detect",
                source_commit=context.source_revision,
                producer_version=context.producer_version,
                rule_id=self.RULE_ID_AGG,
                rule_version=self.RULE_VERSION,
                authority=AuthorityType.OBSERVATION_ONLY,
            )
            payload_agg = RelationshipEventPayload(
                parent_event_keys=child_keys,
                relationship_type="CONSECUTIVE_OVERLAP_AGGREGATE",
            )
            all_refs = [b for r in child_records for b in r.source_bars]
            rec_agg = EyeEventRecord.create(
                family=EventFamily.IMBALANCE, event_type=child_records[0].event_type,
                direction=child_records[0].direction, instrument=context.instrument,
                timeframe=context.timeframe, payload=payload_agg,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.ACTIVE,
                evaluation_context=context,
                observed_at=child_records[-1].observed_at,
                detected_at=child_records[-1].detected_at,
                source_bars=all_refs, producer=prov_agg,
            )
            records.append(rec_agg)

        if not records:
            abstentions.append(DetectorAbstention(
                code=DetectorAbstentionReason.REQUIRED_FEATURE_UNAVAILABLE,
                reason="No 3-bar Fair Value Gaps in bar sequence",
            ))

        return DetectorResult(
            detector_family=self.DETECTOR_FAMILY, rule_id=self.RULE_ID_CHILD, rule_version=self.RULE_VERSION,
            instrument=context.instrument, timeframe=context.timeframe, as_of=context.as_of,
            records=tuple(records), abstentions=tuple(abstentions),
        )
