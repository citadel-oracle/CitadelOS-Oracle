from dataclasses import replace
from datetime import datetime
import json

import pytest

from app.main import app
from src.aegis.ledger import AegisDecisionLedger, AegisLedgerError
from src.aegis.models import AegisInputSnapshot
from src.aegis.providers import AegisInputBuilder
from src.aegis.policy import WEIGHTS, strategy_eligibility
from src.aegis.service import AegisService


pytestmark = pytest.mark.unit


def snapshot(**changes):
    eligibility = strategy_eligibility("simple_pullback", "NIFTY", "5m", "OPEN", "TRENDING")
    base = AegisInputSnapshot(
        generated_at="2026-07-13T10:00:00+05:30", symbol="NIFTY", timeframe="5m",
        strategy_id="simple_pullback", strategy_name="Simple Pullback", strategy_version=None,
        requested_side="CE", session_state="OPEN", session_date="2026-07-13",
        technical={"status":"READY","bias":"BULLISH","signal":"BUY","confidence":90,"regime":"TRENDING","freshness":"LIVE"},
        argus={"status":"available","verdict":"BULLISH","confidence":85,"freshness":"fresh","alignment":"CE","reason_codes":[]},
        kronos_core={"status":"AVAILABLE","setup_quality":90,"timing_state":"VALID","trend":"BULLISH"},
        kronos_alpha={"status":"READY","expected_direction":"BULLISH","persistence":.8,"reversal_probability":.2,"uncertainty":.2,"option_buying_quality":80,"shadow":True,"direct_execution_weight":0},
        athena={"status":"READY","risk_state":"SAFE","recommendation":"CONTINUE","recommended_size_multiplier":1.0,"headroom":90},
        hermes={"status":"READY","event_risk":"LOW","recommendation":"NORMAL","sentiment":"NEUTRAL"},
        personal_oracle={"status":"available","maturity":"STABLE","context_coverage":50,"behavior_coverage":50,"recommendation":"PREFER"},
        risk_authorization={"decision":None,"reason_code":None}, kill_switch_active=False, kill_switch_state="INACTIVE",
        live_trading_enabled=False, live_path_requested=False, paper_state_health="HEALTHY",
        market_data_freshness="LIVE", duplicate_request=False, strategy_eligibility=eligibility,
        required_input_presence={"technical":True,"argus":True,"kronos_core":True,"athena":True},
        source_timestamps={"technical":"2026-07-13T09:59:55+05:30"},
    )
    return replace(base, **changes)


def service_for(value, tmp_path):
    return AegisService(lambda **_: value, ledger=AegisDecisionLedger(tmp_path / "aegis.json"), now_provider=lambda: datetime.fromisoformat("2026-07-13T10:00:01+05:30"))


def decide(tmp_path, value=None):
    return service_for(value or snapshot(), tmp_path).assess("NIFTY", "CE")


def test_decision_contract_is_explicitly_advisory_and_preserves_input_snapshot(tmp_path):
    result=decide(tmp_path).to_dict()
    assert result["mode"]=="ADVISORY" and result["execution_influence"]=="ZERO"
    assert result["recommendation_is_execution_decision"] is False
    assert result["input_snapshot"]["symbol"]=="NIFTY" and result["input_snapshot_version"]==1


def test_latest_advisory_never_invokes_input_provider(tmp_path):
    calls=[]
    service=AegisService(lambda **kwargs: calls.append(kwargs),ledger=AegisDecisionLedger(tmp_path/"aegis.json"))
    result=service.latest_advisory("NIFTY","CE")
    assert calls==[] and result["recommendation"]=="PAUSE" and result["execution_influence"]=="ZERO"


def test_prepared_snapshot_composition_performs_no_provider_rereads():
    def forbidden(*_args, **_kwargs): raise AssertionError("provider reread")
    builder=AegisInputBuilder(technical=forbidden,argus=forbidden,dashboard_cache=forbidden,
        kronos_alpha=forbidden,athena=forbidden,hermes=forbidden,personal_oracle=forbidden,
        risk=forbidden,paper=forbidden,session=forbidden,
        now_provider=lambda:datetime.fromisoformat("2026-07-13T10:00:01+05:30"))
    prepared={
        "technical":{"oracle_status":"READY","directional_bias":"BULLISH","signal":"BUY","confidence":90,"regime":"TRENDING","data_status":"LIVE"},
        "argus":{"status":"available","freshness":"fresh","data":{"underlying":{"fetched_at":"2026-07-13T10:00:00+05:30"},"verdict":{"bias":"BULLISH","confidence":85,"preferred_option_side":"CE"}}},
        "kronos_alpha":{"model_status":"READY","expected_direction":"BULLISH","trend_persistence_probability":.8,"reversal_probability":.2,"outlooks":{"ce":{"option_buying_quality_score":80}}},
        "kronos_core":{"status":"AVAILABLE","setup_quality":90,"timing_state":"VALID","trend":"BULLISH"},
        "athena":{"athena_status":"READY","recommendation":"CONTINUE","recommended_size_multiplier":1.0},
        "hermes":{"hermes_status":"READY","recommendation":"NORMAL"},
        "personal_oracle":{"status":"available","maturity":"STABLE","coverage":{},"behavior":{},"coaching":{"recommendations":[]}},
        "risk":{"kill_switch_active":False,"kill_switch_state":"INACTIVE","live_trading_enabled":False},
        "paper":{"state_health":"HEALTHY"}, "session":{"session_state":"OPEN","session_date":"2026-07-13"},
    }
    result=builder.from_prepared(symbol="NIFTY",requested_side="CE",strategy_id="simple_pullback",live_path_requested=False,duplicate_request=False,prepared=prepared)
    assert result.symbol=="NIFTY" and result.requested_side=="CE" and result.kronos_core["status"]=="AVAILABLE"


def test_weights_are_frozen_and_total_100():
    assert WEIGHTS == {"technical":25,"kronos_core":25,"argus":20,"personal_oracle":15,"hermes":10,"athena":5}
    assert sum(WEIGHTS.values()) == 100


@pytest.mark.parametrize("changes,reason", [
    ({"kill_switch_active":True}, "KILL_SWITCH_ACTIVE"),
    ({"risk_authorization":{"decision":"DENY"}}, "RISK_AUTHORIZATION_DENY"),
    ({"duplicate_request":True}, "DUPLICATE_REQUEST"),
    ({"live_path_requested":True}, "LIVE_TRADING_DISABLED"),
    ({"paper_state_health":"UNAVAILABLE"}, "CRITICAL_SYSTEM_STATE_UNAVAILABLE"),
])
def test_absolute_block_gates(tmp_path, changes, reason):
    decision = decide(tmp_path, replace(snapshot(), **changes))
    assert decision.decision == "BLOCK" and reason in decision.hard_gate_reasons
    assert decision.execution_permission is False


@pytest.mark.parametrize("state,reason", [("UNKNOWN", "KILL_SWITCH_UNKNOWN"), ("CORRUPT", "KILL_SWITCH_CORRUPT")])
def test_unreadable_authoritative_kill_switch_blocks(tmp_path, state, reason):
    decision = decide(tmp_path, replace(snapshot(), kill_switch_active=None, kill_switch_state=state))
    assert decision.decision == "BLOCK"
    assert decision.hard_gate_reasons == (reason,)


def test_inactive_authoritative_kill_switch_does_not_force_approval(tmp_path):
    value = replace(snapshot(), kill_switch_active=False, kill_switch_state="INACTIVE", session_state="WEEKEND",
                    strategy_eligibility=strategy_eligibility("simple_pullback", "NIFTY", "5m", "WEEKEND"))
    decision = decide(tmp_path, value)
    assert decision.decision == "WAIT"
    assert decision.hard_gate_reasons == ("MARKET_CLOSED",)


def test_market_closed_wait_is_stable(tmp_path):
    value = replace(snapshot(), session_state="WEEKEND", strategy_eligibility=strategy_eligibility("simple_pullback","NIFTY","5m","WEEKEND"))
    service = service_for(value, tmp_path)
    first = service.assess("NIFTY", "CE"); second = service.assess("NIFTY", "CE")
    assert first.decision == "WAIT" and "MARKET_CLOSED" in first.hard_gate_reasons
    assert first.decision_id == second.decision_id


def test_read_projection_is_idempotent_and_does_not_append_ledger(tmp_path):
    value = snapshot()
    service = service_for(value, tmp_path)

    first = service.project("NIFTY", "CE")
    second = service.project("NIFTY", "CE")

    assert first.decision_id == second.decision_id
    assert first.generated_at == second.generated_at
    assert service.ledger.history() == []
    persisted = service.assess("NIFTY", "CE")
    assert persisted.decision_id == first.decision_id
    assert len(service.ledger.history()) == 1


def test_unconfigured_hermes_provider_does_not_create_event_wait(tmp_path):
    value = replace(
        snapshot(),
        hermes={
            "status": "NOT_CONFIGURED",
            "event_risk": "UNKNOWN",
            "recommendation": "WAIT",
            "reason_codes": ["EXTERNAL_PROVIDER_NOT_CONFIGURED"],
        },
    )

    decision = decide(tmp_path, value)

    assert "HERMES_EVENT_WAIT" not in decision.hard_gate_reasons
    assert not any(item.conflict_id == "hermes-event" for item in decision.conflicts)
    assert decision.component_scores["hermes"] is None
    assert decision.data_coverage_percentage == 90.0


@pytest.mark.parametrize("changes,reason", [
    ({"market_data_freshness":"STALE"}, "CRITICAL_MARKET_DATA_STALE"),
    ({"athena":{"status":"READY","recommendation":"PAUSE","recommended_size_multiplier":.25}}, "ATHENA_PAUSE"),
    ({"hermes":{"status":"READY","recommendation":"WAIT"}}, "HERMES_EVENT_WAIT"),
    ({"required_input_presence":{"technical":True,"argus":False,"kronos_core":True,"athena":True}}, "MANDATORY_ARGUS_UNAVAILABLE"),
])
def test_wait_gates(tmp_path, changes, reason):
    decision = decide(tmp_path, replace(snapshot(), **changes))
    assert decision.decision == "WAIT" and reason in decision.hard_gate_reasons


def test_unknown_strategy_rejects(tmp_path):
    eligibility = strategy_eligibility("unknown", "NIFTY", "5m", "OPEN")
    decision = decide(tmp_path, replace(snapshot(), strategy_id="unknown", strategy_name="Unknown", strategy_eligibility=eligibility))
    assert decision.decision == "REJECT" and "UNKNOWN_STRATEGY" in decision.hard_gate_reasons


@pytest.mark.parametrize("changes,reason", [
    ({"technical":{"status":"READY","bias":"BEARISH","signal":"SELL","confidence":90,"freshness":"LIVE"}}, "OPPOSITE_TECHNICAL_SIGNAL"),
    ({"kronos_core":{"status":"AVAILABLE","setup_quality":90,"timing_state":"INVALID","trend":"BULLISH"}}, "KRONOS_TIMING_INVALID"),
    ({"argus":{"status":"available","verdict":"BEARISH","confidence":90,"freshness":"fresh"}}, "MANDATORY_ARGUS_STRONGLY_OPPOSITE"),
    ({"kronos_alpha":{"status":"READY","persistence":.3,"reversal_probability":.8,"option_buying_quality":80}}, "HIGH_REVERSAL_LOW_PERSISTENCE"),
    ({"kronos_alpha":{"status":"READY","persistence":.8,"reversal_probability":.2,"option_buying_quality":30}}, "OPTION_BUYING_QUALITY_LOW"),
])
def test_reject_gates(tmp_path, changes, reason):
    decision = decide(tmp_path, replace(snapshot(), **changes))
    assert decision.decision == "REJECT" and reason in decision.hard_gate_reasons


def test_no_requested_side_is_assessment_only(tmp_path):
    decision = service_for(replace(snapshot(), requested_side="NONE"), tmp_path).assess("NIFTY", "NONE")
    assert decision.decision == "WAIT" and "ASSESSMENT_ONLY_NO_REQUESTED_SIDE" in decision.hard_gate_reasons


@pytest.mark.parametrize("score,expected", [(95,"APPROVE"),(70,"APPROVE_REDUCED"),(50,"WAIT"),(30,"REJECT")])
def test_all_soft_threshold_states(tmp_path, score, expected):
    value = replace(snapshot(), technical={"status":"READY","bias":"BULLISH","signal":"BUY","confidence":score,"freshness":"LIVE"},
                    kronos_core={"status":"AVAILABLE","setup_quality":score,"timing_state":"VALID","trend":"BULLISH"},
                    argus={"status":"available","verdict":"BULLISH","confidence":score,"freshness":"fresh"},
                    personal_oracle={"status":"available","recommendation":"PREFER" if score>=80 else "OBSERVE" if score>=45 else "AVOID"},
                    hermes={"status":"READY","recommendation":"NORMAL" if score>=65 else "CAUTION"},
                    athena={"status":"READY","recommendation":"CONTINUE","recommended_size_multiplier":score/100})
    decision = decide(tmp_path, value)
    assert decision.decision == expected
    assert decision.decision_score is None or 0 <= decision.decision_score <= 100


def test_stale_penalty_and_optional_coverage(tmp_path):
    fresh = decide(tmp_path / "fresh")
    stale_value = replace(snapshot(), argus={"status":"stale","verdict":"BULLISH","confidence":85,"freshness":"stale"},
                          personal_oracle={"status":"available","recommendation":None})
    stale = decide(tmp_path / "stale", stale_value)
    assert stale.component_scores["argus"] < fresh.component_scores["argus"]
    assert stale.component_scores["personal_oracle"] is None and stale.data_coverage_percentage == 85


def test_conflicts_are_typed_sorted_and_penalize(tmp_path):
    value = replace(snapshot(), kronos_core={"status":"AVAILABLE","setup_quality":90,"timing_state":"VALID","trend":"BEARISH"},
                    kronos_alpha={"status":"READY","persistence":.8,"reversal_probability":.8,"uncertainty":.8,"option_buying_quality":80})
    decision = decide(tmp_path, value)
    assert decision.conflicts and decision.conflicts[0].severity in {"HIGH","CRITICAL"}
    assert all(item.score_impact > 0 and item.reason_codes for item in decision.conflicts)


def test_ce_and_pe_logic_are_direction_specific(tmp_path):
    ce = decide(tmp_path / "ce")
    pe_value = replace(snapshot(), requested_side="PE",
        technical={"status":"READY","bias":"BEARISH","signal":"SELL","confidence":90,"freshness":"LIVE"},
        argus={"status":"available","verdict":"BEARISH","confidence":85,"freshness":"fresh"},
        kronos_core={"status":"AVAILABLE","setup_quality":90,"timing_state":"VALID","trend":"BEARISH"},
        kronos_alpha={"status":"READY","expected_direction":"BEARISH","persistence":.8,"reversal_probability":.2,"uncertainty":.2,"option_buying_quality":80})
    pe = service_for(pe_value, tmp_path / "pe").assess("NIFTY", "PE")
    assert ce.decision == "APPROVE" and pe.decision == "APPROVE"


def test_size_never_exceeds_athena(tmp_path):
    value = replace(snapshot(), athena={"status":"READY","recommendation":"REDUCE","recommended_size_multiplier":.5})
    decision = decide(tmp_path, value)
    assert decision.recommended_size_multiplier <= .5


def test_decision_contract_is_permanently_advisory(tmp_path):
    decision = decide(tmp_path)
    assert decision.advisory_only is True and decision.execution_permission is False
    assert decision.risk_authorization_required is False and decision.live_trading_enabled is False
    assert decision.schema_version == 1 and decision.input_fingerprint


def test_strategy_eligibility_contract_fails_closed():
    good = strategy_eligibility("simple_pullback","NIFTY","5m","OPEN")
    bad = strategy_eligibility("not-real","NIFTY","5m","OPEN")
    assert good.eligible is True and "technical" in good.required_modules
    assert bad.eligible is False and "UNKNOWN_STRATEGY" in bad.reason_codes


def test_ledger_persistence_duplicate_bound_and_corruption(tmp_path):
    ledger = AegisDecisionLedger(tmp_path / "aegis.json", max_records=2)
    decision = decide(tmp_path / "source")
    assert ledger.append(decision) is True and ledger.append(decision) is False
    assert len(AegisDecisionLedger(ledger.path).history()) == 1
    ledger.path.write_text("{bad", encoding="utf-8")
    with pytest.raises(AegisLedgerError): ledger.load()


def test_get_only_api_and_frontend_contract():
    routes = [(route.path, set(route.methods or ())) for route in app.routes if route.path.startswith("/v1/aegis")]
    assert len(routes) == 6 and all(methods == {"GET"} for _, methods in routes)
    page = open("citadel-dashboard/src/app/page.tsx", encoding="utf-8").read()
    assert "AEGIS — FINAL DECISION INTELLIGENCE" in page
    assert "Advisory only — does not control strategy execution." in page
    assert "Final advisory recommendation" in page
    assert "method: 'POST'" not in page


def test_no_sensitive_or_mutation_fields_in_decision(tmp_path):
    text = json.dumps(decide(tmp_path).to_dict()).lower()
    assert not any(token in text for token in ("access-token","api_key","credential","password","place_order"))
