"""BREAKOUT MAIN adapters; deployment remains explicitly gated."""

import json
from copy import deepcopy
from typing import Dict, Mapping, Optional

from ...core import OrderBlockConfig, SHARED_TRADING_CORE_TYPES, SharedOrderBlockEngine
from ...paper_engine import InstitutionalPaperTradingEngine
from ...shared_pipeline import SharedCorePipeline
from .strategy import BreakoutMainConfig, BreakoutMainStrategyEngine


def _status(component: str):
    return {
        "status": "NOT_IMPLEMENTED",
        "reason": "NOT_IMPLEMENTED",
        "component": component,
        "paper_execution": False,
        "broker_submission": False,
        "live_trading_enabled": False,
    }


class BreakoutMainSignalEngine:
    shared_core_types = SHARED_TRADING_CORE_TYPES

    def __init__(self, config: Optional[BreakoutMainConfig] = None, *, engine: Optional[BreakoutMainStrategyEngine] = None):
        self.engine = engine or BreakoutMainStrategyEngine(config)
        self.pipeline = SharedCorePipeline(self.engine)

    def evaluate(self, context):
        if not isinstance(context.get("bar"), Mapping):
            return self.engine.evaluate(context)
        pipeline = self.pipeline.advance(context)
        result = dict(self.engine.evaluate(context))
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
    def deserialize(cls, payload: str) -> "BreakoutMainSignalEngine":
        value = json.loads(payload)
        if "pipeline" not in value:
            return cls(engine=BreakoutMainStrategyEngine.deserialize(payload))
        engine = BreakoutMainStrategyEngine.deserialize(json.dumps(value["engine"]))
        adapter = cls(engine=engine)
        adapter.pipeline = SharedCorePipeline.restore(engine, value["pipeline"])
        return adapter


class BreakoutMainOrderBlockAdapter:
    """Strategy boundary around the canonical shared Order Block engine."""

    order_block_engine_type = SharedOrderBlockEngine
    shared_core_types = SHARED_TRADING_CORE_TYPES

    @classmethod
    def build_order_block_engine(
        cls, config: Optional[OrderBlockConfig] = None
    ) -> SharedOrderBlockEngine:
        return cls.order_block_engine_type(config)


class BreakoutMainExecutionAdapter:
    """Lazy bridge to the existing Strategy Lab paper engine; never a broker."""

    def __init__(self) -> None:
        self._engines: Dict[str, InstitutionalPaperTradingEngine] = {}

    def process(self, *, evaluation, context, workspace):
        if str(evaluation.get("signal") or "WAIT").upper() == "WAIT":
            return {
                "status": "NO_ACTION", "reason": "STRATEGY_WAIT", "paper_only": True,
                "paper_state_mutated": False, "broker_submission": False,
                "live_trading_enabled": False,
            }
        key = str(workspace.root)
        engine = self._engines.get(key)
        if engine is None:
            metadata = workspace.read("metadata")
            if not metadata:
                return {**_status("EXECUTION_ADAPTER"), "reason": "STRATEGY_METADATA_REQUIRED"}
            engine = InstitutionalPaperTradingEngine.from_metadata(metadata=metadata, workspace=workspace)
            self._engines[key] = engine
        return engine.process(evaluation=evaluation, context=context, workspace=workspace)

    def finalize_decision_lineage(self, *, journal_id, replay_id, execution):
        for engine in self._engines.values():
            engine.finalize_decision_lineage(
                journal_id=journal_id, replay_id=replay_id, execution=execution,
            )


class BreakoutMainRiskAdapter:
    def evaluate(self, context):
        return _status("RISK_ADAPTER")


class BreakoutMainJournalAdapter:
    def record(self, event):
        return _record("JOURNAL_ADAPTER", event)


class BreakoutMainReplayAdapter:
    def record(self, event):
        return _record("REPLAY_ADAPTER", event)


class BreakoutMainEvidenceAdapter:
    def record(self, event):
        return _record("EVIDENCE_ADAPTER", event)


def _record(component: str, event):
    if not event:
        return _status(component)
    return {
        "status": "MAPPED", "reason": "IMMUTABLE_RUNTIME_STREAM_OWNS_PERSISTENCE",
        "component": component, "event": dict(event), "paper_execution": False,
        "broker_submission": False, "live_trading_enabled": False,
    }
