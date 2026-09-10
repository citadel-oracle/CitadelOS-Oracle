"""Canonical Strategy Command → Strategy Lab runtime bridge.

The bridge loads the repository's real strategy adapters into the existing
paper-only Strategy Lab runtime.  It owns no registry, scheduler, market-data
feed, paper ledger, or broker path.
"""

from __future__ import annotations

import importlib
import inspect
import json
import math
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from src.paper_trading.contracts import ContractResolutionError, OptionContractResolver
from src.strategy_lab.models import DeploymentRequest
from src.strategy_lab.runtime import DisabledPaperExecution
from src.strategy_lab.service import StrategyLabService

from .models import (
    AggregationMode,
    DeploymentPath,
    aggregate_timeframe_votes,
    canonical_configuration_hash,
)
from .price_action import evaluate_price_action


EXECUTING_PATHS = {DeploymentPath.SIMPLE_PAPER, DeploymentPath.ORACLE_PAPER}
OBSERVE_PATHS = {
    DeploymentPath.WORKSPACE_OBSERVE,
    DeploymentPath.SIMPLE_SIGNAL_ONLY,
    DeploymentPath.ORACLE_SHADOW,
    DeploymentPath.REPLAY,
    DeploymentPath.BACKTEST,
}


class StrategyCommandSignalAdapter:
    """Normalize one real strategy adapter without replacing its signal logic."""

    def __init__(
        self,
        adapter: Any,
        *,
        configuration: Mapping[str, Any],
        attribution: Mapping[str, Any],
    ) -> None:
        self.adapter = adapter
        self.configuration = deepcopy(dict(configuration))
        self.attribution = deepcopy(dict(attribution))

    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        source = deepcopy(dict(self.adapter.evaluate(context)))
        signal = str(source.get("signal") or "WAIT").upper()
        timestamp = str(
            source.get("evaluated_at")
            or (context.get("bar") or {}).get("timestamp")
            or context.get("timestamp")
            or datetime.now(timezone.utc).isoformat()
        )
        if signal == "SELL":
            return {
                **source,
                **deepcopy(self.attribution),
                "normalized_signal": self._normalized_contract(
                    source, context, "NONE", timestamp, [], [], "EXIT"
                ),
            }

        direction = self._direction(source)
        blockers: list[str] = []
        warnings: list[str] = []
        weights = dict(self.configuration["decision"]["weights"])
        path = DeploymentPath(str(self.configuration["execution"]["path"]))

        if path is DeploymentPath.ORACLE_DEVELOPMENT_REFERENCE:
            blockers.append("ORACLE_DEVELOPMENT_REFERENCE_OBSERVE_ONLY")
        if path is DeploymentPath.LIVE_DISABLED:
            blockers.append("LIVE_EXECUTION_DISABLED")
        if signal == "BUY" and direction == "NONE":
            blockers.append("DIRECTION_NOT_DETERMINED")

        price_action = self._price_action(context)
        vob = self._vob(context)
        strategy_evidence = self._strategy_evidence(source, direction)
        component_scores = {
            "price_action": self._component_score(
                direction, price_action.get("direction"), weights["price_action"]
            ),
            "vob": self._component_score(
                direction, vob.get("direction"), weights["vob"]
            ),
            "strategy_trigger": self._component_score(
                direction, strategy_evidence.get("direction"), weights["strategy_trigger"]
            ),
        }

        entry = self.configuration["entry"]
        if signal == "BUY":
            if entry.get("price_action_requirement") == "REQUIRED" and not price_action["available"]:
                blockers.append("PRICE_ACTION_UNAVAILABLE")
            if entry.get("vob_requirement") == "REQUIRED" and not vob["available"]:
                blockers.append("VOB_UNAVAILABLE")
            if source.get("freshness") in {"STALE", "UNAVAILABLE"}:
                blockers.append(f"STRATEGY_SIGNAL_{source['freshness']}")

        timeframe_consensus = self._timeframe_consensus(context, direction)
        if timeframe_consensus["consensus"] in {
            "UNAVAILABLE", "CONFLICT", "WAITING_CONFIRMATION"
        }:
            blockers.append(str(timeframe_consensus.get("reason") or f"TIMEFRAME_{timeframe_consensus['consensus']}"))

        modifiers = self._intelligence(context, blockers, warnings)
        base_total = sum(component_scores.values())
        final_score = max(0.0, min(100.0, base_total + sum(
            float(row["score_delta"]) for row in modifiers
        )))
        minimum = float(entry.get("minimum_score") or 0)
        option_invalidation = _number(
            source.get("stop")
            if source.get("stop") is not None
            else source.get("sl")
            if source.get("sl") is not None
            else source.get("active_leg_stop")
        )
        underlying_invalidation = _number(
            source.get("underlying_stop")
            if source.get("underlying_stop") is not None
            else (source.get("position_state") or {}).get("stop")
        )
        invalidation = (
            option_invalidation
            if option_invalidation is not None
            else underlying_invalidation
        )
        invalidation_scope = (
            "OPTION_PREMIUM"
            if option_invalidation is not None
            else "UNDERLYING"
            if underlying_invalidation is not None
            else None
        )
        targets = _targets(source)
        if signal == "BUY" and invalidation is None:
            blockers.append("NUMERIC_INVALIDATION_REQUIRED")
        if (
            signal == "BUY"
            and path in EXECUTING_PATHS
            and option_invalidation is None
        ):
            blockers.append("OPTION_PREMIUM_INVALIDATION_REQUIRED")
        if signal == "BUY" and final_score < minimum:
            blockers.append("DECISION_THRESHOLD_NOT_MET")

        why = [
            f"PRICE_ACTION:{price_action.get('direction')}:{component_scores['price_action']}",
            f"VOB:{vob.get('direction')}:{component_scores['vob']}",
            f"STRATEGY_TRIGGER:{strategy_evidence.get('direction')}:{component_scores['strategy_trigger']}",
        ]
        if modifiers:
            why.extend(
                f"{row['name']}:{row['mode']}:{row['score_delta']}" for row in modifiers
            )
        executable = signal == "BUY" and not blockers and final_score >= minimum
        normalized_signal = self._normalized_contract(
            source,
            context,
            direction,
            timestamp,
            blockers,
            warnings,
            "SIGNAL_READY" if executable else "WAITING_FOR_TRIGGER",
            signal_score=final_score,
            invalidation=invalidation,
            targets=targets,
            timeframe_consensus=timeframe_consensus,
            source_evidence={
                "price_action": price_action,
                "vob": vob,
                "strategy_trigger": strategy_evidence,
            },
        )
        decision = {
            "price_action_score": component_scores["price_action"],
            "vob_score": component_scores["vob"],
            "strategy_score": component_scores["strategy_trigger"],
            "base_total": base_total,
            "confidence_modifiers": modifiers,
            "total_score": final_score,
            "direction": direction,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "why": why,
            "why_not": sorted(set(blockers)),
            "next_required_condition": (
                sorted(set(blockers))[0]
                if blockers
                else "VALID CONTRACT AND PAPER RISK AUTHORIZATION"
            ),
            "timeframe_consensus": timeframe_consensus,
            "input_freshness": self._freshness(context),
            "evaluated_at": timestamp,
        }
        normalized = {
            **source,
            **deepcopy(self.attribution),
            "evaluated_at": timestamp,
            "decision": decision,
            "normalized_signal": normalized_signal,
            "price_action_score": decision["price_action_score"],
            "vob_score": decision["vob_score"],
            "strategy_score": decision["strategy_score"],
            "base_total": decision["base_total"],
            "confidence_modifiers": decision["confidence_modifiers"],
            "total_score": decision["total_score"],
            "direction": direction,
            "blockers": decision["blockers"],
            "warnings": decision["warnings"],
            "why": decision["why"],
            "why_not": decision["why_not"],
            "next_required_condition": decision["next_required_condition"],
            "timeframe_consensus": timeframe_consensus,
            "input_freshness": decision["input_freshness"],
            "invalidation": invalidation,
            "invalidation_scope": invalidation_scope,
            "invalidation_operator": "<=" if invalidation is not None else None,
            "targets": targets,
            "mission_required": path in EXECUTING_PATHS,
            "command_risk_configuration": {
                "position": deepcopy(dict(self.configuration["position"])),
                "session": deepcopy(dict(self.configuration["session"])),
                "conflict": deepcopy(dict(self.configuration["conflict"])),
            },
        }
        if executable:
            normalized["signal"] = "BUY"
            if source.get("stop") is None and option_invalidation is not None:
                normalized["stop"] = option_invalidation
            if source.get("target") is None and targets:
                normalized["target"] = targets[0]
        elif signal == "BUY":
            normalized["would_signal"] = "BUY"
            normalized["signal"] = "WAIT"
            normalized["reason"] = normalized["next_required_condition"]
        return normalized

    def serialize(self) -> str:
        serialize = getattr(self.adapter, "serialize", None)
        inner = serialize() if callable(serialize) else None
        return json.dumps(
            {
                "configuration": self.configuration,
                "attribution": self.attribution,
                "adapter_module": type(self.adapter).__module__,
                "adapter_class": type(self.adapter).__name__,
                "adapter_state": inner,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, payload: str) -> "StrategyCommandSignalAdapter":
        value = json.loads(payload)
        module = importlib.import_module(str(value["adapter_module"]))
        adapter_class = getattr(module, str(value["adapter_class"]))
        state = value.get("adapter_state")
        restore = getattr(adapter_class, "deserialize", None)
        adapter = restore(state) if state is not None and callable(restore) else adapter_class()
        return cls(
            adapter,
            configuration=value["configuration"],
            attribution=value["attribution"],
        )

    def _direction(self, source: Mapping[str, Any]) -> str:
        if str(source.get("signal") or "").upper() != "BUY":
            return "NONE"
        contract = source.get("option_contract")
        option_type = (
            str(contract.get("option_type") or "").upper()
            if isinstance(contract, Mapping)
            else ""
        )
        if option_type == "CE":
            return "CALL"
        if option_type == "PE":
            return "PUT"
        sides = [
            str(item).upper()
            for item in self.configuration["market"].get("option_sides") or []
        ]
        return sides[0] if len(sides) == 1 and sides[0] in {"CALL", "PUT"} else "NONE"

    @staticmethod
    def _price_action(context: Mapping[str, Any]) -> dict[str, Any]:
        supplied = context.get("price_action")
        if isinstance(supplied, Mapping):
            direction = _canonical_direction(
                supplied.get("direction") or supplied.get("bias") or supplied.get("signal")
            )
            return {
                "available": direction != "UNAVAILABLE",
                "direction": direction,
                "source": supplied.get("source") or "CANONICAL_PRICE_ACTION",
                "timestamp": supplied.get("timestamp"),
                "raw": deepcopy(dict(supplied)),
            }
        result = evaluate_price_action(context)
        direction = _canonical_direction(result.get("signal"))
        return {
            "available": direction != "UNAVAILABLE",
            "direction": direction,
            "source": "PARITY_TESTED_PRICE_ACTION_ADAPTER",
            "timestamp": context.get("timestamp"),
            "raw": result,
        }

    @staticmethod
    def _vob(context: Mapping[str, Any]) -> dict[str, Any]:
        supplied = context.get("vob")
        if not isinstance(supplied, Mapping):
            return {
                "available": False,
                "direction": "UNAVAILABLE",
                "reason": "VOB_UNAVAILABLE",
            }
        direction = _canonical_direction(
            supplied.get("direction")
            or supplied.get("dominant_bias")
            or supplied.get("classification")
        )
        return {
            "available": direction != "UNAVAILABLE",
            "direction": direction,
            "source": supplied.get("source") or "CANONICAL_VOB",
            "timestamp": supplied.get("evaluated_through") or supplied.get("timestamp"),
            "raw": deepcopy(dict(supplied)),
        }

    @staticmethod
    def _strategy_evidence(source: Mapping[str, Any], direction: str) -> dict[str, Any]:
        return {
            "available": str(source.get("signal") or "").upper() in {"BUY", "SELL", "WAIT"},
            "direction": direction if str(source.get("signal") or "").upper() == "BUY" else "NEUTRAL",
            "reason": source.get("reason"),
            "source": f"{type(source).__name__}:REAL_STRATEGY_OUTPUT",
        }

    def _timeframe_consensus(
        self, context: Mapping[str, Any], direction: str
    ) -> dict[str, Any]:
        roles = self.configuration["timeframes"]["roles"]
        required = sorted({str(item) for values in roles.values() for item in values})
        evidence = context.get("timeframe_evidence")
        votes: dict[str, str] = {}
        stale: list[str] = []
        if isinstance(evidence, Mapping):
            for timeframe, row in evidence.items():
                if not isinstance(row, Mapping):
                    continue
                if str(row.get("freshness") or "FRESH").upper() != "FRESH":
                    stale.append(str(timeframe))
                vote = _vote(row.get("direction") or row.get("bias"))
                if vote:
                    votes[str(timeframe)] = vote
        current_timeframe = str(context.get("timeframe") or "")
        if current_timeframe in required and current_timeframe not in votes:
            vote = _vote(direction)
            if vote:
                votes[current_timeframe] = vote
        mode = AggregationMode(str(self.configuration["timeframes"]["aggregation"]))
        if len(required) == 1:
            only_timeframe = required[0]
            only_vote = votes.get(only_timeframe)
            return {
                "mode": mode.value,
                "votes": votes,
                "required_timeframes": required,
                "stale_timeframes": stale,
                "consensus": (
                    "UNAVAILABLE"
                    if only_vote is None or only_timeframe in stale
                    else only_vote
                ),
                "reason": (
                    "SINGLE_TIMEFRAME_UNAVAILABLE"
                    if only_vote is None
                    else "SINGLE_TIMEFRAME_STALE"
                    if only_timeframe in stale
                    else "SINGLE_TIMEFRAME_CONFIRMED"
                ),
            }
        options: dict[str, Any] = {
            "required_timeframes": required,
            "stale_timeframes": stale,
        }
        if mode is AggregationMode.WEIGHTED:
            options["weights"] = self.configuration["timeframes"].get("weights") or {}
        if mode is AggregationMode.PRIMARY_PLUS_CONFIRMATION:
            options["primary"] = str((roles.get("entry") or required)[0])
        try:
            return aggregate_timeframe_votes(votes, mode, **options)
        except ValueError as error:
            return {
                "mode": mode.value,
                "votes": votes,
                "consensus": "UNAVAILABLE",
                "reason": str(error),
            }

    def _intelligence(
        self,
        context: Mapping[str, Any],
        blockers: list[str],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        supplied = context.get("intelligence")
        source = supplied if isinstance(supplied, Mapping) else {}
        modifiers: list[dict[str, Any]] = []
        for name, mode in sorted(self.configuration["decision"]["intelligence"].items()):
            row = source.get(name)
            available = isinstance(row, Mapping) and str(row.get("status") or "AVAILABLE").upper() not in {
                "UNAVAILABLE", "STALE", "ERROR"
            }
            if mode == "HARD_REQUIREMENT" and not available:
                blockers.append(f"{name.upper()}_HARD_REQUIREMENT_UNAVAILABLE")
            elif mode == "ENTRY_WARNING" and not available:
                warnings.append(f"{name.upper()}_UNAVAILABLE")
            if mode != "CONFIDENCE_MODIFIER" or not available:
                continue
            delta = _number(row.get("score_delta"))
            if delta is None:
                warnings.append(f"{name.upper()}_MODIFIER_NOT_REPORTED")
                continue
            modifiers.append({
                "name": name.upper(),
                "mode": mode,
                "score_delta": max(-25.0, min(25.0, delta)),
                "source_timestamp": row.get("timestamp"),
            })
        return modifiers

    @staticmethod
    def _freshness(context: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "status": context.get("source_health") or "NOT_REPORTED",
            "candle_timestamp": (context.get("bar") or {}).get("timestamp"),
            "source_timestamp": context.get("source_timestamp"),
            "argus_timestamp": (
                (context.get("argus") or {}).get("data", {}).get("fetched_at")
                if isinstance(context.get("argus"), Mapping)
                else None
            ),
        }

    @staticmethod
    def _component_score(direction: str, evidence: Any, weight: Any) -> float:
        value = float(weight)
        if direction == "NONE" or evidence in {"UNAVAILABLE", None}:
            return 0.0
        if evidence == direction:
            return value
        if evidence == "NEUTRAL":
            return value / 2.0
        return 0.0

    def _normalized_contract(
        self,
        source: Mapping[str, Any],
        context: Mapping[str, Any],
        direction: str,
        timestamp: str,
        blockers: list[str],
        warnings: list[str],
        trigger_state: str,
        *,
        signal_score: float = 0.0,
        invalidation: float | None = None,
        targets: list[float] | None = None,
        timeframe_consensus: Mapping[str, Any] | None = None,
        source_evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "direction": direction,
            "trigger_state": trigger_state,
            "signal_score": signal_score,
            "entry_condition": source.get("entry_condition") or source.get("reason"),
            "invalidation": invalidation,
            "invalidation_operator": "<=" if invalidation is not None else None,
            "targets": targets or [],
            "required_timeframe_evidence": deepcopy(dict(timeframe_consensus or {})),
            "timestamp": timestamp,
            "freshness": self._freshness(context),
            "confidence": source.get("confidence"),
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "source_evidence": deepcopy(dict(source_evidence or {})),
            "strategy_specific_explanation": source.get("reason"),
            **deepcopy(self.attribution),
        }


class ConfiguredOptionContractResolver:
    """Apply one deployment's liquidity constraints to the canonical resolver."""

    def __init__(
        self,
        configuration: Mapping[str, Any],
        resolver: OptionContractResolver | None = None,
    ) -> None:
        self.configuration = deepcopy(dict(configuration))
        self.resolver = resolver or OptionContractResolver()
        self.last_selection: dict[str, Any] | None = None

    def resolve(self, argus_response: Mapping[str, Any], signal: str, **values: Any):
        market = self.configuration["market"]
        resolved = self.resolver.resolve(argus_response, signal, **values)
        leg = self._leg(argus_response, resolved.security_id)
        rejected: list[str] = []
        premium = float(resolved.ltp)
        bid = _number(resolved.top_bid_price)
        ask = _number(resolved.top_ask_price)
        spread = ask - bid if ask is not None and bid is not None else None
        premium_range = market.get("premium_range") or [None, None]
        delta_range = market.get("delta_range") or [None, None]
        if market.get("maximum_spread") is not None and (
            spread is None or spread > float(market["maximum_spread"])
        ):
            rejected.append("MAXIMUM_SPREAD_EXCEEDED")
        if market.get("minimum_oi") is not None and (
            _number(leg.get("oi")) is None
            or float(leg["oi"]) < float(market["minimum_oi"])
        ):
            rejected.append("MINIMUM_OI_NOT_MET")
        if market.get("minimum_volume") is not None and (
            _number(leg.get("volume")) is None
            or float(leg["volume"]) < float(market["minimum_volume"])
        ):
            rejected.append("MINIMUM_VOLUME_NOT_MET")
        if premium_range[0] is not None and premium < float(premium_range[0]):
            rejected.append("PREMIUM_BELOW_RANGE")
        if premium_range[1] is not None and premium > float(premium_range[1]):
            rejected.append("PREMIUM_ABOVE_RANGE")
        if any(item is not None for item in delta_range):
            delta = _number(leg.get("delta"))
            if delta is None:
                rejected.append("DELTA_UNAVAILABLE")
            elif (
                delta_range[0] is not None and delta < float(delta_range[0])
            ) or (
                delta_range[1] is not None and delta > float(delta_range[1])
            ):
                rejected.append("DELTA_OUTSIDE_RANGE")
        quote_timestamp = (
            leg.get("source_timestamp")
            or leg.get("timestamp")
            or (argus_response.get("data") or {}).get("fetched_at")
        )
        evidence = {
            "selected_contract": resolved.to_dict(),
            "selection_reason": "CONFIGURED_CANONICAL_OPTION_RESOLVER",
            "rejected_alternatives": rejected,
            "authoritative_quote": {
                "ltp": premium,
                "bid": bid,
                "ask": ask,
                "timestamp": quote_timestamp,
                "source": resolved.quote_source,
            },
            "spread": spread,
            "liquidity_evidence": {
                "oi": leg.get("oi"),
                "volume": leg.get("volume"),
                "bid_quantity": resolved.top_bid_quantity,
                "ask_quantity": resolved.top_ask_quantity,
            },
            "configuration_hash": canonical_configuration_hash(market),
        }
        self.last_selection = evidence
        if rejected:
            raise ContractResolutionError(f"NO_ELIGIBLE_CONTRACT:{','.join(rejected)}")
        return resolved

    def quote_existing(self, argus_response: Mapping[str, Any], contract: str):
        return self.resolver.quote_existing(argus_response, contract)

    def validate_existing(
        self,
        argus_response: Mapping[str, Any],
        contract: str,
        option_contract: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        leg = self._leg(argus_response, contract)
        if not leg:
            raise ContractResolutionError("NO_ELIGIBLE_CONTRACT:EXACT_CONTRACT_QUOTE_UNAVAILABLE")
        market = self.configuration["market"]
        premium = _number(leg.get("ltp"))
        bid = _number(leg.get("top_bid_price"))
        ask = _number(leg.get("top_ask_price"))
        spread = ask - bid if ask is not None and bid is not None else None
        rejected: list[str] = []
        if premium is None or premium <= 0:
            rejected.append("AUTHORITATIVE_PREMIUM_UNAVAILABLE")
        if market.get("maximum_spread") is not None and (
            spread is None or spread > float(market["maximum_spread"])
        ):
            rejected.append("MAXIMUM_SPREAD_EXCEEDED")
        if market.get("minimum_oi") is not None and (
            _number(leg.get("oi")) is None
            or float(leg["oi"]) < float(market["minimum_oi"])
        ):
            rejected.append("MINIMUM_OI_NOT_MET")
        if market.get("minimum_volume") is not None and (
            _number(leg.get("volume")) is None
            or float(leg["volume"]) < float(market["minimum_volume"])
        ):
            rejected.append("MINIMUM_VOLUME_NOT_MET")
        premium_range = market.get("premium_range") or [None, None]
        if premium is not None:
            if premium_range[0] is not None and premium < float(premium_range[0]):
                rejected.append("PREMIUM_BELOW_RANGE")
            if premium_range[1] is not None and premium > float(premium_range[1]):
                rejected.append("PREMIUM_ABOVE_RANGE")
        option = dict(option_contract or {})
        sides = [str(item).upper() for item in market.get("option_sides") or []]
        option_type = str(option.get("option_type") or "").upper()
        if len(sides) == 1 and option_type:
            expected = "CE" if sides[0] == "CALL" else "PE"
            if option_type != expected:
                rejected.append("OPTION_SIDE_MISMATCH")
        configured_expiry = market.get("expiry_date")
        if configured_expiry and str(option.get("expiry") or "") != str(configured_expiry):
            rejected.append("EXPIRY_MISMATCH")
        evidence = {
            "selected_contract": deepcopy(option) or {"security_id": str(contract)},
            "selection_reason": "REAL_STRATEGY_CONTRACT_VALIDATED_AGAINST_CONFIGURATION",
            "rejected_alternatives": rejected,
            "authoritative_quote": {
                "ltp": premium,
                "bid": bid,
                "ask": ask,
                "timestamp": leg.get("source_timestamp") or leg.get("timestamp"),
                "source": "ARGUS_OPTION_CHAIN",
            },
            "spread": spread,
            "liquidity_evidence": {
                "oi": leg.get("oi"),
                "volume": leg.get("volume"),
                "bid_quantity": leg.get("top_bid_quantity"),
                "ask_quantity": leg.get("top_ask_quantity"),
            },
            "configuration_hash": canonical_configuration_hash(market),
        }
        self.last_selection = evidence
        if rejected:
            raise ContractResolutionError(f"NO_ELIGIBLE_CONTRACT:{','.join(rejected)}")
        return evidence

    @staticmethod
    def _leg(argus_response: Mapping[str, Any], security_id: str) -> dict[str, Any]:
        for row in (argus_response.get("data") or {}).get("atm_window") or []:
            if not isinstance(row, Mapping):
                continue
            for key in ("ce", "pe"):
                leg = row.get(key)
                if isinstance(leg, Mapping) and str(leg.get("security_id")) == str(security_id):
                    return dict(leg)
        return {}


class StrategyCommandRuntimeBridge:
    """Load active canonical deployment instances into Strategy Lab."""

    def __init__(
        self,
        *,
        command: Any,
        lab: StrategyLabService,
        context_factory: Callable[[Mapping[str, Any]], Callable[[], Mapping[str, Any]]],
    ) -> None:
        self.command = command
        self.lab = lab
        self.context_factory = context_factory

    def synchronize_all(self) -> dict[str, Any]:
        results = []
        for deployment in self.command.deployments():
            if deployment.get("enabled") is not True:
                continue
            instance_id = str(deployment["deployment_instance_id"])
            try:
                results.append(self.synchronize(instance_id))
            except Exception as error:
                results.append({
                    "deployment_instance_id": instance_id,
                    "status": "BLOCKED",
                    "reason": f"RUNTIME_ACTIVATION_FAILED:{type(error).__name__}:{error}",
                })
        return {"status": "COMPLETE", "runtimes": results}

    def synchronize(self, instance_id: str) -> dict[str, Any]:
        deployment = self.command.deployment(instance_id)
        if self.lab.has_runtime(instance_id):
            return {
                "deployment_instance_id": instance_id,
                "status": "ALREADY_LOADED",
            }
        request = self._request(deployment)
        runtime = self.lab.deploy(request, start=True)
        return {
            "deployment_instance_id": instance_id,
            "status": "LOADED",
            "runtime": runtime.status(),
        }

    def pause(self, instance_id: str) -> dict[str, Any]:
        return self.lab.pause_runtime(instance_id)

    def resume(self, instance_id: str) -> dict[str, Any]:
        if not self.lab.has_runtime(instance_id):
            self.synchronize(instance_id)
        return self.lab.resume_runtime(instance_id)

    def _request(self, deployment: Mapping[str, Any]) -> DeploymentRequest:
        config = deepcopy(dict(deployment["configuration"]))
        version = self.command.version(
            str(deployment["strategy_id"]), str(deployment["strategy_version"])
        )
        module = importlib.import_module(str(version["source_module"]))
        builder = getattr(module, "build_deployment_request")
        signature = inspect.signature(builder)
        market = config["market"]
        roles = config["timeframes"]["roles"]
        primary_timeframe = str((roles.get("entry") or roles.get("signal"))[0])
        sides = [str(item).upper() for item in market.get("option_sides") or []]
        option_type = "CE" if sides == ["CALL"] else "PE" if sides == ["PUT"] else (
            "PE" if "PE" in str(deployment["strategy_id"]).upper() else "CE"
        )
        path = DeploymentPath(str(config["execution"]["path"]))
        values = {
            "context_provider": self.context_factory(deployment),
            "deployment_id": str(deployment["deployment_instance_id"]),
            "deployment_name": str(deployment["name"]),
            "chart_symbol": str(market["instrument"]),
            "chart_timeframe": primary_timeframe,
            "option_type": option_type,
            "mode": "PAPER" if path in EXECUTING_PATHS else "SHADOW",
        }
        request = builder(**{
            key: value for key, value in values.items() if key in signature.parameters
        })
        attribution = {
            "strategy_id": str(deployment["strategy_id"]),
            "strategy_version": str(deployment["strategy_version"]),
            "deployment_instance_id": str(deployment["deployment_instance_id"]),
            "configuration_hash": str(deployment["configuration_hash"]),
            "instrument": str(market["instrument"]),
            "timeframe_set": deepcopy(dict(roles)),
            "execution_path": path.value,
        }
        parameters = deepcopy(dict(request.metadata.parameters))
        parameters.update({
            "canonical_strategy_id": attribution["strategy_id"],
            "canonical_strategy_version": attribution["strategy_version"],
            "deployment_instance_id": attribution["deployment_instance_id"],
            "configuration_hash": attribution["configuration_hash"],
            "command_configuration": config,
            "option_selection": {
                "underlying": str(market["instrument"]),
                "option_type": option_type,
                "strike_offset": int(market.get("strike_offset") or 0),
                "expiry": market.get("expiry_date"),
            },
            "paper_account": self._paper_account(config),
        })
        metadata = replace(
            request.metadata,
            strategy_id=str(deployment["deployment_instance_id"]),
            version=str(deployment["strategy_version"]),
            supported_markets=[str(market["instrument"])],
            supported_timeframes=[primary_timeframe],
            parameters=parameters,
        )
        execution = request.execution
        activation_enabled = bool(config["execution"]["enabled"])
        activation_reason = None
        if path not in EXECUTING_PATHS:
            execution = DisabledPaperExecution()
        if path in {
            DeploymentPath.ORACLE_DEVELOPMENT_REFERENCE,
            DeploymentPath.LIVE_DISABLED,
        }:
            activation_enabled = False
            activation_reason = (
                "ORACLE_DEVELOPMENT_REFERENCE_OBSERVE_ONLY"
                if path is DeploymentPath.ORACLE_DEVELOPMENT_REFERENCE
                else "LIVE_EXECUTION_DISABLED"
            )
        return replace(
            request,
            metadata=metadata,
            adapter=StrategyCommandSignalAdapter(
                request.adapter,
                configuration=config,
                attribution=attribution,
            ),
            execution=execution,
            option_resolver=ConfiguredOptionContractResolver(config),
            activation_enabled=activation_enabled,
            activation_reason=activation_reason,
        )

    @staticmethod
    def _paper_account(config: Mapping[str, Any]) -> dict[str, Any]:
        position = config["position"]
        session = config["session"]
        sizing_mode = "FIXED_LOTS"
        return {
            "portfolio_id": "portfolio_strategy_command",
            "currency": "INR",
            "initial_capital": float(position["capital"]),
            "portfolio_capital_limit": float(position["capital"]),
            "sizing_mode": sizing_mode,
            "fixed_lots": int(position["fixed_lots"]),
            "lot_size": None,
            "fixed_rupee_risk": position.get("fixed_rupee_risk"),
            "max_daily_loss": float(session["daily_loss_limit"]),
            "max_concurrent_positions": int(position["maximum_open_positions"]),
            "max_trades_per_day": int(session["maximum_trades_per_day"]),
            "max_exposure_percent": 100.0,
            "margin_rate": 1.0,
        }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _targets(source: Mapping[str, Any]) -> list[float]:
    values = source.get("targets")
    if not isinstance(values, list):
        values = [
            source.get("target"),
            source.get("underlying_target"),
            (source.get("position_state") or {}).get("target"),
        ]
    result = []
    for value in values:
        number = _number(value)
        if number is not None and number not in result:
            result.append(number)
    return result


def _canonical_direction(value: Any) -> str:
    text = str(value or "").upper().replace(" ", "_")
    if text in {"CALL", "CE", "BUY", "BULLISH", "ULTRA_BULLISH"}:
        return "CALL"
    if text in {"PUT", "PE", "SELL", "BEARISH", "ULTRA_BEARISH"}:
        return "PUT"
    if text in {"NEUTRAL", "MIXED", "BALANCED", "NONE", "WAIT"}:
        return "NEUTRAL"
    return "UNAVAILABLE"


def _vote(value: Any) -> str | None:
    direction = _canonical_direction(value)
    return {
        "CALL": "BULLISH",
        "PUT": "BEARISH",
        "NEUTRAL": "NEUTRAL",
    }.get(direction)
