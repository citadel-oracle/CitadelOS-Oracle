import pytest
import json
from pathlib import Path

from app.main import strategy_lab_comparison, strategy_lab_service
from src.strategy_lab.service import StrategyLabService
from src.strategy_lab.strategies.bull_pulse import build_deployment_request as build_bp


def test_comparison_endpoint_returns_valid_payload_structure():
    data = strategy_lab_comparison()
    assert data["status"] == "available"
    assert data["paper_only"] is True
    assert "comparison" in data
    assert "deployments" in data

    comp = data["comparison"]
    assert "deployment_id" in comp
    assert "strategy_name" in comp
    assert "timeframe" in comp
    assert "argus_mode" in comp
    assert "runtime_health" in comp
    assert "evidence_status" in comp
    assert comp["evidence_status"] in ("NO_DATA", "INSUFFICIENT_SAMPLE", "COLLECTING", "REVIEW_READY")


def test_comparison_endpoint_supports_all_four_deployments():
    for dep_id in ("TC_NIFTY_PE_1M", "TC_NIFTY_PE_3M", "BP_NIFTY_CE_1M", "BP_NIFTY_CE_3M"):
        data = strategy_lab_comparison(deployment_id=dep_id)
        assert data["comparison"]["deployment_id"] == dep_id
        if "1M" in dep_id:
            assert data["comparison"]["argus_mode"] == "SHADOW"
        else:
            assert data["comparison"]["argus_mode"] == "OFF"


def test_empty_workspace_returns_no_data_status(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    result = service.comparison("TC_NIFTY_PE_1M")
    comp = result["comparison"]
    assert comp["evidence_status"] == "NO_DATA"
    assert comp["sample_size"] == 0
    assert comp["total_native_signals"] == 0
    assert comp["useful_blocks"] == 0
    assert comp["false_blocks"] == 0


def test_shadow_journal_metrics_and_deduplication(tmp_path):
    lab_root = tmp_path / "lab"
    dep_dir = lab_root / "runtimes" / "TC_NIFTY_PE_1M"
    dep_dir.mkdir(parents=True, exist_ok=True)

    paper_state = {
        "closed_trades": [
            {"trade_id": "trade-1", "realized_pnl": -500.0},
            {"trade_id": "trade-2", "realized_pnl": 800.0},
        ]
    }
    (dep_dir / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")

    journal_lines = [
        json.dumps({
            "event_type": "ARGUS_SHADOW_EVALUATION",
            "recorded_at": "2026-07-25T10:00:00+05:30",
            "payload": {
                "evaluation_id": "eval-1",
                "signal_id": "sig-1",
                "hypothetical_allow_block_delay": "BLOCK",
                "argus_status": "AVAILABLE",
                "confidence": 85.0,
                "reason_codes": ["PERSISTENCE_LOW"],
                "contract": {"trading_symbol": "NIFTY26JUL24000PE"}
            }
        }),
        json.dumps({
            "event_type": "ARGUS_SHADOW_OUTCOME",
            "recorded_at": "2026-07-25T10:30:00+05:30",
            "payload": {
                "signal_id": "sig-1",
                "trade_id": "trade-1",
                "native_outcome": "LOSS",
                "counterfactual_shadow_outcome": "AVOIDED_LOSS",
                "avoided_loss": 500.0,
                "missed_winner": 0.0,
                "net_pnl": -500.0
            }
        }),
        json.dumps({
            "event_type": "ARGUS_SHADOW_EVALUATION",
            "recorded_at": "2026-07-25T11:00:00+05:30",
            "payload": {
                "evaluation_id": "eval-2",
                "signal_id": "sig-2",
                "hypothetical_allow_block_delay": "ALLOW",
                "argus_status": "AVAILABLE",
                "confidence": 90.0,
                "reason_codes": ["PERSISTENCE_CONFIRMED"],
                "contract": {"trading_symbol": "NIFTY26JUL24000PE"}
            }
        }),
        json.dumps({
            "event_type": "ARGUS_SHADOW_OUTCOME",
            "recorded_at": "2026-07-25T11:30:00+05:30",
            "payload": {
                "signal_id": "sig-2",
                "trade_id": "trade-2",
                "native_outcome": "WIN",
                "counterfactual_shadow_outcome": "EXECUTED_AS_ALLOWED",
                "avoided_loss": 0.0,
                "missed_winner": 0.0,
                "net_pnl": 800.0
            }
        }),
        json.dumps({
            "event_type": "ARGUS_SHADOW_EVALUATION",
            "recorded_at": "2026-07-25T10:00:00+05:30",
            "payload": {
                "evaluation_id": "eval-1",
                "signal_id": "sig-1",
                "hypothetical_allow_block_delay": "BLOCK",
            }
        })
    ]
    (dep_dir / "journal.jsonl").write_text("\n".join(journal_lines), encoding="utf-8")

    service = StrategyLabService(str(lab_root))
    res = service.comparison("TC_NIFTY_PE_1M")
    comp = res["comparison"]

    assert comp["shadow_evaluations"] == 2
    assert comp["sample_size"] == 2
    assert comp["evidence_status"] == "INSUFFICIENT_SAMPLE"
    assert comp["argus_hypothetical_blocks"] == 1
    assert comp["argus_hypothetical_allows"] == 1
    assert comp["useful_blocks"] == 1
    assert comp["avoided_losses"] == 500.0
    assert len(comp["reason_code_breakdown"]) == 2
    assert len(comp["recent_signals"]) == 2


def test_frontend_contract_includes_comparison_selector():
    page = (Path(__file__).parents[1] / "citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    selectors = (Path(__file__).parents[1] / "citadel-dashboard/src/dashboard/selectors/index.ts").read_text(encoding="utf-8")
    
    assert "feedSelectors.comparison" in page
    assert "StrategyComparisonPanel" in page
    assert "comparison: selectFeed<unknown>('comparison')" in selectors


def test_comparison_reports_runtime_truth_and_does_not_score_missing_outcome(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    service.deploy(
        build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW"),
        start=False,
    )
    dep_dir = tmp_path / "lab" / "runtimes" / "BP_NIFTY_CE_1M"
    (dep_dir / "journal.jsonl").write_text(json.dumps({
        "event_type": "ARGUS_SHADOW_EVALUATION",
        "recorded_at": "2026-07-25T11:00:00+05:30",
        "payload": {
            "evaluation_id": "eval-pending",
            "signal_id": "sig-pending",
            "hypothetical_allow_block_delay": "BLOCK",
            "reason_codes": ["PERSISTENCE_LOW"],
        },
    }) + "\n", encoding="utf-8")

    comp = service.comparison("BP_NIFTY_CE_1M")["comparison"]

    assert comp["runtime_health"] == "DEGRADED"
    assert comp["runtime_readiness"] == "BLOCKED"
    assert comp["runtime_reason"] == "HISTORY_LOADING"
    assert comp["useful_blocks"] == 0
    assert comp["false_blocks"] == 0
    assert comp["avoided_losses"] == 0.0
    assert comp["missed_winners"] == 0.0
    assert comp["recent_signals"][0]["journal_status"] == "PENDING"
    assert comp["recent_signals"][0]["native_result"] == "OUTCOME PENDING"


def test_comparison_panel_is_immediately_after_active_deployments():
    page = (Path(__file__).parents[1] / "citadel-dashboard/src/app/page.tsx").read_text(encoding="utf-8")
    deployments = page.index('aria-label="Active Deployments"')
    comparison = page.index("<StrategyComparisonPanel", deployments)
    positions = page.index('aria-label="Active Positions"', deployments)

    assert deployments < comparison < positions
