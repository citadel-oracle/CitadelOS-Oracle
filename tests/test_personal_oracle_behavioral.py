from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from app.main import app
from src.oracle_personal.behavior import BehaviorClassifier, BehaviorPolicy
from src.oracle_personal.coaching import BehavioralCoaching
from src.oracle_personal.ledger import OracleLedgerError, PersonalOracleLedger
from src.oracle_personal.models import BehavioralEnrichment, OracleEvent
from src.oracle_personal.service import PersonalOracleService


pytestmark = pytest.mark.unit


def make_event(index=1, pnl=10.0, **changes):
    entry = datetime.fromisoformat("2026-06-01T09:30:00+05:30") + timedelta(minutes=index * 20)
    base = OracleEvent(
        oracle_event_id=f"event-{index}", source_type="TEST", source_record_id=str(index),
        immutable_source_hash=f"hash-{index}", captured_at=entry.isoformat(), entry_at=entry.isoformat(),
        exit_at=(entry + timedelta(minutes=5)).isoformat(), trading_date=entry.date().isoformat(),
        symbol="NIFTY", instrument_id=None, option_side="CE", strike=None, expiry=None,
        side="BUY", quantity=1, raw_quantity=1, lot_size=None, number_of_lots=None,
        entry_price=100, exit_price=100 + pnl, realized_pnl=pnl, realized_points=pnl,
        holding_seconds=300, outcome="WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
        exit_reason="TEST", r_multiple=None, brokerage=None, slippage=None,
        strategy_name=None, strategy_version=None, trade_number_of_day=index,
        weekday="Monday", time_bucket="OPENING",
    )
    return replace(base, **changes)


def classify(events, enrichments=()):
    return BehaviorClassifier().classify(events, enrichments)


def enrichment(event, **changes):
    base = BehavioralEnrichment("enrich-1", event.oracle_event_id, "2026-06-02T10:00:00+05:30", True)
    return replace(base, **changes)


@pytest.mark.parametrize("delay,expected", [(30, "ON_TIME"), (181, "LATE"), (-1, "EARLY")])
def test_entry_timing(delay, expected):
    event = make_event(signal_at=(datetime.fromisoformat(make_event().entry_at) - timedelta(seconds=delay)).isoformat())
    assert classify([event])[0].entry_timing == expected


def test_chase_entry_and_distance():
    row = classify([make_event(entry_reference_price=98)])[0]
    assert row.entry_distance_from_reference == 2 and row.chase_entry == "YES" and "CHASE_ENTRY" in row.mistake_tags


def test_early_and_plan_based_exit():
    early = make_event(exit_reason="MANUAL EXIT", planned_stop_price=90, planned_target_price=120)
    plan = make_event(2, 20, planned_stop_price=90, planned_target_price=120)
    assert classify([early])[0].exit_timing == "EARLY"
    assert classify([plan])[0].exit_timing == "PLAN_BASED"


@pytest.mark.parametrize("minutes,expected", [(5, "NO"), (10, "YES"), (20, "YES")])
def test_cooldown(minutes, expected):
    first = make_event(1)
    second_entry = datetime.fromisoformat(first.exit_at) + timedelta(minutes=minutes)
    second = replace(make_event(2), entry_at=second_entry.isoformat(), exit_at=(second_entry + timedelta(minutes=5)).isoformat())
    assert classify([first, second])[1].cooldown_respected == expected


def test_after_loss_sequence_and_repeats():
    first = make_event(1, -5, side="BUY", setup_tag="PULLBACK")
    second = replace(make_event(2), entry_at=(datetime.fromisoformat(first.exit_at) + timedelta(minutes=5)).isoformat(), side="BUY", setup_tag="PULLBACK")
    row = classify([first, second])[1]
    assert row.after_loss == "YES" and row.after_consecutive_losses == 1
    assert row.same_direction_repeat is True and row.same_setup_repeat is True


def test_size_and_athena_classification():
    row = classify([make_event(quantity=2, raw_quantity=2, recommended_quantity=1, athena_recommendation="PAUSE", athena_utilization=85)])[0]
    assert row.size_multiplier_used == 2 and row.exceeded_recommended_size == "YES"
    assert row.entered_during_athena_pause == "YES" and row.entered_near_daily_limit == "YES"


def test_context_alignment_and_risk_flags():
    event = make_event(technical_bias="BEARISH", argus_bias="BULLISH", kronos_core_quality=40,
                       kronos_alpha_direction="BEARISH", hermes_event_risk="WAIT",
                       kronos_alpha_uncertainty=.7, kronos_alpha_reversal_risk=.8)
    row = classify([event])[0]
    assert row.entered_against_technical_bias == "YES" and row.entered_against_argus == "NO"
    assert row.entered_with_weak_kronos_core == "YES" and row.entered_with_weak_kronos_alpha == "YES"
    assert row.entered_during_hermes_wait == "YES" and row.entered_during_high_uncertainty == "YES"
    assert row.entered_during_high_reversal_risk == "YES"


@pytest.mark.parametrize("field", [
    "entered_against_technical_bias", "entered_against_argus", "entered_with_weak_kronos_core",
    "entered_with_weak_kronos_alpha", "entered_during_hermes_wait",
    "entered_during_high_uncertainty", "entered_during_high_reversal_risk",
])
def test_missing_context_flags_remain_unknown(field):
    assert getattr(classify([make_event()])[0], field) == "UNKNOWN"


def test_unknown_stays_unknown_and_historical_context_not_reconstructed():
    row = classify([make_event(historical_backfill=True)])[0]
    assert row.entry_timing == "UNKNOWN" and row.entered_against_argus == "UNKNOWN"
    assert row.entered_with_weak_kronos_alpha == "UNKNOWN"


def test_policy_threshold_is_centralized():
    assert BehaviorPolicy().late_entry_seconds("5m") == 180


def test_enrichment_is_typed_sanitized_and_source_immutable(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    event = make_event(); assert ledger.append(event)
    enriched = enrichment(event, followed_plan="YES", mistake_tags=("MANUAL_OVERRIDE",), notes_reference="review-42")
    assert ledger.append_enrichment(enriched) is True
    assert ledger.append_enrichment(enriched) is False
    assert ledger.events()[0] == event
    assert ledger.enrichments()[0].followed_plan == "YES"


@pytest.mark.parametrize("changes", [
    {"notes_reference": "x" * 161}, {"notes_reference": "line\nbreak"},
    {"mistake_tags": ("FEAR",)}, {"setup_tags": ("unsafe tag!",)},
    {"confidence_before_trade": 101},
])
def test_enrichment_rejects_unsafe_fields(changes):
    with pytest.raises(ValueError): enrichment(make_event(), **changes)


def test_enrichment_unknown_event_rejected(tmp_path):
    with pytest.raises(OracleLedgerError): PersonalOracleLedger(tmp_path / "x.json").append_enrichment(enrichment(make_event()))


def comparison_events(attribute, bad_value, good_value, total=20):
    events = []; observations = []
    for index in range(total):
        event = make_event(index + 1, -5 if index < total // 2 else 10)
        events.append(event)
        observation = classify([event])[0]
        observations.append(replace(observation, **{attribute: bad_value if index < total // 2 else good_value}))
    return events, observations


@pytest.mark.parametrize("attribute,bad,good,expected_type", [
    ("cooldown_respected", "NO", "YES", "NO_COOLDOWN_COST"),
    ("exit_timing", "EARLY", "PLAN_BASED", "EARLY_EXIT_COST"),
    ("entry_timing", "LATE", "ON_TIME", "LATE_ENTRY_COST"),
    ("stop_respected", "NO", "YES", "STOP_DISCIPLINE_ISSUE"),
    ("target_respected", "NO", "YES", "TARGET_DISCIPLINE_ISSUE"),
    ("entered_with_weak_kronos_alpha", "YES", "NO", "KRONOS_ALPHA_ALIGNMENT_EDGE"),
    ("entered_during_hermes_wait", "YES", "NO", "EVENT_RISK_VIOLATION"),
    ("exceeded_recommended_size", "YES", "NO", "SIZE_DISCIPLINE_ISSUE"),
])
def test_behavioral_comparisons(attribute, bad, good, expected_type):
    events, observations = comparison_events(attribute, bad, good)
    findings = BehavioralCoaching().findings(events, observations)["findings"]
    assert any(item["type"] == expected_type for item in findings)


def test_post_loss_and_first_trade_comparisons():
    events = [make_event(i + 1, -5 if i < 10 else 10) for i in range(20)]
    observations = [replace(classify([event])[0], previous_trade_result="LOSS" if i < 10 else "WIN", trade_number_of_day=2 if i < 10 else 1) for i, event in enumerate(events)]
    types = {item["type"] for item in BehavioralCoaching().findings(events, observations)["findings"]}
    assert {"POST_LOSS_DEGRADATION", "SECOND_TRADE_WEAKNESS"} <= types


@pytest.mark.parametrize("attribute,expected_type", [
    ("entered_against_technical_bias", "CONTEXT_ALIGNMENT_EDGE"),
    ("entered_against_argus", "CONTEXT_ALIGNMENT_EDGE"),
    ("entered_during_high_uncertainty", "HIGH_UNCERTAINTY_ENTRY_COST"),
    ("entered_during_high_reversal_risk", "HIGH_REVERSAL_RISK_ENTRY_COST"),
    ("entered_during_athena_pause", "EVENT_RISK_VIOLATION"),
])
def test_additional_context_comparisons(attribute, expected_type):
    events, observations = comparison_events(attribute, "YES", "NO")
    assert any(item["type"] == expected_type for item in BehavioralCoaching().findings(events, observations)["findings"])


def test_ce_pe_and_manual_override_comparisons():
    events = [make_event(i + 1, -2 if i < 10 else 4, option_side="CE" if i < 10 else "PE") for i in range(20)]
    rows = [replace(classify([event])[0], mistake_tags=("MANUAL_OVERRIDE",) if i < 10 else ()) for i, event in enumerate(events)]
    types = {item["type"] for item in BehavioralCoaching().findings(events, rows)["findings"]}
    assert "CE_BEHAVIOR_EDGE" in types and "REPEATED_MISTAKE" in types


def test_findings_threshold_effect_size_maturity_and_language():
    events, observations = comparison_events("entry_timing", "LATE", "ON_TIME", 18)
    assert not any(item["type"] == "LATE_ENTRY_COST" for item in BehavioralCoaching().findings(events, observations)["findings"])
    events, observations = comparison_events("entry_timing", "LATE", "ON_TIME", 20)
    finding = BehavioralCoaching().findings(events, observations)["findings"][0]
    assert finding["effect_size"] is not None and finding["maturity"] == "COLLECTING"
    text = f"{finding['summary']} {' '.join(finding['limitations'])}".lower()
    assert "causal claim" in text and not any(word in text for word in ("fearful", "greedy", "undisciplined"))


def test_repeated_mistake_and_top_three_recommendations():
    events = [make_event(i + 1, -1 if i < 10 else 2) for i in range(20)]
    observations = [replace(classify([event])[0], mistake_tags=("LATE_ENTRY",), entry_timing="LATE" if i < 10 else "ON_TIME") for i, event in enumerate(events)]
    findings = BehavioralCoaching().findings(events, observations)["findings"]
    assert any(item["type"] == "REPEATED_MISTAKE" for item in findings)
    assert len(BehavioralCoaching().coaching(events, observations)["recommendations"]) <= 3


def test_coaching_insufficient_data_has_no_authority():
    event = make_event(); row = classify([event])[0]
    recommendation = BehavioralCoaching().coaching([event], [row])["recommendations"][0]
    assert recommendation["state"] == "INSUFFICIENT_DATA"
    assert recommendation["execution_authority"] is False and recommendation["risk_override"] is False


def test_scorecard_gated_and_no_personality_score():
    events = [make_event(i + 1) for i in range(10)]
    rows = [replace(classify([event])[0], followed_plan="YES") for event in events]
    scorecard = BehavioralCoaching().scorecard(rows)
    plan = next(item for item in scorecard["categories"] if item["category"] == "Plan Adherence")
    entry = next(item for item in scorecard["categories"] if item["category"] == "Entry Discipline")
    assert plan["score"] == 100 and plan["sample_size"] == 10
    assert entry["score"] is None and scorecard["overall_score"] is None


def test_coaching_action_labels_match_evidence_semantics():
    events, observations = comparison_events("entry_timing", "LATE", "ON_TIME")
    recommendation = BehavioralCoaching().coaching(events, observations)["recommendations"][0]
    assert recommendation["state"] == "OBSERVE"

    tagged = [replace(item, mistake_tags=("NO_COOLDOWN",)) for item in observations]
    states = {item["title"]: item["state"] for item in BehavioralCoaching().coaching(events, tagged)["recommendations"]}
    assert states["Repeated observable tag: No Cooldown"] == "IMPROVE"


def test_cooldown_score_label_describes_compliance():
    rows = [replace(classify([make_event(i + 1)])[0], cooldown_respected="YES") for i in range(10)]
    category = next(item for item in BehavioralCoaching().scorecard(rows)["categories"] if item["category"] == "Cooldown Compliance")
    assert category["score"] == 100


def test_trends_improving_deteriorating_and_insufficient():
    events = [make_event(i + 1, -5 if i < 10 else 10) for i in range(20)]
    rows = [replace(classify([event])[0], mistake_tags=("LATE_ENTRY",) if i < 10 else ()) for i, event in enumerate(events)]
    assert BehavioralCoaching().trends(events, rows)["label"] == "IMPROVING"
    assert BehavioralCoaching().trends(events[::-1], rows[::-1])["label"] == "IMPROVING"
    assert BehavioralCoaching().trends(events[:10], rows[:10])["label"] == "INSUFFICIENT_DATA"

    deteriorating_events = [make_event(i + 1, 10 if i < 10 else -5) for i in range(20)]
    deteriorating_rows = [replace(classify([event])[0], mistake_tags=() if i < 10 else ("LATE_ENTRY",)) for i, event in enumerate(deteriorating_events)]
    assert BehavioralCoaching().trends(deteriorating_events, deteriorating_rows)["label"] == "DETERIORATING"


def test_trend_stable_with_equal_windows():
    events = [make_event(i + 1, 1) for i in range(20)]
    rows = [classify([event])[0] for event in events]
    assert BehavioralCoaching().trends(events, rows)["label"] == "STABLE"


def test_read_only_routes_exist_and_no_mutation_routes():
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}
    for path in ("behavior", "coaching", "scorecard", "trends", "mistakes"):
        matches = [methods for route_path, methods in routes if route_path == f"/v1/personal-oracle/{path}"]
        assert matches == [("GET",)]
    assert not any(route_path.startswith("/v1/personal-oracle") and set(methods) & {"POST", "PUT", "PATCH", "DELETE"} for route_path, methods in routes)


def test_service_outputs_are_bounded_and_exclude_note_references(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    for i in range(1, 4): ledger.append(make_event(i))
    ledger.append_enrichment(enrichment(ledger.events()[0], notes_reference="private-reference"))
    service = PersonalOracleService(ledger=ledger)
    assert len(service.behavior()["observations"]) == 3
    for payload in (service.behavior(), service.coaching(), service.scorecard(), service.trends(), service.mistakes()):
        assert "private-reference" not in str(payload)


def test_live_trading_disabled_and_foundation_identity_stable():
    import json
    assert json.load(open("config/settings.json", encoding="utf-8"))["live_trading_enabled"] is False
    assert make_event().oracle_event_id == "event-1"


def test_frontend_contract_has_no_mutation_controls():
    page = open("citadel-dashboard/src/app/page.tsx", encoding="utf-8").read()
    provider = open("citadel-dashboard/src/dashboard/providers/RestDashboardProvider.ts", encoding="utf-8").read()
    assert "Personal Trading Intelligence" in page
    assert "Collecting evidence. No threshold-qualified observation yet." in page
    assert "fetch(" in provider
    assert "method: 'POST'" not in page


def test_frontend_keeps_existing_modules_and_mobile_contract():
    page = open("citadel-dashboard/src/app/page.tsx", encoding="utf-8").read()
    css = open("citadel-dashboard/src/app/globals.css", encoding="utf-8").read()
    for label in ("Mission Control", "Market Matrix", "Active Trade", "ARGUS", "KRONOS ALPHA", "Technical Intelligence", "Athena", "Hermes"):
        assert label in page
    assert "@media (max-width: 420px)" in css and "personal-oracle-scorecard" in css
