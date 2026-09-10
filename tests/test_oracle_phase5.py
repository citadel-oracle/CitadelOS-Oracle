from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest

from src.execution.paper_state import PaperStateService
from src.order_ledger.service import OrderFillLedgerService
from src.order_ledger.storage import OrderFillStore
from src.oracle.conditions import (
    CandleClosePredicate, ConditionConflict, ConditionContractError, ConditionEvaluator,
    ConditionState, DynamicPaperPlan, IndependentPaperGuardian, OracleConditionService,
    ConditionMonitor, PaperOrderRequest, Phase5PaperExecutionAdapter,
    Phase5RevalidationService, ProtectionPlan, seal,
)
from src.risk.authorization import (
    ExactPaperAuthorizationRequest, RiskAuditLogger, RiskAuthorizationRequest,
    RiskAuthorizationService, RiskControlStore,
)


NOW = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


def structured(now=NOW):
    return {
        "symbol": "NIFTY", "instrument_id": "NSE:IDX_I:13", "security_id": "12345",
        "timeframe": "3m", "candle_level": 24400.0, "candle_comparator": "ABOVE",
        "retest_direction": "HOLD_ABOVE", "retest_tolerance": 2.0,
        "selected_option_id": "12345", "option_type": "CE", "minimum_premium": 100.0,
        "maximum_spread": 1.0, "maximum_spread_percent": 1.0,
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "expected_candle_close_boundary": (now + timedelta(minutes=3)).isoformat(),
        "source_decision_id": "decision_12345678", "source_decision_hash": "d" * 64,
        "source_analysis_id": "analysis_12345678", "source_analysis_hash": "a" * 64,
        "required_direction": "BULLISH",
    }


def armed(tmp_path, now=NOW):
    service = OracleConditionService(tmp_path / "conditions", clock=lambda: now)
    projection = service.arm(
        original_wording="Next 3m close above 24400, retest hold and CE confirm then paper buy",
        structured=structured(now), actor_id="user-1", correlation_id="corr-12345678",
        idempotency_key="idem-arm-1", user_confirmed=True,
    )
    return service, service.store.definition(projection.condition_id), projection


def paper_components(tmp_path, now=NOW, *, depth=75):
    state = PaperStateService(tmp_path / "paper.json", now_provider=lambda: now)
    state.initialize(cash_balance=100000)
    ledger = OrderFillLedgerService(OrderFillStore(tmp_path / "ledger.json"), now_provider=lambda: now.isoformat())
    risk_store = RiskControlStore(tmp_path / "risk.json")
    risk_store.initialize(kill_switch_active=False, reason="paper fixture", actor="test")
    audit = RiskAuditLogger(tmp_path / "risk.jsonl")
    config = {
        "live_trading_enabled": False, "max_daily_loss": 1000, "max_trades_per_day": 3,
        "max_consecutive_losses": 3, "max_risk_per_trade": 500,
        "max_position_quantity": 150, "max_open_positions": 1,
        "max_market_data_age_seconds": 30, "max_volatility": None,
    }
    risk = RiskAuthorizationService(config_provider=lambda: config, store=risk_store,
                                    paper_state=state, audit_logger=audit, now_provider=lambda: now)
    adapter = Phase5PaperExecutionAdapter(tmp_path / "execution", ledger=ledger,
                                          paper_state=state, clock=lambda: now, slippage_points=.05)
    quote = {"contract_id": "12345", "bid": 99.8, "ask": 100.0, "ask_depth": depth,
             "timestamp": now.isoformat(), "lot_size": 75, "quantity": 75,
             "expiry": "2026-08-06", "strike": 24400, "exchange_segment": "NSE_FNO"}
    return state, ledger, risk, adapter, quote


def order_and_auth(risk, now=NOW):
    order = seal(PaperOrderRequest(
        order_request_id="paper-order-12345678", condition_id="condition-12345678",
        revalidation_id="revalidation-12345678", decision_id="decision-12345678",
        contract_id="12345", exchange_segment="NSE_FNO", expiry="2026-08-06",
        strike=24400, symbol="NIFTY", option_type="CE", side="BUY", quantity=75,
        lot_size=75, order_type="MARKETABLE_LIMIT", limit_price=100.25,
        executable_price_band=(99.5, 100.5), stop_price=95.0,
        target_prices=(110.0, 116.0), estimated_maximum_loss=393.75,
        market_data_timestamp=now.isoformat(), expires_at=(now + timedelta(seconds=20)).isoformat(),
        idempotency_key="paper-order-idem-12345678",
    ))
    request = ExactPaperAuthorizationRequest(
        request_id="risk-request-12345678", condition_id=order.condition_id,
        condition_hash="c" * 64, decision_id=order.decision_id, decision_hash="d" * 64,
        revalidation_id=order.revalidation_id, revalidation_hash="r" * 64,
        paper_order_request_id=order.order_request_id, paper_order_request_hash=order.content_hash,
        symbol="NIFTY", instrument_id="12345", side="BUY", quantity=75,
        executable_price_low=99.5, executable_price_high=100.5, price=100.25,
        stop_price=95.0, estimated_maximum_loss=393.75,
        market_data_timestamp=now, expires_at=now + timedelta(seconds=20),
        idempotency_key="risk-idem-12345678",
    )
    return order, request, risk.authorize_exact_paper(request)


def test_ambiguity_requires_confirmation_and_exact_ast(tmp_path):
    service = OracleConditionService(tmp_path)
    proposal = service.propose(original_wording="Buy if good", structured={},
                               actor_id="user", correlation_id="corr")
    assert proposal["status"] == "CLARIFICATION_REQUIRED"
    assert proposal["armed"] is False and proposal["execution_authority"] is False
    with pytest.raises(Exception, match="EXACT_CONFIRMATION_REQUIRED"):
        service.arm(original_wording="Buy if good", structured={}, actor_id="user",
                    correlation_id="corr", idempotency_key="idem", user_confirmed=False)


def test_condition_lifecycle_idempotency_restart_and_forbidden_transition(tmp_path):
    service, condition, projection = armed(tmp_path)
    assert projection.state is ConditionState.WATCHING and projection.version == 3
    recovered = OracleConditionService(tmp_path / "conditions", clock=lambda: NOW)
    assert recovered.store.projection(condition.condition_id).content_hash == projection.content_hash
    duplicate = recovered.arm(original_wording=condition.original_user_wording,
        structured=structured(), actor_id="user-1", correlation_id="corr-12345678",
        idempotency_key="idem-arm-1", user_confirmed=True)
    assert duplicate.version == 3
    with pytest.raises(ConditionConflict, match="INVALID_TRANSITION"):
        recovered.transition(condition.condition_id, ConditionState.FILLED,
            expected_prior_version=3, idempotency_key="bad", actor_id="test", reason_code="BAD")
    with pytest.raises(ConditionConflict, match="EXPECTED_PRIOR_VERSION"):
        recovered.cancel(condition.condition_id, expected_prior_version=2,
                         idempotency_key="cancel", actor_id="user")
    cancelled = recovered.cancel(condition.condition_id, expected_prior_version=3,
                                 idempotency_key="cancel", actor_id="user")
    assert cancelled.state is ConditionState.CANCELLED


def test_predicate_rejects_forming_wrong_symbol_and_duplicate_event(tmp_path):
    service, condition, _ = armed(tmp_path)
    event = {
        "candle_id": "NIFTY:3m:1", "symbol": "NIFTY", "timeframe": "3m",
        "closed": False, "close": 24405, "low": 24399, "high": 24408,
        "quote_timestamp": NOW.isoformat(),
        "option_quote": {"contract_id": "12345", "bid": 100, "ask": 100.2,
                         "timestamp": NOW.isoformat(), "ose_confirmed": True},
        "context": {"direction": "BULLISH"},
    }
    passed, checks = ConditionEvaluator.evaluate(condition, event, observed_at=NOW)
    assert not passed and not checks["completed_candle"]
    event.update({"closed": True, "symbol": "BANKNIFTY"})
    assert ConditionEvaluator.evaluate(condition, event, observed_at=NOW)[0] is False
    event.update({"symbol": "NIFTY", "option_quote": {"contract_id": "12345", "ask": None,
                  "timestamp": (NOW - timedelta(minutes=1)).isoformat()}})
    passed, checks = ConditionEvaluator.evaluate(condition, event, observed_at=NOW)
    assert passed is False and checks["quote_freshness"] is False and checks["spread"] is False


def test_live_authorization_stays_denied_but_exact_paper_can_pass(tmp_path):
    _, _, risk, _, _ = paper_components(tmp_path)
    live = risk.authorize(RiskAuthorizationRequest(
        operation="PLACE", method="POST", endpoint="/orders", request_id="live-1",
        symbol="NIFTY", side="BUY", quantity=75, price=100, stop_price=95,
        market_data_timestamp=NOW,
    ))
    assert not live.allowed and live.reason_code == "LIVE_TRADING_DISABLED"
    order, request, authorization = order_and_auth(risk)
    assert authorization.allowed and authorization.paper_only
    assert authorization.paper_order_request_hash == order.content_hash
    assert not authorization.live_trading_enabled and not authorization.broker_submission
    duplicate = risk.authorize_exact_paper(request)
    assert not duplicate.allowed and duplicate.reason_code == "DUPLICATE_REQUEST"


def test_internal_paper_fill_protection_guardian_stop_and_restart(tmp_path):
    state, ledger, risk, adapter, quote = paper_components(tmp_path)
    order, _, authorization = order_and_auth(risk)
    result = adapter.submit(order, authorization, quote)
    assert result["state"] == "FILLED" and result["paper_state_applied"] is True
    assert result["intent"]["broker_submission_requested"] is False
    paper_bytes = state.path.read_bytes()
    assert adapter.trade(result["position_id"])["status"] == "OPEN"
    assert state.path.read_bytes() == paper_bytes
    protection = adapter.establish_protection(
        condition_id=order.condition_id, position_id=result["position_id"],
        authorization=authorization, request=order,
        structural_invalidation_id="structural-invalidation-1",
        time_exit_at=(NOW + timedelta(minutes=10)).isoformat(),
    )
    recovered = Phase5PaperExecutionAdapter(tmp_path / "execution", ledger=ledger,
                                             paper_state=state, clock=lambda: NOW)
    assert recovered.protection(protection.protection_id).content_hash == protection.content_hash
    guardian = IndependentPaperGuardian(tmp_path / "guardian", execution=recovered, clock=lambda: NOW)
    hold = guardian.cycle(protection, {"event_id": "quote-1", "paper_route_healthy": True,
        "kill_switch_active": False, "quote_fresh": True, "bid": 100.0,
        "premium_confirmed": True, "structural_invalidated": False,
        "authority_material_reversal": False})
    assert hold["action"] == "HOLD"
    exited = guardian.cycle(protection, {"event_id": "quote-2", "paper_route_healthy": True,
        "kill_switch_active": False, "quote_fresh": True, "bid": 94.9,
        "premium_confirmed": True, "structural_invalidated": False,
        "authority_material_reversal": False})
    assert exited["action"] == "EXIT"
    assert not state.load().open_positions and state.load().closed_trades
    assert all((row["intent"].get("live_trading_enabled") is False) for row in ledger.list_orders(limit=100)["orders"])


def test_partial_fill_is_not_reported_as_full_and_is_protected(tmp_path):
    state, ledger, risk, adapter, quote = paper_components(tmp_path, depth=30)
    order, _, authorization = order_and_auth(risk)
    result = adapter.submit(order, authorization, quote)
    assert result["partial_fill"] is True
    assert result["position"]["raw_quantity"] == 30
    assert result["state"] == "CANCELLED"
    assert ledger.get_order(result["intent"]["intent_id"])["filled_quantity"] == 30


def test_contracts_forbid_fixed_or_unsupported_plan_and_stop_loosening(tmp_path):
    with pytest.raises(ConditionContractError):
        seal(DynamicPaperPlan(
            contract_id="12345", option_type="CE", entry_band=(100, 101), expected_entry=100,
            structural_invalidation_id="inv", premium_hard_stop=95,
            stop_mapping_status="LOW_CONFIDENCE", natural_target_ids=(), natural_target_premiums=(),
            resulting_rr=(), estimated_round_trip_cost=1, maximum_slippage=.2,
        ))
    _, _, risk, adapter, quote = paper_components(tmp_path)
    order, _, authorization = order_and_auth(risk)
    result = adapter.submit(order, authorization, quote)
    protection = adapter.establish_protection(condition_id=order.condition_id,
        position_id=result["position_id"], authorization=authorization, request=order,
        structural_invalidation_id="inv", time_exit_at=(NOW + timedelta(minutes=5)).isoformat())
    with pytest.raises(Exception, match="STOP_LOOSENING_FORBIDDEN"):
        adapter.tighten_stop(protection, 94, 100)


def test_openalgo_truth_and_safety_projection(tmp_path):
    from src.oracle.conditions.workflow import Phase5OracleWorkflow
    workflow = object.__new__(Phase5OracleWorkflow)
    truth = workflow.openalgo_capability()
    assert truth["production_reliability"] == "UNPROVEN"
    assert truth["fallback"] == "INTERNAL_PAPER_ENGINE"
    assert truth["live_mutation"] is False


def test_monitor_requires_acceptance_then_retest_deduplicates_and_recovers(tmp_path):
    current = [NOW]
    service, condition, _ = armed(tmp_path)
    events = [{
        "candle_id": "nifty-3m-1", "symbol": "NIFTY", "timeframe": "3m",
        "closed": True, "close": 24405, "low": 24399, "high": 24408,
        "candle_closed_at": (NOW + timedelta(minutes=3)).isoformat(),
        "quote_timestamp": (NOW + timedelta(minutes=3)).isoformat(),
        "option_quote": {"contract_id": "12345", "bid": 100, "ask": 100.2,
            "timestamp": (NOW + timedelta(minutes=3)).isoformat(), "ose_confirmed": True},
        "context": {"direction": "BULLISH"}, "source_hashes": {"canonical": "1"},
    }]
    triggers = []
    monitor = ConditionMonitor(service, context_provider=lambda _: events[-1],
        on_trigger=lambda cond, trigger: triggers.append(trigger), clock=lambda: current[0])
    current[0] = NOW + timedelta(minutes=3)
    assert monitor.cycle() == 0
    assert not triggers
    assert monitor.cycle() == 0  # same canonical candle is deduplicated
    current[0] = NOW + timedelta(minutes=6)
    events.append({**events[-1], "candle_id": "nifty-3m-2",
        "candle_closed_at": current[0].isoformat(), "quote_timestamp": current[0].isoformat(),
        "option_quote": {**events[-1]["option_quote"], "timestamp": current[0].isoformat()}})
    assert monitor.cycle() == 1
    assert len(triggers) == 1
    assert service.store.projection(condition.condition_id).state is ConditionState.TRIGGERED
    recovered = OracleConditionService(tmp_path / "conditions", clock=lambda: current[0])
    assert recovered.store.projection(condition.condition_id).state is ConditionState.TRIGGERED


class _Hash:
    def __init__(self, **values):
        self.__dict__.update(values)
    def verify_hash(self):
        return True


def _analysis_result(*, action="BUY", contract="12345", rr=(2.0,), fresh=True):
    source_states = {name: "FRESH" if fresh else "STALE" for name in
                     ("context", "argus", "vob", "ose", "canonical_features")}
    estimate = _Hash(executable=True, target_premiums=(110.0,), premium_hard_stop_candidate=95.0,
        resulting_rr=rr, entry_band=(99.5, 100.5), expected_entry=100.0,
        stop_mapping_status="LOW_CONFIDENCE_DISCLOSED", estimated_round_trip_cost=1.5,
        estimated_one_way_slippage=.1)
    return _Hash(
        snapshot=_Hash(analysis_id="analysis-fresh-12345678", content_hash="s" * 64,
            candidate_contracts=(_Hash(contract_id="12345", option_type="CE"),),
            source_states=source_states, data_completeness=100),
        decision=_Hash(decision_id="decision-fresh-12345678", content_hash="d" * 64,
            action=action, selected_contract_id=contract),
        option_capture=_Hash(execution_estimate=estimate),
        timing=_Hash(entry_extended=False),
        underlying=_Hash(invalidations=(_Hash(invalidation_id="inv-natural-1"),),
            natural_targets=(_Hash(target_id="target-natural-1"),)),
    )


def test_revalidation_rebuilds_dynamic_natural_plan_and_rejects_material_drift(tmp_path):
    _, condition, _ = armed(tmp_path)
    from src.oracle.conditions.contracts import TriggerEvent
    trigger = seal(TriggerEvent(
        trigger_id="trigger-12345678", condition_id=condition.condition_id,
        correlation_id=condition.correlation_id, canonical_event_id="event-12345678",
        candle_id="candle-12345678", candle_timeframe="3m",
        candle_closed_at=NOW.isoformat(), candle_close=24405,
        quote_timestamp=NOW.isoformat(), observed_at=NOW.isoformat(),
        predicate_results={"all": True}, source_hashes={"candle": "h"}, non_live_fixture=True,
    ))
    service = _Hash(policy=_Hash(minimum_data_completeness=75),
                    create=lambda **_: _analysis_result())
    passed = Phase5RevalidationService(service, clock=lambda: NOW).revalidate(condition, trigger)
    assert passed.passed and passed.dynamic_plan.natural_target_ids == ("target-natural-1",)
    assert passed.dynamic_plan.stop_mapping_status == "LOW_CONFIDENCE_DISCLOSED"
    assert passed.execution_authority is False and passed.historical_probability_used is False
    drift_service = _Hash(policy=_Hash(minimum_data_completeness=75),
                          create=lambda **_: _analysis_result(action="WAIT", rr=(1.0,), fresh=False))
    rejected = Phase5RevalidationService(drift_service, clock=lambda: NOW).revalidate(condition, trigger)
    assert not rejected.passed and rejected.dynamic_plan is None
    assert {"DECISION_BUY", "MINIMUM_RR", "CRITICAL_SOURCES_FRESH"} <= set(rejected.material_drift)


def test_phase5_api_gets_are_side_effect_free_and_proposal_cannot_arm(tmp_path, monkeypatch):
    import app.main as main
    service = OracleConditionService(tmp_path / "api", clock=lambda: NOW)
    monkeypatch.setattr(main, "oracle_condition_service", service)
    request = main.OracleConditionProposalRequest(
        idempotency_key="proposal-api-idem", actor_id="user-api", correlation_id="corr-api",
        original_user_wording="Maybe buy if it looks good", structured={},
    )
    value = main.propose_oracle_condition(request)
    assert value["status"] == "CLARIFICATION_REQUIRED" and value["armed"] is False
    assert not (tmp_path / "api" / "definitions").exists()
    projection = service.arm(original_wording="Exact paper condition", structured=structured(),
        actor_id="user-api", correlation_id="corr-api-exact", idempotency_key="api-arm-idem",
        user_confirmed=True)
    files = {path: path.read_bytes() for path in (tmp_path / "api").rglob("*") if path.is_file()}
    assert main.oracle_condition(projection.condition_id)["projection"]["state"] == "WATCHING"
    assert main.oracle_condition_events(projection.condition_id)["hash_chained"] is True
    assert {path: path.read_bytes() for path in files} == files


def test_non_live_fixture_end_to_end_workflow_has_hash_lineage_and_no_broker(tmp_path):
    from src.oracle.conditions import Phase5OracleWorkflow
    from src.oracle.conditions.contracts import TriggerEvent
    conditions, condition, projection = armed(tmp_path)
    trigger = seal(TriggerEvent(
        trigger_id="trigger-e2e-12345678", condition_id=condition.condition_id,
        correlation_id=condition.correlation_id, canonical_event_id="fixture-event-12345678",
        candle_id="fixture-candle-12345678", candle_timeframe="3m",
        candle_closed_at=NOW.isoformat(), candle_close=24405,
        quote_timestamp=NOW.isoformat(), observed_at=NOW.isoformat(),
        predicate_results={"all": True}, source_hashes={"fixture": "f" * 64},
        non_live_fixture=True,
    ))
    conditions.transition(condition.condition_id, ConditionState.TRIGGERED,
        expected_prior_version=projection.version, idempotency_key="fixture-trigger-transition",
        actor_id="FIXTURE_MONITOR", reason_code="NON_LIVE_FIXTURE_TRIGGER",
        details={"trigger_id": trigger.trigger_id})
    state, ledger, risk, paper, quote = paper_components(tmp_path / "e2e")
    analysis = _Hash(policy=_Hash(minimum_data_completeness=75), create=lambda **_: _analysis_result())
    revalidation = Phase5RevalidationService(analysis, clock=lambda: NOW)
    guardian = IndependentPaperGuardian(tmp_path / "e2e" / "guardian", execution=paper, clock=lambda: NOW)
    workflow = Phase5OracleWorkflow(conditions=conditions, revalidation=revalidation,
        risk=risk, paper=paper, guardian=guardian, quote_provider=lambda _: quote,
        clock=lambda: NOW)
    workflow.handle_trigger(condition, trigger)
    final = conditions.store.projection(condition.condition_id)
    assert final.state is ConditionState.MANAGING
    assert final.authorization_id and final.order_id and final.position_id and final.protection_id
    assert state.load().open_positions[0].instrument_id == condition.selected_option_id
    all_events = conditions.store.events(condition.condition_id)
    assert all(row["previous_hash"] == ("GENESIS" if index == 0 else all_events[index - 1]["record_hash"])
               for index, row in enumerate(all_events))
    assert workflow.performance()["risk_authorization"]["p95_ms"] is not None
    assert all(not row["intent"]["broker_submission_requested"] for row in ledger.list_orders(limit=100)["orders"])


def test_unfilled_order_cancellation_and_hash_authorized_modification(tmp_path):
    _, _, risk, adapter, quote = paper_components(tmp_path)
    quote["ask"] = 101.0
    order, _, authorization = order_and_auth(risk)
    submitted = adapter.submit(order, authorization, quote)
    order_id = submitted["intent"]["intent_id"]
    assert submitted["state"] == "ACKNOWLEDGED" and submitted["filled_quantity"] == 0
    revised = seal(replace(order, content_hash="", order_request_id="paper-order-revised-12345678",
                           limit_price=100.4, estimated_maximum_loss=405.0,
                           idempotency_key="paper-order-revised-idem"))
    revised_request = ExactPaperAuthorizationRequest(
        request_id="risk-request-revised-12345678", condition_id=revised.condition_id,
        condition_hash="c" * 64, decision_id=revised.decision_id, decision_hash="d" * 64,
        revalidation_id=revised.revalidation_id, revalidation_hash="r" * 64,
        paper_order_request_id=revised.order_request_id, paper_order_request_hash=revised.content_hash,
        symbol="NIFTY", instrument_id="12345", side="BUY", quantity=75,
        executable_price_low=99.5, executable_price_high=100.5, price=100.4,
        stop_price=95.0, estimated_maximum_loss=405.0,
        market_data_timestamp=NOW, expires_at=NOW + timedelta(seconds=20),
        idempotency_key="risk-idem-revised-12345678",
    )
    revised_auth = risk.authorize_exact_paper(revised_request)
    modification = adapter.record_authorized_modification(order_id,
        revised_request=revised, authorization=revised_auth, idempotency_key="modify-1")
    assert modification["status"] == "MODIFICATION_RECORDED"
    assert modification["broker_submission"] is False
    cancelled = adapter.cancel_order(order_id, reason="USER_CANCELLED", idempotency_key="cancel-order-1")
    assert cancelled["state"] == "CANCELLED"


def test_guardian_partial_exit_preserves_remaining_protection(tmp_path):
    state, _, risk, adapter, quote = paper_components(tmp_path)
    order, _, authorization = order_and_auth(risk)
    result = adapter.submit(order, authorization, quote)
    protection = adapter.establish_protection(condition_id=order.condition_id,
        position_id=result["position_id"], authorization=authorization, request=order,
        structural_invalidation_id="inv", time_exit_at=(NOW + timedelta(minutes=5)).isoformat())
    guardian = IndependentPaperGuardian(tmp_path / "guardian", execution=adapter, clock=lambda: NOW)
    partial = guardian.cycle(protection, {"event_id": "partial-target", "paper_route_healthy": True,
        "kill_switch_active": False, "quote_fresh": True, "bid": 110,
        "premium_confirmed": True, "structural_invalidated": False,
        "authority_material_reversal": False, "partial_exit_quantity": 30})
    assert partial["action"] == "PARTIAL_EXIT"
    assert partial["outcome"]["status"] == "PARTIALLY_CLOSED"
    assert state.load().open_positions[0].remaining_quantity == 45
    assert adapter.protection(protection.protection_id).status == "ACTIVE"


def test_forbidden_dependencies_and_locked_safety_configuration():
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(path.read_text(encoding="utf-8").lower()
                       for path in (root / "src" / "oracle" / "conditions").glob("*.py"))
    for forbidden in (
        "from src.broker", "import src.broker", "dhan_client", "openalgoanalyzerclient",
        "from src.oracle.knowledge", "from src.oracle.similarity", "from src.oracle.trade_planner",
        "import requests", "import httpx", "urllib.request",
    ):
        assert forbidden not in source
    settings = json.loads((root / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings["live_trading_enabled"] is False
    assert "live_trading_enabled=True" not in source.replace(" ", "")
    assert "broker_submission=True" not in source.replace(" ", "")
