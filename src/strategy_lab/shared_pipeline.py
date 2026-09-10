"""Deterministic orchestration of the frozen Strategy Lab shared engines."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from .core import (
    FairValueGapBar,
    FairValueGapEngine,
    LiquidityBar,
    LiquidityZoneEngine,
    OrderBlockBar,
)
from .core.atr import TradingViewATR
from .state_truth import stable_structure_id


def _market_structure_engine_type():
    # Lazy import prevents the Pullback adapter from recursively importing the
    # BREAKOUT package while both deployment modules are being registered.
    from .strategies.breakout_main.market_structure import MarketStructureEngine

    return MarketStructureEngine


class SharedCorePipeline:
    """Advance each shared subsystem once before strategy-specific evaluation."""

    SCHEMA_VERSION = 1
    MAX_PROCESSED_CANDLES = 5000

    def __init__(
        self,
        strategy: Any,
        *,
        market_structure: Any | None = None,
        fair_value_gaps: FairValueGapEngine | None = None,
        liquidity: LiquidityZoneEngine | None = None,
    ) -> None:
        self.strategy = strategy
        self.market_structure = market_structure or _market_structure_engine_type()()
        self.order_blocks = strategy.order_blocks
        self.fair_value_gaps = fair_value_gaps or getattr(strategy, "fair_value_gaps", None) or FairValueGapEngine()
        self.liquidity = liquidity or getattr(strategy, "liquidity", None) or LiquidityZoneEngine()
        if hasattr(strategy, "fair_value_gaps"):
            strategy.fair_value_gaps = self.fair_value_gaps
        if hasattr(strategy, "liquidity"):
            strategy.liquidity = self.liquidity
        self._processed: list[str] = []
        self._processed_set: set[str] = set()
        self._sequence = 0
        self._origins: dict[int, OrderBlockBar] = {}
        self._order_block_atr = TradingViewATR(200)
        self._order_block_atr_values: dict[int, float | None] = {}
        self._bar_times: list[int] = []
        self._pending_mitigation: dict[str, OrderBlockBar] = {}
        self._structure_catalog: dict[str, dict[str, Any]] = {}

    def advance(self, context: Mapping[str, Any]) -> dict[str, Any]:
        rows = context.get("completed_candles")
        candidates = list(rows) if isinstance(rows, list) else []
        current = context.get("bar")
        current_key: str | None = None
        if isinstance(current, Mapping):
            candidates.append(current)
            current_key = self._timestamp(current).isoformat()
        ordered: dict[str, Mapping[str, Any]] = {}
        for raw in candidates:
            if not isinstance(raw, Mapping):
                continue
            timestamp = self._timestamp(raw)
            ordered[timestamp.isoformat()] = raw

        stage_counts = {
            "market_structure": 0,
            "order_blocks": 0,
            "fair_value_gaps": 0,
            "liquidity": 0,
        }
        created = {"order_blocks": [], "fair_value_gaps": [], "liquidity": []}
        last_structure: dict[str, Any] | None = None
        for candle_key in sorted(ordered):
            if candle_key in self._processed_set:
                continue
            raw = ordered[candle_key]
            timestamp = self._timestamp(raw)
            time_ms = int(timestamp.timestamp() * 1000)
            self._sequence += 1
            logical_index = self._sequence
            shared_bar = {
                "index": logical_index,
                "bar_index": logical_index,
                "timestamp": timestamp.isoformat(),
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume") or 0.0),
            }
            origin = OrderBlockBar(
                time=time_ms,
                open=shared_bar["open"],
                high=shared_bar["high"],
                low=shared_bar["low"],
                close=shared_bar["close"],
                volume=shared_bar["volume"],
            )
            self._origins[logical_index] = origin
            self._order_block_atr_values[logical_index] = self._order_block_atr.update(
                origin.high, origin.low, origin.close
            )
            previous_structure_start = self.market_structure.state.start
            bullish_origin = self._find_order_block_origin(use_max=False)
            bearish_origin = self._find_order_block_origin(use_max=True)
            previous_event_count = len(self.market_structure.events)
            last_structure = self.market_structure.update(shared_bar)
            stage_counts["market_structure"] += 1

            if candle_key == current_key:
                # The strategy consumes an active block on the breakout/touch
                # candle before Pine mutates that block's mitigation state.
                self._pending_mitigation[candle_key] = origin
            else:
                self.order_blocks.mitigate(origin, confirmed=True)
            for event in self.market_structure.events[previous_event_count:]:
                bull = (
                    event.direction == "BEARISH"
                    if previous_structure_start == 1
                    else event.direction == "BULLISH"
                )
                event_origin = bullish_origin if bull else bearish_origin
                event_atr = self._order_block_atr_values.get(
                    next(key for key, value in self._origins.items() if value is event_origin)
                )
                if event_atr is None:
                    continue
                boundary = (
                    min(event_origin.low + event_atr, event_origin.high)
                    if bull
                    else max(event_origin.high - event_atr, event_origin.low)
                )
                block = self.order_blocks.create_block(
                    bull=bull,
                    boundary=boundary,
                    origin=event_origin,
                )
                created["order_blocks"].append({
                    "event": event.event,
                    "direction": event.direction,
                    "structure_level": event.level,
                    "loc": block.loc,
                })
                self._catalog_structure(
                    structure_type="ORDER_BLOCK", direction="BULLISH" if block.bull else "BEARISH",
                    origin=block.loc, confirmation=time_ms, lower=block.btm, upper=block.top,
                    context=context,
                )
            self.order_blocks.remove_overlaps()
            self.order_blocks.observe_latest_states()
            self._bar_times.append(time_ms)
            self._bar_times = self._bar_times[-3:]
            if len(self._bar_times) == 3:
                self.order_blocks.update_activity(*self._bar_times)
            stage_counts["order_blocks"] += 1

            fvg = self.fair_value_gaps.update(FairValueGapBar(
                logical_index, time_ms, shared_bar["open"], shared_bar["high"],
                shared_bar["low"], shared_bar["close"], shared_bar["volume"],
            ))
            created["fair_value_gaps"].extend(fvg.created)
            if fvg.created:
                for direction in fvg.created:
                    collection = self.fair_value_gaps.bullish if direction == "BULLISH" else self.fair_value_gaps.bearish
                    if collection:
                        gap = collection[0]
                        self._catalog_structure(
                            structure_type="FVG", direction=direction, origin=gap.loc,
                            confirmation=time_ms, lower=gap.btm, upper=gap.top, context=context,
                        )
            stage_counts["fair_value_gaps"] += 1
            liquidity = self.liquidity.update(LiquidityBar(
                logical_index, time_ms, shared_bar["open"], shared_bar["high"],
                shared_bar["low"], shared_bar["close"], shared_bar["volume"],
            ))
            if liquidity.created:
                created["liquidity"].append(liquidity.created)
                zone = self.liquidity.zones[0] if self.liquidity.zones else None
                if zone is not None:
                    self._catalog_structure(
                        structure_type="LIQUIDITY", direction=str(zone.side), origin=zone.pivot_time,
                        confirmation=time_ms, lower=min(zone.base, zone.outer), upper=max(zone.base, zone.outer),
                        context=context,
                    )
            created["liquidity"].extend(liquidity.grabbed)
            stage_counts["liquidity"] += 1
            self._advance_structure_catalog(shared_bar, context)
            self._remember(candle_key)

        return {
            "status": "ADVANCED" if any(stage_counts.values()) else "ALREADY_PROCESSED",
            "processed_candles": stage_counts["market_structure"],
            "stage_counts": stage_counts,
            "created": created,
            "market_structure": last_structure or self.market_structure._result(self._sequence, processed=False),
            "order_blocks": {"bullish": len(self.order_blocks.bullish), "bearish": len(self.order_blocks.bearish)},
            "fair_value_gaps": {"bullish": len(self.fair_value_gaps.bullish), "bearish": len(self.fair_value_gaps.bearish)},
            "liquidity_zones": len(self.liquidity.zones),
        }

    def finalize(self, context: Mapping[str, Any]) -> dict[str, Any]:
        """Apply same-bar Order Block lifecycle mutations after evaluation."""

        current = context.get("bar")
        if not isinstance(current, Mapping):
            return {"status": "NO_CURRENT_BAR", "mitigated": []}
        candle_key = self._timestamp(current).isoformat()
        origin = self._pending_mitigation.pop(candle_key, None)
        if origin is None:
            return {"status": "ALREADY_FINALIZED", "mitigated": []}
        mitigated = self.order_blocks.mitigate(origin, confirmed=True) or []
        self.order_blocks.remove_overlaps()
        self.order_blocks.observe_latest_states()
        return {"status": "FINALIZED", "mitigated": mitigated}

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "market_structure": self.market_structure.snapshot(),
            "fair_value_gaps": json.loads(self.fair_value_gaps.serialize()),
            "liquidity": json.loads(self.liquidity.serialize()),
            "processed": list(self._processed),
            "sequence": self._sequence,
            "origins": {str(key): value.__dict__ for key, value in self._origins.items()},
            "order_block_atr": self._order_block_atr.snapshot(),
            "order_block_atr_values": {
                str(key): value for key, value in self._order_block_atr_values.items()
            },
            "bar_times": list(self._bar_times),
            "pending_mitigation": {
                key: value.__dict__ for key, value in self._pending_mitigation.items()
            },
            "structure_catalog": deepcopy(self._structure_catalog),
        }

    @classmethod
    def restore(cls, strategy: Any, value: Mapping[str, Any]) -> "SharedCorePipeline":
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported shared-core pipeline schema")
        pipeline = cls(
            strategy,
            market_structure=_market_structure_engine_type().restore(value["market_structure"]),
            fair_value_gaps=FairValueGapEngine.deserialize(json.dumps(value["fair_value_gaps"])),
            liquidity=LiquidityZoneEngine.deserialize(json.dumps(value["liquidity"])),
        )
        pipeline._processed = [str(item) for item in value.get("processed", [])][-cls.MAX_PROCESSED_CANDLES:]
        pipeline._processed_set = set(pipeline._processed)
        pipeline._sequence = int(value.get("sequence") or 0)
        pipeline._origins = {
            int(key): OrderBlockBar(**row) for key, row in dict(value.get("origins") or {}).items()
        }
        pipeline._order_block_atr = TradingViewATR.restore(
            value.get("order_block_atr") or {"length": 200}
        )
        pipeline._order_block_atr_values = {
            int(key): None if item is None else float(item)
            for key, item in dict(value.get("order_block_atr_values") or {}).items()
        }
        pipeline._bar_times = [int(item) for item in value.get("bar_times", [])][-3:]
        pipeline._pending_mitigation = {
            str(key): OrderBlockBar(**row)
            for key, row in dict(value.get("pending_mitigation") or {}).items()
        }
        pipeline._structure_catalog = deepcopy(dict(value.get("structure_catalog") or {}))
        return pipeline

    def reference_for_level(self, level: Any, *, structure_type: str = "ORDER_BLOCK") -> dict[str, Any] | None:
        try:
            price = float(level)
        except (TypeError, ValueError):
            return None
        matches = [
            row for row in self._structure_catalog.values()
            if row.get("type") == structure_type and row.get("state") in {"CONFIRMED", "ACTIVE", "TOUCHED"}
            and float(row["lower_bound"]) - 1e-9 <= price <= float(row["upper_bound"]) + 1e-9
        ]
        return deepcopy(max(matches, key=lambda row: str(row.get("confirmation_timestamp") or ""))) if matches else None

    def certify_source_data(self, context: Mapping[str, Any]) -> int:
        readiness = context.get("data_readiness")
        checksum = readiness.get("reservoir_checksum") if isinstance(readiness, Mapping) else None
        if not checksum:
            return 0
        security_id = str(context.get("contract") or context.get("symbol") or "NIFTY")
        timeframe = str(context.get("timeframe") or "UNKNOWN")
        updated = 0
        for row in self._structure_catalog.values():
            if row.get("security_id") == security_id and row.get("timeframe") == timeframe and row.get("source_data_checksum") is None:
                row["source_data_checksum"] = str(checksum)
                updated += 1
        return updated

    def _catalog_structure(self, *, structure_type: str, direction: str, origin: int, confirmation: int,
                           lower: float, upper: float, context: Mapping[str, Any]) -> None:
        security_id = str(context.get("contract") or context.get("symbol") or "NIFTY")
        timeframe = str(context.get("timeframe") or "UNKNOWN")
        origin_timestamp = datetime.fromtimestamp(origin / 1000, tz=self._timestamp({"timestamp": context.get("timestamp")}).tzinfo).isoformat()
        structure_id = stable_structure_id(
            security_id=security_id, timeframe=timeframe, origin_timestamp=origin_timestamp,
            structure_type=structure_type, direction=direction, rule_version="SHARED_CORE_V1",
        )
        self._structure_catalog.setdefault(structure_id, {
            "structure_id": structure_id, "instrument_scope": str(context.get("symbol") or context.get("underlying") or "NIFTY"),
            "security_id": security_id, "expiry": (context.get("chart_contract") or {}).get("expiry") if isinstance(context.get("chart_contract"), Mapping) else None,
            "timeframe": timeframe, "type": structure_type, "direction": direction,
            "origin_candle": origin_timestamp,
            "confirmation_candle": datetime.fromtimestamp(confirmation / 1000, tz=self._timestamp({"timestamp": context.get("timestamp")}).tzinfo).isoformat(),
            "lower_bound": float(lower), "upper_bound": float(upper),
            "creation_timestamp": datetime.fromtimestamp(confirmation / 1000, tz=self._timestamp({"timestamp": context.get("timestamp")}).tzinfo).isoformat(),
            "confirmation_timestamp": datetime.fromtimestamp(confirmation / 1000, tz=self._timestamp({"timestamp": context.get("timestamp")}).tzinfo).isoformat(),
            "state": "ACTIVE", "touch_count": 0, "first_touch": None, "last_touch": None,
            "mitigation_state": False, "invalidation_state": False, "expiry_state": False,
            "source_data_checksum": (context.get("data_readiness") or {}).get("reservoir_checksum") if isinstance(context.get("data_readiness"), Mapping) else None,
            "rule_version": "SHARED_CORE_V1",
        })

    def _advance_structure_catalog(self, bar: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        security_id = str(context.get("contract") or context.get("symbol") or "NIFTY")
        timeframe = str(context.get("timeframe") or "UNKNOWN")
        timestamp = str(bar["timestamp"])
        active_origins = {
            "ORDER_BLOCK": {item.loc for item in (*self.order_blocks.bullish, *self.order_blocks.bearish)},
            "FVG": {item.loc for item in (*self.fair_value_gaps.bullish, *self.fair_value_gaps.bearish)},
            "LIQUIDITY": {item.pivot_time for item in self.liquidity.zones if not item.grabbed},
        }
        for row in self._structure_catalog.values():
            if row.get("security_id") != security_id or row.get("timeframe") != timeframe:
                continue
            readiness = context.get("data_readiness")
            if row.get("source_data_checksum") is None and isinstance(readiness, Mapping):
                row["source_data_checksum"] = readiness.get("reservoir_checksum")
            if row.get("state") in {"MITIGATED", "INVALIDATED", "EXPIRED"}:
                continue
            expiry = row.get("expiry")
            if expiry and str(expiry) < timestamp[:10]:
                row.update({"state": "EXPIRED", "expiry_state": True})
                continue
            if timestamp > str(row.get("confirmation_timestamp") or ""):
                touched = float(bar["high"]) >= float(row["lower_bound"]) and float(bar["low"]) <= float(row["upper_bound"])
                if touched:
                    row["touch_count"] = int(row.get("touch_count") or 0) + 1
                    row["first_touch"] = row.get("first_touch") or timestamp
                    row["last_touch"] = timestamp
                    row["state"] = "TOUCHED"
            origin_ms = int(self._timestamp({"timestamp": row["origin_candle"]}).timestamp() * 1000)
            if origin_ms not in active_origins.get(str(row.get("type")), set()):
                mitigated = int(row.get("touch_count") or 0) > 0
                row["state"] = "MITIGATED" if mitigated else "INVALIDATED"
                row["mitigation_state"] = mitigated
                row["invalidation_state"] = not mitigated

    def _remember(self, candle_key: str) -> None:
        self._processed.append(candle_key)
        self._processed_set.add(candle_key)
        while len(self._processed) > self.MAX_PROCESSED_CANDLES:
            removed = self._processed.pop(0)
            self._processed_set.discard(removed)
        if len(self._origins) > self.MAX_PROCESSED_CANDLES:
            for key in sorted(self._origins)[:-self.MAX_PROCESSED_CANDLES]:
                del self._origins[key]
                self._order_block_atr_values.pop(key, None)

    def _find_order_block_origin(self, *, use_max: bool) -> OrderBlockBar:
        """Pine ``find(..., useob=true)`` over the current retained history."""

        current = self._sequence
        origin_index = self.market_structure.state.loc
        if origin_index is None or origin_index not in self._origins:
            return self._origins[current]
        distance = current - origin_index
        end = distance - 1 if distance - 1 > 0 else distance
        selected = 0
        maximum = 0.0
        minimum = 99_999_999.0
        for offset in range(0, max(0, end) + 1):
            candidate = self._origins.get(current - offset)
            if candidate is None:
                continue
            if use_max:
                maximum = max(candidate.high, maximum)
                if maximum == candidate.high:
                    minimum = candidate.low
                    selected = offset
            else:
                minimum = min(candidate.low, minimum)
                if minimum == candidate.low:
                    maximum = candidate.high
                    selected = offset
        chosen = self._origins.get(current - selected, self._origins[current])
        previous = self._origins.get(current - selected - 1)
        if previous is not None:
            if use_max and previous.high > chosen.high:
                chosen = previous
            elif not use_max and previous.low < chosen.low:
                chosen = previous
        return chosen

    @staticmethod
    def _timestamp(raw: Mapping[str, Any]) -> datetime:
        value = raw.get("timestamp", raw.get("time"))
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
