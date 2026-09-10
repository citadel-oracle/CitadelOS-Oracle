import pytest
import json
import hashlib
from datetime import datetime, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo
from copy import deepcopy
from typing import Any, Mapping

from src.strategy_lab.strategies.trend_catcher import TrendCatcherStrategyEngine, TrendCatcherConfig, TrendCatcherState
from src.strategy_lab.strategies.bull_pulse import BullPulseStrategyEngine, BullPulseConfig, BullPulseState
from src.strategy_lab.models import DeploymentRequest, StrategyMetadata, StrategyInputType
from src.strategy_lab.runtime import StrategyRuntime
from src.strategy_lab.storage import StrategyWorkspace
from src.strategy_lab.paper_engine import InstitutionalPaperTradingEngine
from src.paper_trading.contracts import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")

class InstrumentMaster:
    def resolve(self, **values):
        return {
            "security_id": str(values["security_id"]),
            "lot_size": 65,
            "source": "DHAN_INSTRUMENT_MASTER",
            "exchange_segment": "NSE_FNO",
        }

def build_deployment_request(
    strategy_id: str,
    parameters: dict,
    workspace: "StrategyWorkspace | None" = None,
) -> DeploymentRequest:
    # PaperRiskPolicy reads from parameters["paper_account"] (nested dict).
    _paper_policy_defaults = {
        "paper_account": {
            "initial_capital": 1_000_000.0,
            "sizing_mode": "FIXED_LOTS",
            "fixed_lots": 1,
            "lot_size": 65,
            "max_daily_loss": 50_000.0,
            "max_concurrent_positions": 1,
            "max_trades_per_day": 10,
        }
    }
    full_params = {**_paper_policy_defaults, **parameters}
    metadata = StrategyMetadata(
        strategy_id=strategy_id,
        name="Test Strategy",
        version="1.0.0",
        author="Tester",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NSE_FNO"],
        supported_timeframes=["1m"],
        rr=1.0,
        risk_model="IsolatedRisk",
        parameters=full_params
    )
    engine = (
        BullPulseStrategyEngine(config=BullPulseConfig(), state=BullPulseState())
        if "bp" in strategy_id
        else TrendCatcherStrategyEngine(config=TrendCatcherConfig(), state=TrendCatcherState())
    )
    execution = None
    if workspace is not None:
        execution = InstitutionalPaperTradingEngine.from_metadata(
            metadata=metadata.to_dict(),
            workspace=workspace,
        )
    return DeploymentRequest(
        metadata=metadata,
        adapter=engine,
        context_provider=lambda: {},
        execution=execution,
        option_resolver=OptionContractResolver(InstrumentMaster()),
        activation_enabled=True
    )

def mock_bp_context(timestamp: str, premium: float, atm_strike: float, dte: int = 4, index: int = 1) -> dict:
    return {
        "symbol": "NIFTY",
        "underlying": "NIFTY",
        "bar": {
            "timestamp": timestamp,
            "index": index,
            "open": premium,
            "high": premium,
            "low": premium,
            "close": premium,
            "volume": 1000
        },
        "lot_size": 65,
        "argus": {
            "status": "available",
            "freshness": "fresh",
            "data": {
                "underlying": {
                    "symbol": "NIFTY",
                    "expiry": "2026-07-28",
                    "atm_strike": atm_strike,
                    "market_state": "OPEN",
                    "ltp": atm_strike,
                    "fetched_at": timestamp
                },
                "atm_window": [
                    {
                        "strike": atm_strike - 50.0,
                        "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": premium},
                        "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
                    },
                    {
                        "strike": atm_strike,
                        "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": premium},
                        "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
                    },
                    {
                        "strike": atm_strike + 50.0,
                        "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": premium},
                        "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
                    },
                    {
                        "strike": atm_strike + 100.0,
                        "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": premium},
                        "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
                    }
                ],
                "tactical_edge": {
                    "module": "ARGUS TACTICAL EDGE",
                    "status": "LIVE",
                    "freshness": "FRESH",
                    "source_timestamp": timestamp,
                    "contract_selection": {"ce": {"security_id": "63925"}},
                    "pressure": {"direction": "CALL"},
                    "breadth": {"status": "AVAILABLE"},
                    "persistence": {"distinct_confirmation_count": 3},
                    "iv_intelligence": {"status": "AVAILABLE"},
                    "gamma": {},
                    "continuation_reversal": {},
                    "decision": {
                        "readiness_score": 85.0,
                        "current_action": "Observe call conditions",
                        "gate": "ADVISORY_READY",
                        "action_enabled": True
                    }
                }
            }
        }
    }

@pytest.mark.unit
def test_locked_contract_remains_locked_when_atm_moves():
    # Bull Pulse locks strike 2 intervals above ATM (ATM + 100) at 10:30
    engine = BullPulseStrategyEngine()
    
    # 1. 10:30 AM IST tick: ATM is 23600 -> resolves 23700 CE
    ctx_1030 = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    res1 = engine.evaluate(ctx_1030)
    
    assert res1["state"]["selected_contract"]["strike"] == 23700.0
    assert res1["state"]["selected_contract"]["security_id"] == "63925"
    
    # 2. 10:31 AM IST tick: ATM moves to 23700. Normally OTM2 would shift to 23800.
    # But because of Locked Contract Rule, it should stay locked to 23700 CE!
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 105.0, 23700.0, index=2)
    # Ensure 23700 CE exists in window so it is found
    ctx_1031["argus"]["data"]["atm_window"].append({
        "strike": 23700.0, # Target strike
        "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 105.0},
        "pe": {"security_id": "mock_pe", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
    })
    
    res2 = engine.evaluate(ctx_1031)
    assert res2["state"]["selected_contract"]["strike"] == 23700.0
    assert res2["state"]["selected_contract"]["security_id"] == "63925"

@pytest.mark.unit
def test_locked_contract_unavailable_emits_contract_data_unavailable():
    engine = BullPulseStrategyEngine()
    ctx_1030 = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    engine.evaluate(ctx_1030)
    
    # Next tick the contract is missing from the window
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 105.0, 23700.0, index=2)
    # Omit 63925 from window
    ctx_1031["argus"]["data"]["atm_window"] = []
    
    res = engine.evaluate(ctx_1031)
    assert res["status"] == "UNAVAILABLE"
    assert res["reason"] == "CONTRACT_DATA_UNAVAILABLE"


@pytest.mark.integration
def test_shadow_outcome_failure_is_logged_not_silenced(tmp_path, monkeypatch):
    workspace = StrategyWorkspace(tmp_path, "bp_shadow_error")
    request = build_deployment_request(
        "bp_shadow_error",
        {"mode": "SHADOW", "strike_offset": 2},
        workspace=workspace,
    )
    runtime = StrategyRuntime(request=request, workspace=workspace)
    original_read = workspace.read

    def broken_read(name):
        if name == "strategy_state":
            raise ValueError("corrupt shadow state")
        return original_read(name)

    monkeypatch.setattr(workspace, "read", broken_read)
    runtime._handle_shadow_outcome("2026-07-24T10:31:00+05:30")

    records = workspace.logs.read()
    error = next(row for row in records if row["event_type"] == "ARGUS_SHADOW_OUTCOME_ERROR")
    assert error["payload"]["error_type"] == "ValueError"
    assert error["payload"]["execution_influence"] == "ZERO"

@pytest.mark.integration
def test_off_vs_shadow_directives_identical(tmp_path):
    # OFF Mode runtime
    workspace_off = StrategyWorkspace(tmp_path / "off", "bp_off")
    req_off = build_deployment_request("bp_off", {"mode": "OFF", "strike_offset": 2}, workspace=workspace_off)
    runtime_off = StrategyRuntime(request=req_off, workspace=workspace_off)
    
    # SHADOW Mode runtime
    workspace_shadow = StrategyWorkspace(tmp_path / "shadow", "bp_shadow")
    req_shadow = build_deployment_request("bp_shadow", {"mode": "SHADOW", "strike_offset": 2}, workspace=workspace_shadow)
    runtime_shadow = StrategyRuntime(request=req_shadow, workspace=workspace_shadow)
    
    ctx = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    
    # Tick both and verify directives are identical
    res_off = runtime_off.tick_once(ctx)
    res_shadow = runtime_shadow.tick_once(ctx)
    
    assert res_off["decision"]["signal"] == res_shadow["decision"]["signal"]
    assert res_off["decision"]["status"] == res_shadow["decision"]["status"]

@pytest.mark.integration
def test_shadow_creates_evaluation_record_and_outcome(tmp_path):
    # Initialize workspace & runtime in SHADOW mode
    workspace = StrategyWorkspace(tmp_path, "bp_shadow")
    req = build_deployment_request("bp_shadow", {"mode": "SHADOW", "strike_offset": 2}, workspace=workspace)
    runtime = StrategyRuntime(request=req, workspace=workspace)
    
    # 1. 10:30 AM: capture reference premium of 100.0
    ctx_1030 = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    runtime.tick_once(ctx_1030)
    
    # 2. 10:31 AM: trigger entry at 111.0 (>= 100 * 1.10)
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 111.0, 23600.0, index=2)
    ctx_1031["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res = runtime.tick_once(ctx_1031)
    assert res["decision"]["signal"] == "BUY"
    
    # Verify that ARGUS_SHADOW_EVALUATION event was logged
    journal_rows = workspace.journal.read()
    eval_event = next((row for row in journal_rows if row.get("event_type") == "ARGUS_SHADOW_EVALUATION"), None)
    assert eval_event is not None
    assert eval_event["payload"]["hypothetical_allow_block_delay"] == "ALLOW"
    assert eval_event["payload"]["confidence"] == 85.0
    signal_id = eval_event["payload"]["signal_id"]
    
    # 2.5. 10:32 AM: Intermediate tick at 111.0 to let paper engine fill order and open position
    ctx_1032 = mock_bp_context("2026-07-24T10:32:00+05:30", 111.0, 23600.0, index=3)
    ctx_1032["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res_wait = runtime.tick_once(ctx_1032)
    assert res_wait["decision"]["signal"] == "WAIT"
    
    # 3. 10:33 AM: trigger stop loss exit (falls to 80.0 <= 111.0 * 0.80)
    ctx_1033 = mock_bp_context("2026-07-24T10:33:00+05:30", 80.0, 23600.0, index=4)
    ctx_1033["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res_exit = runtime.tick_once(ctx_1033)
    # Paper engine auto-closes position via _mark_positions when stop fires,
    # then receives SELL and emits DUPLICATE_EXIT_SUPPRESSED → signal becomes WAIT.
    # The strategy-level status (EXIT_CANDIDATE) confirms the exit was triggered.
    assert res_exit["decision"]["status"] == "EXIT_CANDIDATE"
    assert res_exit["decision"]["state"]["exit_reason"] in {"LEG_STOP_LOSS_HIT", "STOP_LOSS_HIT"}
    
    # Verify that ARGUS_SHADOW_OUTCOME event was logged
    journal_rows_2 = workspace.journal.read()
    outcome_event = next((row for row in journal_rows_2 if row.get("event_type") == "ARGUS_SHADOW_OUTCOME"), None)
    assert outcome_event is not None
    assert outcome_event["payload"]["signal_id"] == signal_id
    assert outcome_event["payload"]["native_outcome"] == "LOSS"
    assert outcome_event["payload"]["counterfactual_shadow_outcome"] == "EXECUTED_AS_ALLOWED"

@pytest.mark.integration
def test_shadow_argus_unavailable_does_not_block_trade(tmp_path):
    workspace = StrategyWorkspace(tmp_path, "bp_shadow")
    req = build_deployment_request("bp_shadow", {"mode": "SHADOW", "strike_offset": 2}, workspace=workspace)
    runtime = StrategyRuntime(request=req, workspace=workspace)
    
    # Reference tick
    ctx_1030 = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    runtime.tick_once(ctx_1030)
    
    # Entry tick but ARGUS is missing!
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 111.0, 23600.0, index=2)
    
    ctx_1031["argus"] = {
        "status": "unavailable",
        "freshness": "stale",
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "expiry": "2026-07-28",
                "atm_strike": 23600.0,
                "market_state": "OPEN",
                "ltp": 23600.0,
                "fetched_at": "2026-07-24T10:31:00+05:30"
            },
            "atm_window": [
                {
                    "strike": 23550.0,
                    "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 111.0},
                    "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
                },
                {
                    "strike": 23600.0,
                    "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 111.0},
                    "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
                },
                {
                    "strike": 23650.0,
                    "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 111.0},
                    "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
                },
                {
                    "strike": 23700.0,
                    "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 111.0},
                    "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
                }
            ]
        }
    }
    
    res = runtime.tick_once(ctx_1031)
    
    # Native execution BUY must STILL trigger successfully!
    assert res["decision"]["signal"] == "BUY"
    
    # Verify that ARGUS_SHADOW_EVALUATION was logged as ARGUS_UNAVAILABLE or ARGUS_STALE
    journal_rows = workspace.journal.read()
    eval_event = next((row for row in journal_rows if row.get("event_type") == "ARGUS_SHADOW_EVALUATION"), None)
    assert eval_event is not None
    assert eval_event["payload"]["suggested_action"] in {"ARGUS_UNAVAILABLE", "ARGUS_STALE"}
    assert eval_event["payload"]["hypothetical_allow_block_delay"] == "BLOCK"

@pytest.mark.integration
def test_shadow_mode_counterfactual_capital_unavailable(tmp_path):
    # Initialize workspace with tiny capital (10.0) to trigger capital rejection
    workspace = StrategyWorkspace(tmp_path, "bp_shadow")
    req = build_deployment_request("bp_shadow", {
        "mode": "SHADOW",
        "strike_offset": 2,
        "paper_account": {
            "initial_capital": 10.0,
            "sizing_mode": "FIXED_LOTS",
            "fixed_lots": 1,
            "lot_size": 65,
            "max_daily_loss": 5.0,
            "max_concurrent_positions": 1,
            "max_trades_per_day": 10,
        }
    }, workspace=workspace)
    runtime = StrategyRuntime(request=req, workspace=workspace)

    
    # 1. 10:30 AM: capture reference premium of 100.0
    ctx_1030 = mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1)
    runtime.tick_once(ctx_1030)
    
    # 2. 10:31 AM: trigger entry at 111.0 (>= 100 * 1.10)
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 111.0, 23600.0, index=2)
    ctx_1031["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res = runtime.tick_once(ctx_1031)
    
    # The native decision is still BUY
    assert res["decision"]["signal"] == "BUY"
    # But the paper execution must be REJECTED with INSUFFICIENT_AVAILABLE_MARGIN
    assert res["decision"]["paper_execution"]["status"] == "REJECTED"
    assert res["decision"]["paper_execution"]["reason"] == "INSUFFICIENT_AVAILABLE_MARGIN"
    
    # Verify that both ARGUS_SHADOW_EVALUATION and CAPITAL_UNAVAILABLE were logged
    journal_rows = workspace.journal.read()
    eval_event = next((row for row in journal_rows if row.get("event_type") == "ARGUS_SHADOW_EVALUATION"), None)
    cap_event = next((row for row in journal_rows if row.get("event_type") == "CAPITAL_UNAVAILABLE"), None)
    assert eval_event is not None
    assert cap_event is not None
    assert cap_event["payload"]["reason"] == "INSUFFICIENT_AVAILABLE_MARGIN"
    
    # 3. 10:32 AM: tick at 111.0 (WAIT)
    ctx_1032 = mock_bp_context("2026-07-24T10:32:00+05:30", 111.0, 23600.0, index=3)
    ctx_1032["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 111.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res_wait = runtime.tick_once(ctx_1032)
    assert res_wait["decision"]["signal"] == "WAIT"
    
    # 4. 10:33 AM: trigger native stop loss exit (falls to 80.0)
    ctx_1033 = mock_bp_context("2026-07-24T10:33:00+05:30", 80.0, 23600.0, index=4)
    ctx_1033["argus"]["data"]["atm_window"] = [
        {
            "strike": 23550.0,
            "ce": {"security_id": "mock_ce_low", "trading_symbol": "NIFTY-23550-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_low", "trading_symbol": "NIFTY-23550-PE", "ltp": 100.0}
        },
        {
            "strike": 23600.0,
            "ce": {"security_id": "mock_ce_atm", "trading_symbol": "NIFTY-23600-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_atm", "trading_symbol": "NIFTY-23600-PE", "ltp": 100.0}
        },
        {
            "strike": 23650.0,
            "ce": {"security_id": "mock_ce_high", "trading_symbol": "NIFTY-23650-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_high", "trading_symbol": "NIFTY-23650-PE", "ltp": 100.0}
        },
        {
            "strike": 23700.0,
            "ce": {"security_id": "63925", "trading_symbol": "NIFTY-23700-CE", "ltp": 80.0},
            "pe": {"security_id": "mock_pe_high2", "trading_symbol": "NIFTY-23700-PE", "ltp": 100.0}
        }
    ]
    res_exit = runtime.tick_once(ctx_1033)
    
    # Verify early return with DUPLICATE_EXIT_SUPPRESSED
    assert res_exit["decision"]["status"] == "EXIT_CANDIDATE"
    assert res_exit["decision"]["reason"] == "DUPLICATE_EXIT_SUPPRESSED"
    
    # Verify that ARGUS_SHADOW_OUTCOME event was successfully logged counterfactually
    journal_rows_2 = workspace.journal.read()
    outcome_event = next((row for row in journal_rows_2 if row.get("event_type") == "ARGUS_SHADOW_OUTCOME"), None)
    assert outcome_event is not None
    assert outcome_event["payload"]["signal_id"] == eval_event["payload"]["signal_id"]
    assert outcome_event["payload"]["trade_id"].startswith("cf-")
    assert outcome_event["payload"]["native_outcome"] == "LOSS"
    assert outcome_event["payload"]["counterfactual_shadow_outcome"] == "AVOIDED_LOSS"

