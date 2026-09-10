"""OracleDevPriceActionAnalyzer Native Engine Adapter for Eye Engine E2A."""

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


class OracleDevAdapter(BaseEyeAdapter):
    PRODUCER_NAME = "OracleDevPriceActionAnalyzer"
    PRODUCER_VERSION = "1.0.0"
    RULE_ID = "ORACLE_DEV_PRICE_ACTION_V1"
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
            source_file="src/oracle_development/price_action_analyzer.py",
            source_symbol="OracleDevPriceActionAnalyzer.analyze",
            source_commit=source_revision or "8632791",
            producer_version=self.PRODUCER_VERSION,
            rule_id=self.RULE_ID,
            rule_version=self.RULE_VERSION,
        )

        out_dict = native_output if isinstance(native_output, dict) else {}

        pa_state = out_dict.get("trend") or out_dict.get("state") or out_dict.get("regime")
        if pa_state:
            payload = StateEventPayload(state_code=str(pa_state), effective_from_bar=bar_refs[-1].bar_key)
            direction = EventDirection.BULLISH if "BULL" in str(pa_state).upper() else EventDirection.BEARISH if "BEAR" in str(pa_state).upper() else EventDirection.NEUTRAL
            rec = EyeEventRecord.create(
                family=EventFamily.REGIME, event_type=EventType.TREND_BULLISH if direction == EventDirection.BULLISH else EventType.TREND_BEARISH if direction == EventDirection.BEARISH else EventType.RANGE,
                direction=direction, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.ACTIVE,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)
        else:
            abstentions.append(AdapterAbstention(
                code=AdapterAbstentionReason.UNSUPPORTED_NATIVE_EVENT,
                reason="OracleDev price action analyzer contains no mappable trend/regime state",
            ))

        return AdapterResult(
            producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
            input_identity=instrument_identity, timeframe=timeframe,
            evaluation_as_of=evaluation_context.as_of, records=tuple(records),
            abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            source_revision=source_revision,
        )
