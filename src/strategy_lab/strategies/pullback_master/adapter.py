"""Hash-pinned adapter for authoritative PULLBACK MASTER Pine events.

The original script has not been translated into an unverified Python trading
algorithm.  This adapter consumes a candle-scoped event emitted by that exact
Pine source and maps it without changing its entry, exit, stop, or target.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict, Mapping, Optional

from ...core import OrderBlockConfig, SHARED_TRADING_CORE_TYPES, SharedOrderBlockEngine
from ...shared_pipeline import SharedCorePipeline
from .deployment import PARITY_STATUS, SOURCE_SHA256
from .strategy import PullbackMasterConfig, PullbackMasterStrategyEngine


class PullbackMasterNativeAdapter:
    """Native Strategy Lab adapter; deployment and paper execution stay gated."""

    order_block_engine_type = SharedOrderBlockEngine
    shared_core_types = SHARED_TRADING_CORE_TYPES

    def __init__(
        self,
        config: Optional[PullbackMasterConfig] = None,
        *,
        engine: Optional[PullbackMasterStrategyEngine] = None,
    ) -> None:
        self.engine = engine or PullbackMasterStrategyEngine(config)
        self.pipeline = SharedCorePipeline(self.engine)

    @classmethod
    def build_order_block_engine(
        cls, config: Optional[OrderBlockConfig] = None
    ) -> SharedOrderBlockEngine:
        return cls.order_block_engine_type(config)

    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(context.get("bar"), Mapping):
            return self.engine.evaluate(context)
        pipeline = self.pipeline.advance(context)
        enriched = dict(context)
        enriched["bull_fvg"] = "BULLISH" in pipeline["created"]["fair_value_gaps"]
        result = dict(self.engine.evaluate(enriched))
        reference = self.pipeline.reference_for_level(result.get("target"))
        if reference is not None:
            result.update({
                "exit_reference_type": reference["type"], "exit_reference_id": reference["structure_id"],
                "exit_reference_instrument": reference["security_id"], "exit_reference_timeframe": reference["timeframe"],
                "exit_reference_rule_version": reference["rule_version"],
            })
        if isinstance(context.get("chart_contract"), Mapping):
            result["option_contract"] = deepcopy(dict(context["chart_contract"]))
            result["lot_size"] = int(context["lot_size"])
        pipeline["finalization"] = self.pipeline.finalize(context)
        result["shared_core_pipeline"] = pipeline
        return result

    def serialize(self) -> str:
        return json.dumps({
            "schema_version": 1,
            "engine": json.loads(self.engine.serialize()),
            "pipeline": self.pipeline.snapshot(),
        }, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def deserialize(cls, payload: str) -> "PullbackMasterNativeAdapter":
        value = json.loads(payload)
        if "pipeline" not in value:
            return cls(engine=PullbackMasterStrategyEngine.deserialize(payload))
        engine = PullbackMasterStrategyEngine.deserialize(json.dumps(value["engine"]))
        adapter = cls(engine=engine)
        adapter.pipeline = SharedCorePipeline.restore(engine, value["pipeline"])
        return adapter


class PullbackMasterPineEventAdapter:
    """Map authoritative Pine events into the Strategy Lab decision contract."""

    _ACTIONS = {"BUY", "SELL", "TARGET", "SL", "WAIT"}
    order_block_engine_type = SharedOrderBlockEngine
    shared_core_types = SHARED_TRADING_CORE_TYPES

    @classmethod
    def build_order_block_engine(
        cls, config: Optional[OrderBlockConfig] = None
    ) -> SharedOrderBlockEngine:
        return cls.order_block_engine_type(config)

    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        event = context.get("pine_event")
        if not isinstance(event, Mapping):
            return self._wait("AUTHORITATIVE_PINE_EVENT_REQUIRED")

        source_hash = str(event.get("source_sha256") or "").lower()
        if source_hash != SOURCE_SHA256:
            raise ValueError("PULLBACK_MASTER_SOURCE_HASH_MISMATCH")

        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("PULLBACK_MASTER_EVENT_ID_REQUIRED")

        if event.get("candle_closed") is not True:
            return self._wait(
                "INCOMPLETE_CANDLE_REJECTED",
                evaluation_id=event_id,
                pine_event=event,
            )

        action = str(event.get("action") or "WAIT").upper()
        if action not in self._ACTIONS:
            raise ValueError("PULLBACK_MASTER_ACTION_UNSUPPORTED")

        signal = "BUY" if action == "BUY" else "SELL" if action in {"SELL", "TARGET", "SL"} else "WAIT"
        reason = str(event.get("reason") or f"PINE_{action}")
        result: Dict[str, Any] = {
            "evaluation_id": event_id,
            "signal": signal,
            "pine_action": action,
            "reason": reason,
            "why_trade": event.get("why_trade") if signal != "WAIT" else None,
            "why_not_trade": event.get("why_not_trade") if signal == "WAIT" else None,
            "entry": event.get("entry"),
            "exit": event.get("exit"),
            "stop": event.get("stop"),
            "target": event.get("target"),
            "bar_index": event.get("bar_index"),
            "candle_time": event.get("candle_time"),
            "candle_closed": True,
            "source_sha256": SOURCE_SHA256,
            "parity_status": PARITY_STATUS,
            "strategy_classification": "UNDERLYING_STRATEGY",
            "authoritative_pine_event": deepcopy(dict(event)),
        }
        return result

    @staticmethod
    def _wait(
        reason: str,
        *,
        evaluation_id: str = "pullback-master-no-authoritative-event",
        pine_event: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return {
            "evaluation_id": evaluation_id,
            "signal": "WAIT",
            "pine_action": "WAIT",
            "reason": reason,
            "why_trade": None,
            "why_not_trade": reason,
            "entry": None,
            "exit": None,
            "stop": None,
            "target": None,
            "source_sha256": SOURCE_SHA256,
            "parity_status": PARITY_STATUS,
            "strategy_classification": "UNDERLYING_STRATEGY",
            "authoritative_pine_event": deepcopy(dict(pine_event or {})),
        }
