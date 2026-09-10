"""Phase-5 coordinator: trigger -> fresh truth -> risk -> internal paper -> Guardian."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from time import perf_counter
from typing import Any, Callable, Mapping

from src.risk.authorization import ExactPaperAuthorizationRequest, RiskAuthorizationService

from .contracts import ConditionState, PaperOrderRequest, TriggerEvent, seal
from .guardian import IndependentPaperGuardian
from .paper import PaperExecutionError, Phase5PaperExecutionAdapter
from .service import OracleConditionService, Phase5RevalidationService


class Phase5OracleWorkflow:
    def __init__(self, *, conditions: OracleConditionService,
                 revalidation: Phase5RevalidationService,
                 risk: RiskAuthorizationService,
                 paper: Phase5PaperExecutionAdapter,
                 guardian: IndependentPaperGuardian,
                 quote_provider: Callable[[str], Mapping[str, Any] | None],
                 clock=None):
        self.conditions = conditions
        self.revalidation = revalidation
        self.risk = risk
        self.paper = paper
        self.guardian = guardian
        self.quote_provider = quote_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.metrics: dict[str, list[float]] = {name: [] for name in (
            "trigger_revalidation", "risk_authorization", "paper_submission", "fill_reconciliation", "protection")}

    def handle_trigger(self, condition, trigger: TriggerEvent) -> None:
        projection = self.conditions.store.projection(condition.condition_id)
        self.conditions.transition(condition.condition_id, ConditionState.REVALIDATING,
            expected_prior_version=projection.version, idempotency_key=f"revalidating:{trigger.trigger_id}",
            actor_id="PHASE5_WORKFLOW", reason_code="FRESH_ANALYSIS_REQUIRED",
            details={"trigger_id": trigger.trigger_id})
        started = perf_counter()
        try:
            result = self.revalidation.revalidate(condition, trigger)
        except Exception as error:
            projection = self.conditions.store.projection(condition.condition_id)
            self.conditions.transition(condition.condition_id, ConditionState.FAILED_SAFE,
                expected_prior_version=projection.version, idempotency_key=f"revalidation-failed:{trigger.trigger_id}",
                actor_id="PHASE5_WORKFLOW", reason_code="REVALIDATION_UNAVAILABLE",
                details={"explanation": f"{type(error).__name__}:{error}"})
            return
        self.metrics["trigger_revalidation"].append((perf_counter() - started) * 1000)
        self.conditions.store.stream(condition.condition_id).append(
            "REVALIDATION_RESULT", result.to_dict(), idempotency_key=f"revalidation-result:{result.revalidation_id}")
        if not result.passed:
            projection = self.conditions.store.projection(condition.condition_id)
            self.conditions.transition(condition.condition_id, ConditionState.REJECTED,
                expected_prior_version=projection.version, idempotency_key=f"rejected:{result.revalidation_id}",
                actor_id="PHASE5_WORKFLOW", reason_code="MATERIAL_DRIFT",
                details={"revalidation_id": result.revalidation_id, "explanation": ",".join(result.material_drift)})
            return
        quote = self.quote_provider(condition.selected_option_id)
        if not isinstance(quote, Mapping):
            self._fail(condition.condition_id, "CANONICAL_OPTION_QUOTE_UNAVAILABLE", result.revalidation_id)
            return
        plan = result.dynamic_plan
        assert plan is not None
        now = self._now()
        quantity = int(quote.get("quantity") or quote.get("lot_size") or 0)
        lot_size = int(quote.get("lot_size") or 0)
        ask = float(quote.get("ask") or 0)
        if quantity <= 0 or lot_size <= 0 or quantity % lot_size or ask <= 0:
            self._fail(condition.condition_id, "EXACT_QUANTITY_OR_ASK_UNAVAILABLE", result.revalidation_id)
            return
        limit = min(plan.entry_band[1], ask + plan.maximum_slippage)
        if limit < ask or not plan.entry_band[0] <= limit <= plan.entry_band[1]:
            self._reject(condition.condition_id, "ENTRY_PRICE_MOVED_BEYOND_ALLOWED_EXTENSION", result.revalidation_id)
            return
        expires = min(now + timedelta(seconds=30), datetime.fromisoformat(condition.expiry_policy.expires_at.replace("Z", "+00:00")))
        order = seal(PaperOrderRequest(
            order_request_id="p5req_" + hashlib.sha256(f"{condition.condition_id}|{result.content_hash}".encode()).hexdigest()[:24],
            condition_id=condition.condition_id, revalidation_id=result.revalidation_id,
            decision_id=result.fresh_decision_id, contract_id=condition.selected_option_id,
            exchange_segment=str(quote.get("exchange_segment") or "NSE_FNO"),
            expiry=str(quote.get("expiry")), strike=float(quote.get("strike")),
            symbol=condition.symbol, option_type=condition.predicate_ast.premium_confirmation.option_type,
            side="BUY", quantity=quantity, lot_size=lot_size, order_type="MARKETABLE_LIMIT",
            limit_price=limit, executable_price_band=plan.entry_band,
            stop_price=plan.premium_hard_stop, target_prices=plan.natural_target_premiums,
            estimated_maximum_loss=(limit - plan.premium_hard_stop) * quantity,
            market_data_timestamp=str(quote.get("timestamp")), expires_at=expires.isoformat(),
            idempotency_key=f"paper-order:{condition.condition_id}:{result.revalidation_id}",
        ))
        auth_request = ExactPaperAuthorizationRequest(
            request_id=f"risk:{order.order_request_id}", condition_id=condition.condition_id,
            condition_hash=condition.content_hash, decision_id=result.fresh_decision_id,
            decision_hash=result.fresh_decision_hash, revalidation_id=result.revalidation_id,
            revalidation_hash=result.content_hash, paper_order_request_id=order.order_request_id,
            paper_order_request_hash=order.content_hash, symbol=condition.symbol,
            instrument_id=order.contract_id, side="BUY", quantity=quantity,
            executable_price_low=order.executable_price_band[0], executable_price_high=order.executable_price_band[1],
            price=order.limit_price, stop_price=order.stop_price,
            estimated_maximum_loss=order.estimated_maximum_loss,
            market_data_timestamp=datetime.fromisoformat(order.market_data_timestamp.replace("Z", "+00:00")),
            expires_at=expires, idempotency_key=f"paper-risk:{order.order_request_id}",
        )
        started = perf_counter()
        authorization = self.risk.authorize_exact_paper(auth_request)
        self.metrics["risk_authorization"].append((perf_counter() - started) * 1000)
        self.conditions.store.stream(condition.condition_id).append("PAPER_RISK_AUTHORIZATION", authorization.to_dict(),
            idempotency_key=f"authorization:{order.order_request_id}")
        if not authorization.allowed:
            self._reject(condition.condition_id, authorization.reason_code, result.revalidation_id,
                         explanation=authorization.reason)
            return
        projection = self.conditions.store.projection(condition.condition_id)
        projection = self.conditions.transition(condition.condition_id, ConditionState.RISK_APPROVED,
            expected_prior_version=projection.version, idempotency_key=f"risk-approved:{authorization.authorization_id}",
            actor_id="RISK_AUTHORIZATION_SERVICE", reason_code="EXACT_ONE_TIME_PAPER_AUTHORIZATION",
            details={"revalidation_id": result.revalidation_id, "risk_grant_id": authorization.authorization_id})
        started = perf_counter()
        try:
            if self.paper.ledger.integrity().get("status") != "HEALTHY":
                raise PaperExecutionError("PAPER_ROUTE_UNHEALTHY")
            execution = self.paper.submit(order, authorization, quote)
        except Exception as error:
            reason = str(error) if isinstance(error, PaperExecutionError) else f"PAPER_EXECUTION_UNAVAILABLE:{type(error).__name__}"
            self._fail(condition.condition_id, reason, result.revalidation_id)
            return
        self.metrics["paper_submission"].append((perf_counter() - started) * 1000)
        reconcile_started = perf_counter()
        if execution.get("position_id"):
            trade_projection = self.paper.trade(str(execution["position_id"]))
            if trade_projection.get("status") != "OPEN" or not execution.get("paper_state_applied"):
                self._fail(condition.condition_id, "FILL_RECONCILIATION_FAILED", result.revalidation_id)
                return
        self.metrics["fill_reconciliation"].append((perf_counter() - reconcile_started) * 1000)
        self.conditions.store.stream(condition.condition_id).append("PAPER_EXECUTION_RESULT", execution,
            idempotency_key=f"execution:{order.order_request_id}")
        projection = self.conditions.store.projection(condition.condition_id)
        order_id = str((execution.get("intent") or {}).get("intent_id") or execution.get("order_id") or "")
        if execution.get("state") == "REJECTED":
            self.conditions.transition(condition.condition_id, ConditionState.REJECTED,
                expected_prior_version=projection.version, idempotency_key=f"order-rejected:{order_id}",
                actor_id="PAPER_EXECUTION", reason_code="PAPER_ORDER_REJECTED", details={"order_id": order_id})
            return
        projection = self.conditions.transition(condition.condition_id, ConditionState.ORDER_SUBMITTED,
            expected_prior_version=projection.version, idempotency_key=f"order-submitted:{order_id}",
            actor_id="PAPER_EXECUTION", reason_code="INTERNAL_PAPER_ORDER_SUBMITTED",
            details={"order_id": order_id})
        if not execution.get("position_id"):
            return
        filled_state = ConditionState.PARTIALLY_FILLED if execution.get("partial_fill") else ConditionState.FILLED
        projection = self.conditions.transition(condition.condition_id, filled_state,
            expected_prior_version=projection.version, idempotency_key=f"fill:{order_id}", actor_id="PAPER_EXECUTION",
            reason_code="PARTIAL_FILL_REMAINDER_CANCELLED" if execution.get("partial_fill") else "PAPER_FILL_RECONCILED",
            details={"order_id": order_id, "position_id": execution["position_id"]})
        started = perf_counter()
        try:
            protection = self.paper.establish_protection(
                condition_id=condition.condition_id, position_id=execution["position_id"], authorization=authorization,
                request=order, structural_invalidation_id=plan.structural_invalidation_id,
                time_exit_at=condition.expiry_policy.expires_at,
            )
        except PaperExecutionError as error:
            self.conditions.transition(condition.condition_id, ConditionState.RECONCILIATION_REQUIRED,
                expected_prior_version=projection.version, idempotency_key=f"protection-failed:{order_id}",
                actor_id="PAPER_EXECUTION", reason_code=str(error), details={"position_id": execution["position_id"]})
            return
        self.metrics["protection"].append((perf_counter() - started) * 1000)
        self.conditions.store.stream(condition.condition_id).append("DURABLE_PAPER_PROTECTION", protection.to_dict(),
            idempotency_key=f"protection:{protection.protection_id}")
        self.conditions.transition(condition.condition_id, ConditionState.MANAGING,
            expected_prior_version=projection.version, idempotency_key=f"managing:{execution['position_id']}",
            actor_id="INDEPENDENT_GUARDIAN", reason_code="PROTECTION_RECONCILED",
            details={"position_id": execution["position_id"], "protection_id": protection.protection_id,
                     "guardian_action": "HOLD"})

    def performance(self) -> dict[str, Any]:
        def p95(values):
            if not values:
                return None
            ordered = sorted(values)
            return round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3)
        return {name: {"samples": len(values), "p95_ms": p95(values)} for name, values in self.metrics.items()}

    def openalgo_capability(self) -> dict[str, Any]:
        return {
            "role": "DIAGNOSTIC_OPTIONAL", "production_reliability": "UNPROVEN",
            "analysis_authority": False, "market_data_authority": False,
            "risk_authority": False, "fill_truth_authority": False,
            "paper_analyzer_available": False, "fallback": "INTERNAL_PAPER_ENGINE",
            "live_mutation": False, "phase5_blocked_by_openalgo": False,
        }

    def _reject(self, condition_id: str, reason: str, revalidation_id: str, explanation: str | None = None) -> None:
        projection = self.conditions.store.projection(condition_id)
        self.conditions.transition(condition_id, ConditionState.REJECTED,
            expected_prior_version=projection.version, idempotency_key=f"reject:{condition_id}:{reason}:{projection.version}",
            actor_id="PHASE5_WORKFLOW", reason_code=reason,
            details={"revalidation_id": revalidation_id, "explanation": explanation or reason})

    def _fail(self, condition_id: str, reason: str, revalidation_id: str) -> None:
        projection = self.conditions.store.projection(condition_id)
        self.conditions.transition(condition_id, ConditionState.FAILED_SAFE,
            expected_prior_version=projection.version, idempotency_key=f"fail:{condition_id}:{reason}:{projection.version}",
            actor_id="PHASE5_WORKFLOW", reason_code=reason,
            details={"revalidation_id": revalidation_id, "explanation": reason})

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeError("VERIFIED_TIME_UNAVAILABLE")
        return value
