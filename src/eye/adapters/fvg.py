"""FVGEngine Native Engine Adapter for Eye Engine E2A."""

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence

from src.eye.adapters.base import BaseEyeAdapter, quantize_price
from src.eye.adapter_result import AdapterResult, AdapterAbstention, AdapterAbstentionReason, AdapterDiagnostics
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    ZoneEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
)


class FVGAdapter(BaseEyeAdapter):
    PRODUCER_NAME = "FVGEngine"
    PRODUCER_VERSION = "1.0.0"
    RULE_ID = "FVG_NATIVE_THREE_BAR_V1"
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
            source_file="src/fvg/fvg_engine.py",
            source_symbol="FVGEngine.analyze",
            source_commit=source_revision or "8632791",
            producer_version=self.PRODUCER_VERSION,
            rule_id=self.RULE_ID,
            rule_version=self.RULE_VERSION,
        )

        fvgs = []
        if isinstance(native_output, list):
            fvgs = native_output
        elif isinstance(native_output, dict):
            fvgs = native_output.get("fvgs", [])
            # Support single summary dict from FVGEngine.analyze()
            if not fvgs and "gap_high" in native_output and "gap_low" in native_output:
                fvgs = [native_output]

        for fvg in fvgs:
            if isinstance(fvg, dict):
                top_val = fvg.get("top") or fvg.get("gap_high")
                bot_val = fvg.get("bottom") or fvg.get("gap_low")
                is_bullish = fvg.get("is_bullish", fvg.get("bias") == "BULLISH" or "BULLISH" in str(fvg.get("type", "")))
                mitigated = fvg.get("mitigated", fvg.get("filled", False))
            else:
                top_val = getattr(fvg, "top", getattr(fvg, "gap_high", None))
                bot_val = getattr(fvg, "bottom", getattr(fvg, "gap_low", None))
                is_bullish = getattr(fvg, "is_bullish", True)
                mitigated = getattr(fvg, "mitigated", getattr(fvg, "filled", False))

            if top_val is None or bot_val is None:
                continue

            lower_atom, diag_l = quantize_price(min(top_val, bot_val))
            upper_atom, diag_u = quantize_price(max(top_val, bot_val))
            diagnostics.extend([diag_l, diag_u])

            event_type = EventType.FVG_BULLISH if is_bullish else EventType.FVG_BEARISH
            direction = EventDirection.BULLISH if is_bullish else EventDirection.BEARISH
            lifecycle = LifecycleState.MITIGATED if mitigated else LifecycleState.ACTIVE

            payload = ZoneEventPayload(
                lower=lower_atom, upper=upper_atom,
                zone_role="IMBALANCE",
            )
            rec = EyeEventRecord.create(
                family=EventFamily.IMBALANCE, event_type=event_type,
                direction=direction, instrument=instrument_identity,
                timeframe=timeframe, payload=payload,
                detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=lifecycle,
                evaluation_context=evaluation_context,
                observed_at=evaluation_context.as_of,
                detected_at=evaluation_context.as_of,
                source_bars=bar_refs, producer=prov,
            )
            records.append(rec)

        if not records:
            abstentions.append(AdapterAbstention(
                code=AdapterAbstentionReason.UNSUPPORTED_NATIVE_EVENT,
                reason="No active Fair Value Gaps in native output",
            ))

        return AdapterResult(
            producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
            input_identity=instrument_identity, timeframe=timeframe,
            evaluation_as_of=evaluation_context.as_of, records=tuple(records),
            abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            source_revision=source_revision,
        )
