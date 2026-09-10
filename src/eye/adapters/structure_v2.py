"""StructureEngineV2 Native Engine Adapter for Eye Engine E2A."""

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence

from src.eye.adapters.base import BaseEyeAdapter, quantize_price
from src.eye.adapter_result import AdapterResult, AdapterAbstention, AdapterAbstentionReason, AdapterDiagnostics
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    PointEventPayload,
    StateEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
)


class StructureV2Adapter(BaseEyeAdapter):
    PRODUCER_NAME = "StructureEngineV2"
    PRODUCER_VERSION = "2.0.0"
    RULE_ID = "STRUCTURE_V2_BOS_CLOSE_V1"
    RULE_VERSION = "1.0.0"

    def adapt(
        self,
        native_output: Any,
        source_bars: Sequence[Mapping[str, Any]],
        instrument_identity: Any,
        timeframe: str,
        evaluation_context: Any,
        native_configuration: Optional[Mapping[str, Any]] = None,
        source_revision: str = "",
    ) -> AdapterResult:
        records: List[EyeEventRecord] = []
        abstentions: List[AdapterAbstention] = []
        diagnostics: List[AdapterDiagnostics] = []

        if not isinstance(native_output, dict):
            abstentions.append(AdapterAbstention(
                code=AdapterAbstentionReason.INVALID_NATIVE_OUTPUT,
                reason="Native output must be a dictionary",
            ))
            return AdapterResult(
                producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
                input_identity=instrument_identity, timeframe=timeframe,
                evaluation_as_of=evaluation_context.as_of, records=tuple(records),
                abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            )

        if not source_bars:
            abstentions.append(AdapterAbstention(
                code=AdapterAbstentionReason.SOURCE_BAR_LINEAGE_MISSING,
                reason="Source bars sequence is empty",
            ))
            return AdapterResult(
                producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
                input_identity=instrument_identity, timeframe=timeframe,
                evaluation_as_of=evaluation_context.as_of, records=tuple(records),
                abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            )

        # Convert source bars to BarReferences
        bar_refs: List[BarReference] = []
        for b in source_bars:
            open_t = b.get("open_time") or evaluation_context.as_of
            close_t = b.get("expected_close_time") or evaluation_context.as_of
            avail_t = b.get("available_at") or evaluation_context.as_of
            bar_refs.append(BarReference(
                instrument_key=instrument_identity.instrument_key,
                timeframe=timeframe,
                open_time=open_t,
                expected_close_time=close_t,
                available_at=avail_t,
                bar_key=str(b.get("bar_key") or f"{instrument_identity.instrument_key}:{timeframe}:{open_t.isoformat()}"),
                is_closed=bool(b.get("is_closed", True)),
                source_name=str(b.get("source_name", "DHAN")),
            ))

        prov = ProducerProvenance(
            engine_name=self.PRODUCER_NAME,
            source_file="src/structure/structure_engine_v2.py",
            source_symbol="StructureEngineV2.analyze",
            source_commit=source_revision or "8632791",
            producer_version=self.PRODUCER_VERSION,
            rule_id=self.RULE_ID,
            rule_version=self.RULE_VERSION,
        )

        bos = native_output.get("bos", "NONE")
        last_high = native_output.get("last_swing_high") or native_output.get("last_high")
        last_low = native_output.get("last_swing_low") or native_output.get("last_low")

        if bos == "BULLISH_BOS" and last_high:
            px_val = last_high.get("price") if isinstance(last_high, dict) else last_high
            atom, diag = quantize_price(px_val)
            diagnostics.append(diag)
            payload = PointEventPayload(primary_level=atom, direction=EventDirection.BULLISH)
            rec = EyeEventRecord.create(
                family=EventFamily.STRUCTURE, event_type=EventType.BOS_BULLISH,
                direction=EventDirection.BULLISH, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)
        elif bos == "BEARISH_BOS" and last_low:
            px_val = last_low.get("price") if isinstance(last_low, dict) else last_low
            atom, diag = quantize_price(px_val)
            diagnostics.append(diag)
            payload = PointEventPayload(primary_level=atom, direction=EventDirection.BEARISH)
            rec = EyeEventRecord.create(
                family=EventFamily.STRUCTURE, event_type=EventType.BOS_BEARISH,
                direction=EventDirection.BEARISH, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)

        choch = native_output.get("choch", "NONE")
        if choch == "BULLISH_CHOCH" and last_high:
            px_val = last_high.get("price") if isinstance(last_high, dict) else last_high
            atom, diag = quantize_price(px_val)
            diagnostics.append(diag)
            payload = PointEventPayload(primary_level=atom, direction=EventDirection.BULLISH)
            rec = EyeEventRecord.create(
                family=EventFamily.STRUCTURE, event_type=EventType.CHOCH_BULLISH,
                direction=EventDirection.BULLISH, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)
        elif choch == "BEARISH_CHOCH" and last_low:
            px_val = last_low.get("price") if isinstance(last_low, dict) else last_low
            atom, diag = quantize_price(px_val)
            diagnostics.append(diag)
            payload = PointEventPayload(primary_level=atom, direction=EventDirection.BEARISH)
            rec = EyeEventRecord.create(
                family=EventFamily.STRUCTURE, event_type=EventType.CHOCH_BEARISH,
                direction=EventDirection.BEARISH, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)

        if not records and bos == "NONE" and choch == "NONE":
            abstentions.append(AdapterAbstention(
                code=AdapterAbstentionReason.UNSUPPORTED_NATIVE_EVENT,
                reason="No active BOS or CHOCH signal in native output",
                native_context=str(native_output.get("reason", "")),
            ))

        return AdapterResult(
            producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
            input_identity=instrument_identity, timeframe=timeframe,
            evaluation_as_of=evaluation_context.as_of, records=tuple(records),
            abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            source_revision=source_revision,
        )
