import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from src.api.v2_integration import V2DashboardIntegration
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.lite import PersonalOracleLite, StrategyLabOracleSource
from src.oracle_personal.models import OracleEvent, OracleObservation
from src.oracle_personal.service import PersonalOracleService
from src.strategy_lab.storage import StrategyRegistryStore


pytestmark = pytest.mark.unit


def metadata(strategy_id, family="FUTURE"):
    return {
        "strategy_id": strategy_id,
        "name": f"{family} strategy",
        "version": "1.0",
        "author": "test",
        "input_type": "PYTHON_STRATEGY",
        "supported_markets": ["NIFTY"],
        "supported_timeframes": ["3m"],
        "rr": 2,
        "risk_model": "FIXED",
        "parameters": {"strategy_family": family, "option_type": "CE"},
    }


def state(strategy_id, index=1, pnl=50.0, diagnostic=None):
    order_open = {
        "order_id": f"open-{strategy_id}-{index}", "position_id": f"pos-{strategy_id}-{index}",
        "contract": "NIFTY 25000 CE", "position_effect": "OPEN", "requested_quantity": 65,
        "lot_size": 65, "created_at": "2026-07-15T09:30:00+05:30",
        "protective_stop": 95, "target_price": 110,
    }
    order_close = {
        "order_id": f"close-{strategy_id}-{index}", "position_id": f"pos-{strategy_id}-{index}",
        "contract": "NIFTY 25000 CE", "position_effect": "CLOSE",
        "exit_reason": "TARGET" if pnl > 0 else "STOP", "rejection_reason": diagnostic,
    }
    fills = [
        {"fill_id": f"fill-open-{strategy_id}-{index}", "order_id": order_open["order_id"], "position_effect": "OPEN", "quantity": 65},
        {"fill_id": f"fill-close-{strategy_id}-{index}", "order_id": order_close["order_id"], "position_effect": "CLOSE", "quantity": 65},
    ]
    trade = {
        "trade_id": f"trade-{strategy_id}-{index}", "position_id": f"pos-{strategy_id}-{index}",
        "strategy_id": strategy_id, "contract": "NIFTY 25000 CE", "side": "LONG",
        "average_price": 100, "exit": 101 if pnl > 0 else 99, "realized_pnl": pnl,
        "entry_time": f"2026-07-15T09:{30 + index:02d}:00+05:30",
        "exit_time": f"2026-07-15T09:{31 + index:02d}:00+05:30",
        "exit_reason": "TARGET" if pnl > 0 else "STOP", "mfe": 2, "mae": -1,
        "stop": 95, "target": 110, "lineage": [order_open["order_id"], order_close["order_id"]],
        "diagnostic_reason": diagnostic,
    }
    return {"strategy_id": strategy_id, "orders": [order_open, order_close], "fills": fills, "closed_trades": [trade]}


def install_strategy(root: Path, strategy_id: str, trades=None, family="FUTURE"):
    StrategyRegistryStore(root).register(metadata(strategy_id, family))
    runtime = root / "runtimes" / strategy_id
    runtime.mkdir(parents=True, exist_ok=True)
    payload = state(strategy_id) if trades is None else trades
    (runtime / "paper_engine_state.json").write_text(json.dumps(payload), encoding="utf-8")


def service(tmp_path):
    root = tmp_path / "strategy_lab"
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    return PersonalOracleService(ledger=ledger, strategy_lab_root=root), root


def test_dynamic_discovery_and_unknown_future_strategy(tmp_path):
    oracle, root = service(tmp_path)
    install_strategy(root, "unknown_future_strategy")
    assert [row["strategy_id"] for row in oracle.discover_strategies()] == ["unknown_future_strategy"]
    assert oracle.backfill_authoritative(dry_run=False)["inserted"] == 1
    assert oracle.ledger.events()[0].strategy_id == "unknown_future_strategy"


def test_production_source_contains_no_current_deployment_id_list():
    source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("src/oracle_personal/lite.py", "src/oracle_personal/service.py")
    )
    assert "PB_NIFTY_" not in source and "BO_NIFTY_" not in source


def test_dry_run_is_non_mutating_and_real_backfill_is_idempotent(tmp_path):
    oracle, root = service(tmp_path)
    install_strategy(root, "dynamic_strategy")
    source = root / "runtimes/dynamic_strategy/paper_engine_state.json"
    before = sha256(source.read_bytes()).hexdigest()
    dry = oracle.backfill_authoritative(dry_run=True)
    assert dry["inserted"] == 1 and not oracle.ledger.path.exists()
    first = oracle.backfill_authoritative(dry_run=False)
    second = oracle.backfill_authoritative(dry_run=False)
    assert first["inserted"] == 1 and second["duplicate"] == 1 and len(oracle.ledger.events()) == 1
    assert sha256(source.read_bytes()).hexdigest() == before


def test_configured_migration_cutoff_preserves_legacy_history_and_allows_future_trades(
    tmp_path, monkeypatch
):
    oracle, root = service(tmp_path)
    install_strategy(root, "migration_strategy")
    legacy = event_for("legacy", pnl=10)
    oracle.ledger.append(legacy)
    source_hash = sha256(oracle.ledger.path.read_bytes()).hexdigest()

    monkeypatch.setenv(
        "CITADEL_PERSONAL_ORACLE_MIN_EXIT_AT",
        "2026-07-15T09:40:00+05:30",
    )
    migrated = PersonalOracleService(
        ledger=oracle.ledger,
        strategy_lab_root=root,
    )
    result = migrated.backfill_authoritative()
    assert result["inserted"] == 0
    assert result["skipped"] == 1
    assert len(migrated.ledger.events()) == 1
    assert sha256(migrated.ledger.path.read_bytes()).hexdigest() == source_hash

    payload = state("migration_strategy", 20)
    install_strategy(root, "migration_strategy", payload)
    result = migrated.backfill_authoritative()
    assert result["inserted"] == 1
    assert len(migrated.ledger.events()) == 2


def test_configured_ledger_path_keeps_legacy_source_immutable(tmp_path, monkeypatch):
    source_path = tmp_path / "legacy-source.json"
    source_path.write_text(json.dumps({
        "schema_version": 1,
        "events": [event_for("legacy-source").to_dict()],
        "enrichments": [],
    }), encoding="utf-8")
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    compatibility_path = tmp_path / "personal-oracle-rc2.json"
    compatibility_path.write_bytes(source_path.read_bytes())
    monkeypatch.setenv(
        "CITADEL_PERSONAL_ORACLE_LEDGER_PATH",
        str(compatibility_path),
    )

    oracle = PersonalOracleService(strategy_lab_root=tmp_path / "strategy_lab")
    oracle.summary()
    assert oracle.ledger.path == compatibility_path
    assert len(oracle.ledger.events()) == 1
    assert sha256(source_path.read_bytes()).hexdigest() == source_hash
    assert sha256(compatibility_path.read_bytes()).hexdigest() != source_hash


def test_legacy_history_is_unified_without_duplicates_or_lost_evidence(tmp_path):
    source_path = tmp_path / "legacy.json"
    legacy_rows = [event_for(f"legacy-{index}", minute=30 + index * 2, pnl=-5 if index % 2 else 10) for index in range(6)]
    source_path.write_text(json.dumps({
        "schema_version": 1,
        "events": [{**row.to_dict(), "schema_version": 1} for row in legacy_rows],
        "enrichments": [],
    }), encoding="utf-8")
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    oracle, _ = service(tmp_path)
    dry = oracle.import_legacy_history(source_path, dry_run=True)
    first = oracle.import_legacy_history(source_path)
    second = oracle.import_legacy_history(source_path)
    summary = oracle.summary()
    assert dry["inserted"] == 6 and first["inserted"] == 6
    assert second["duplicate"] == 6 and summary["scope"]["observed_trade_count"] == 6
    assert summary["evidence"]["observed_trades"] == 6
    assert summary["evidence"]["behavior"]["observed_trades"] == 6
    assert summary["evidence"]["trends"]["current_window"]["sample_size"] >= 0
    assert sha256(source_path.read_bytes()).hexdigest() == source_hash
    assert "revenge" not in json.dumps(summary).lower()
    assert summary["execution_influence"] == "ZERO"


def test_canonical_event_is_traceable_and_never_fabricates_context(tmp_path):
    oracle, root = service(tmp_path)
    install_strategy(root, "canonical")
    oracle.backfill_authoritative(dry_run=False)
    event = oracle.ledger.events()[0]
    assert event.schema_version == 3
    assert event.source_type == "STRATEGY_LAB_CLOSED_TRADE"
    assert event.source_record_id == "trade-canonical-1"
    assert event.order_id == "open-canonical-1" and event.fill_id == "fill-open-canonical-1"
    assert event.manual_action_source is None
    assert event.kronos_snapshot_reference is None
    assert event.ingestion_mode == "RECONCILED"
    assert event.context_captured is False
    assert event.missing_context_fields == ("ENTRY_CONTEXT_ENVELOPE",)


def test_event_driven_ingestion_is_exactly_once_restart_safe_and_preserves_context(tmp_path):
    oracle, root = service(tmp_path)
    install_strategy(root, "event-driven")
    trade = state("event-driven")["closed_trades"][0]
    trade["oracle_entry_context"] = {
        "context_captured": True,
        "context_completeness_percentage": 80.0,
        "missing_context_fields": ["reference_price", "market_regime"],
        "source_trade_id": trade["trade_id"],
        "entry_timestamp": trade["entry_time"],
        "instrument": "NIFTY 25000 CE",
        "underlying": "NIFTY",
        "option_side": "CE",
        "strike": 25000.0,
        "expiry": "2026-07-30",
        "strategy": "event-driven",
        "setup": "PULLBACK",
        "timeframe": "3m",
        "entry_reason": "PULLBACK_CONFIRMED",
        "signal_price": 100.0,
        "reference_price": None,
        "stop_loss": 95.0,
        "target": 110.0,
        "market_regime": None,
        "quantity": 65,
        "entry_price": 100.0,
        "data_provenance": "STRATEGY_LAB_PAPER_ENGINE_ENTRY",
        "capture_timestamp": trade["entry_time"],
    }
    assert oracle.ingest_strategy_lab_trade(trade, source_event_id="evt_stable") is True
    assert oracle.ingest_strategy_lab_trade(trade, source_event_id="evt_stable") is False
    restarted = PersonalOracleService(ledger=oracle.ledger, strategy_lab_root=root)
    assert restarted.backfill_authoritative()["duplicate"] == 1
    event = restarted.ledger.events()[0]
    assert event.ingestion_mode == "EVENT_DRIVEN"
    assert event.source_event_id == "evt_stable"
    assert event.context_captured is True
    assert event.entry_context["source_trade_id"] == event.source_record_id
    assert event.entry_context["reference_price"] is None
    assert event.missing_context_fields == ("reference_price", "market_regime")
    projection = restarted.summary()
    assert projection["ingestion"]["label"] == "LIVE INGESTION"
    assert projection["ingestion"]["context_completeness_percentage"] == 80.0
    assert projection["execution_influence"] == "ZERO"


def test_event_driven_ingestion_respects_cutoff_policy(tmp_path, monkeypatch):
    oracle, root = service(tmp_path)
    install_strategy(root, "cutoff-live")
    monkeypatch.setenv("CITADEL_PERSONAL_ORACLE_MIN_EXIT_AT", "2026-07-15T10:00:00+05:30")
    guarded = PersonalOracleService(ledger=oracle.ledger, strategy_lab_root=root)
    assert guarded.ingest_strategy_lab_trade(state("cutoff-live")["closed_trades"][0]) is False
    assert guarded.ledger.events() == ()


def test_same_contract_trades_keep_separate_order_and_fill_lineage(tmp_path):
    oracle, root = service(tmp_path)
    first, second = state("lineage", 1), state("lineage", 2)
    combined = {
        "strategy_id": "lineage",
        "orders": first["orders"] + second["orders"],
        "fills": first["fills"] + second["fills"],
        "closed_trades": first["closed_trades"] + second["closed_trades"],
    }
    install_strategy(root, "lineage", combined)
    assert oracle.backfill_authoritative(dry_run=False)["inserted"] == 2
    assert {row.quantity for row in oracle.ledger.events()} == {65}
    assert {row.order_id for row in oracle.ledger.events()} == {"open-lineage-1", "open-lineage-2"}


def test_valid_loss_and_execution_defect_are_distinct(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    lite = PersonalOracleLite(ledger, StrategyLabOracleSource(tmp_path / "strategy_lab"))
    good = event_for("good", pnl=-10)
    defect = replace(event_for("defect", pnl=-10), diagnostic_reason="MISSING_AUTHORITATIVE_QUOTE")
    types = {row.oracle_event_id: set() for row in (good, defect)}
    for row in lite.classify((good, defect)):
        types[row.source_event_id].add(row.classification_type)
    assert "VALID_STRATEGY_OUTCOME" in types[good.oracle_event_id]
    assert "EXECUTION_DEFECT" not in types[good.oracle_event_id]
    assert {"EXECUTION_DEFECT", "MISSING_AUTHORITATIVE_QUOTE"} <= types[defect.oracle_event_id]


def test_automated_sequences_are_neutral_and_manual_behaviour_not_recorded(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    lite = PersonalOracleLite(ledger, StrategyLabOracleSource(tmp_path / "strategy_lab"))
    rows = (event_for("one", pnl=-10), event_for("two", minute=37, pnl=5))
    labels = {row.classification_type for row in lite.classify(rows)}
    assert {"RAPID_REENTRY", "LOSS_SEQUENCE_REENTRY", "SAME_DIRECTION_REPEAT"} <= labels
    assert "REVENGE" not in " ".join(labels)
    for row in rows:
        ledger.append(row)
    summary = PersonalOracleService(ledger=ledger, strategy_lab_root=tmp_path / "strategy_lab").summary()
    assert summary["behavior"]["manual_behaviour_status"] == "NOT_RECORDED"


def test_observation_noise_threshold_critical_alert_and_stable_identity(tmp_path):
    ledger = PersonalOracleLedger(tmp_path / "oracle.json")
    lite = PersonalOracleLite(ledger, StrategyLabOracleSource(tmp_path / "strategy_lab"))
    two = (event_for("a", pnl=-1), event_for("b", minute=50, pnl=-1))
    assert lite.observe(two, lite.classify(two)) == ()
    defect = (replace(event_for("critical"), diagnostic_reason="REJECTED_EXIT"),)
    first = lite.observe(defect, lite.classify(defect))
    critical = next(row for row in first if row.severity == "CRITICAL")
    unchanged = lite.observe(defect, lite.classify(defect), first)
    same = next(row for row in unchanged if row.observation_id == critical.observation_id)
    assert same.observation_id == critical.observation_id and same.version == critical.version
    expanded_events = defect + (replace(event_for("critical-2", minute=55), diagnostic_reason="REJECTED_EXIT"),)
    updated = lite.observe(expanded_events, lite.classify(expanded_events), first)
    changed = next(row for row in updated if row.observation_id == critical.observation_id)
    assert changed.version == critical.version + 1


def test_compact_summary_is_bounded_advisory_and_restart_safe(tmp_path):
    oracle, root = service(tmp_path)
    for index in range(4):
        strategy_id = f"strategy_{index}"
        payload = state(strategy_id, index + 1, pnl=-10, diagnostic="REJECTED_EXIT")
        install_strategy(root, strategy_id, payload, family="TEST")
    oracle.backfill_authoritative(dry_run=False)
    summary = oracle.summary()
    assert len(summary["insights"]["top_observations"]) <= 3
    assert summary["execution_influence"] == "ZERO"
    restarted = PersonalOracleService(ledger=PersonalOracleLedger(oracle.ledger.path), strategy_lab_root=root)
    assert len(restarted.ledger.events()) == 4
    assert restarted.ledger.classifications()
    assert restarted.ledger.observations()


def test_compact_summary_exposes_six_authoritative_hero_inputs(tmp_path):
    oracle, root = service(tmp_path)
    install_strategy(root, "future_strategy")
    oracle.backfill_authoritative(dry_run=False)
    summary = oracle.summary()
    assert set(summary["hero"]) == {
        "discovered_strategy_count",
        "needs_attention_count",
        "active_observation_count",
        "new_observation_count",
        "highest_priority_execution_issue",
        "highest_impact_performance_leak",
        "cooldown_compliance_percentage",
        "discipline_metric",
        "today_focus",
    }
    assert summary["hero"]["discovered_strategy_count"] == 1
    assert summary["hero"]["today_focus"] == summary["insights"]["today_focus"]
    assert summary["hero"]["highest_priority_execution_issue"] is None


def test_hero_priority_leak_and_discipline_are_deterministic():
    def observation(identity, title, category, severity, impact):
        return OracleObservation(
            observation_id=identity, version=1, title=title, summary=title,
            category=category, severity=severity, confidence=0.9, sample_size=4,
            affected_strategy_count=1, affected_strategy_ids=("future",),
            strategy_family="FUTURE", actual_realized_impact=impact,
            hypothetical_impact=None, first_detected_at="2026-07-15T09:00:00+05:30",
            last_updated_at="2026-07-15T09:00:00+05:30",
            evidence_references=("event",), status="NEW",
        )

    focus = {"text": "Authoritative focus", "confidence": 0.9, "sample_size": 12}
    hero = PersonalOracleService._hero_summary(
        [{"strategy_id": "future"}],
        {"needs_attention": 1},
        [
            observation("issue", "Rejected Exit", "EXECUTION_HEALTH", "CRITICAL", -5),
            observation("less", "Late Entry", "RISK", "IMPORTANT", -10),
            observation("top", "Rapid Reentry", "RISK", "IMPORTANT", -25),
        ],
        focus,
        {"categories": []},
        {"current_window": {"cooldown_compliance": 96.6}},
    )
    assert hero["highest_priority_execution_issue"] == "Rejected Exit"
    assert hero["highest_impact_performance_leak"] == "Rapid Reentry"
    assert hero["cooldown_compliance_percentage"] == 96.6
    assert hero["discipline_metric"] == {"label": "Cooldown compliance", "percentage": 96.6}
    assert hero["today_focus"] == focus


def test_one_hundred_strategies_aggregate_without_hardcoded_ids(tmp_path):
    oracle, root = service(tmp_path)
    for index in range(100):
        install_strategy(root, f"future_{index:03d}")
    assert len(oracle.discover_strategies()) == 100
    result = oracle.backfill_authoritative(dry_run=False)
    assert result["inserted"] == 100
    summary = oracle.summary()
    assert summary["scope"]["discovered_strategy_count"] == 100
    assert summary["scope"]["analysed_strategy_count"] == 100
    assert summary["hero"]["discovered_strategy_count"] == 100


def test_v2_uses_existing_personal_oracle_feed_without_unbounded_rescan(tmp_path):
    class CountingLedger(PersonalOracleLedger):
        event_reads = 0

        def events(self):
            self.event_reads += 1
            return super().events()

    root = tmp_path / "strategy_lab"
    ledger = CountingLedger(tmp_path / "oracle.json")
    oracle = PersonalOracleService(ledger=ledger, strategy_lab_root=root)
    calls = {"summary": 0}

    def personal():
        calls["summary"] += 1
        return oracle.summary()

    provider = lambda *args: {"status": "READY"}
    v2 = V2DashboardIntegration(
        snapshot=lambda: {}, kronos_alpha=provider, chronos2=provider, oracle=provider,
        athena=provider, hermes=provider, argus=provider, risk_status=provider,
        kill_switch=provider, paper_status=provider, personal_oracle=personal,
        aegis=provider, readiness=provider, next_session_plan=provider,
        order_ledger=provider, paper_trading=lambda: {"timeline": {"events": []}},
    )
    result = v2.dashboard()
    assert result["feeds"]["personal_oracle"]["data"]["execution_influence"] == "ZERO"
    assert calls["summary"] == 1
    reads = ledger.event_reads
    oracle.summary()
    assert ledger.event_reads == reads


def event_for(identity, minute=30, pnl=10.0):
    return OracleEvent(
        oracle_event_id=identity, source_type="TEST", source_record_id=identity,
        immutable_source_hash=identity, captured_at="2026-07-15T09:00:00+05:30",
        entry_at=f"2026-07-15T09:{minute:02d}:00+05:30",
        exit_at=f"2026-07-15T09:{minute + 1:02d}:00+05:30",
        trading_date="2026-07-15", symbol="NIFTY", instrument_id=None,
        option_side="CE", strike=None, expiry=None, side="LONG", quantity=65,
        raw_quantity=65, lot_size=65, number_of_lots=1, entry_price=100,
        exit_price=101 if pnl >= 0 else 99, realized_pnl=pnl,
        realized_points=1 if pnl >= 0 else -1, holding_seconds=60,
        outcome="WIN" if pnl > 0 else "LOSS", exit_reason="TARGET" if pnl > 0 else "STOP",
        r_multiple=None, brokerage=None, slippage=None, strategy_name="Test",
        strategy_version="1", trade_number_of_day=1, weekday="Wednesday",
        time_bucket="OPENING", strategy_id="dynamic", strategy_family="TEST",
        timeframe="3m", planned_stop_price=95, planned_target_price=110,
    )
