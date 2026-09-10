"""BigBelugaVOBEngine Native Engine Adapter for Eye Engine E2A."""

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence

from src.eye.adapters.base import BaseEyeAdapter, quantize_price
from src.eye.adapter_result import AdapterResult, AdapterAbstention, AdapterAbstentionReason, AdapterDiagnostics
from src.eye.contracts import (
    EyeEventRecord,
    BarReference,
    ZoneEventPayload,
    PointEventPayload,
    ProducerProvenance,
    DetectionState,
    LifecycleState,
    EventFamily,
    EventType,
    EventDirection,
)


class BigBelugaAdapter(BaseEyeAdapter):
    PRODUCER_NAME = "BigBelugaVOBEngine"
    PRODUCER_VERSION = "1.0.0"
    RULE_ID = "BIGBELUGA_OB_CLOSE_MITIGATION_V1"
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
            source_file="src/vob/bigbeluga_engine.py",
            source_symbol="BigBelugaVOBEngine.analyze",
            source_commit=source_revision or "8632791",
            producer_version=self.PRODUCER_VERSION,
            rule_id=self.RULE_ID,
            rule_version=self.RULE_VERSION,
        )

        # Handle list of OBZone dataclasses / dicts or dict wrapper from analyze_all
        zones = []
        if isinstance(native_output, list):
            zones = native_output
        elif isinstance(native_output, dict):
            zones = native_output.get("zones", [])
            tf_data = native_output.get("timeframes", {}).get(timeframe, {})
            if isinstance(tf_data, dict):
                zones.extend(tf_data.get("all_bull_obs", []))
                zones.extend(tf_data.get("all_bear_obs", []))
            # Also extract top-level nearest_support / nearest_resistance
            sup = native_output.get("nearest_support")
            if isinstance(sup, dict) and sup.get("price"):
                zones.append({"top": sup["price"] + 5.0, "bottom": sup["price"] - 5.0, "is_bullish": True, "mitigated": False})
            res = native_output.get("nearest_resistance")
            if isinstance(res, dict) and res.get("price"):
                zones.append({"top": res["price"] + 5.0, "bottom": res["price"] - 5.0, "is_bullish": False, "mitigated": False})

        for z in zones:
            if hasattr(z, "top") and hasattr(z, "btm"):
                top_val, bot_val = getattr(z, "top"), getattr(z, "btm")
                is_bullish = getattr(z, "bull", True)
                mitigated = getattr(z, "is_mitigated", False)
                broken = getattr(z, "is_broken", False)
            elif hasattr(z, "top"):
                top_val, bot_val = getattr(z, "top"), getattr(z, "bottom", getattr(z, "btm", None))
                is_bullish = getattr(z, "is_bullish", getattr(z, "bull", True))
                mitigated = getattr(z, "mitigated", getattr(z, "is_mitigated", False))
                broken = getattr(z, "broken", getattr(z, "is_broken", False))
            elif isinstance(z, dict):
                top_val = z.get("top")
                bot_val = z.get("bottom") or z.get("btm")
                is_bullish = z.get("is_bullish", z.get("bull", True))
                mitigated = z.get("mitigated", z.get("is_mitigated", False))
                broken = z.get("broken", z.get("is_broken", False))
            else:
                continue

            if top_val is None or bot_val is None:
                continue

            lower_atom, diag_l = quantize_price(min(top_val, bot_val))
            upper_atom, diag_u = quantize_price(max(top_val, bot_val))
            diagnostics.extend([diag_l, diag_u])

            event_type = EventType.ORDER_BLOCK_BULLISH if is_bullish else EventType.ORDER_BLOCK_BEARISH
            direction = EventDirection.BULLISH if is_bullish else EventDirection.BEARISH
            lifecycle = LifecycleState.MITIGATED if mitigated else LifecycleState.BROKEN if broken else LifecycleState.ACTIVE

            payload = ZoneEventPayload(
                lower=lower_atom, upper=upper_atom,
                zone_role="DEMAND_ZONE" if is_bullish else "SUPPLY_ZONE",
            )
            rec = EyeEventRecord.create(
                family=EventFamily.ZONE, event_type=event_type,
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
                reason="No valid order block zones detected in native output",
            ))

        return AdapterResult(
            producer=self.PRODUCER_NAME, producer_version=self.PRODUCER_VERSION,
            input_identity=instrument_identity, timeframe=timeframe,
            evaluation_as_of=evaluation_context.as_of, records=tuple(records),
            abstentions=tuple(abstentions), diagnostics=tuple(diagnostics),
            source_revision=source_revision,
        )
