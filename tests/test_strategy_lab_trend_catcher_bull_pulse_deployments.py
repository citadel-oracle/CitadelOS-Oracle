import pytest
import json
import hashlib
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from copy import deepcopy

from app.main import strategy_lab_service
from src.strategy_lab import StrategyLabService
from src.strategy_lab.models import DeploymentRequest, StrategyMetadata, StrategyInputType
from src.strategy_lab.runtime import StrategyRuntime
from src.strategy_lab.storage import StrategyWorkspace
from src.strategy_lab.paper_engine import InstitutionalPaperTradingEngine
from src.strategy_lab.strategies.trend_catcher import (
    TrendCatcherStrategyEngine, TrendCatcherConfig, TrendCatcherState, build_deployment_request as build_tc
)
from src.strategy_lab.strategies.bull_pulse import (
    BullPulseStrategyEngine, BullPulseConfig, BullPulseState, build_deployment_request as build_bp
)
from src.paper_trading.contracts import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")

def mock_bp_context(time_str: str, ltp: float, spot: float, index: int = 1) -> dict:
    today_str = date.today().isoformat()
    if time_str.startswith("2026-07-24"):
        time_str = time_str.replace("2026-07-24", today_str)
    dt = datetime.fromisoformat(time_str)
    exp = (dt.date() + timedelta(days=4)).isoformat()
    return {
        "bar": {
            "timestamp": time_str,
            "close": ltp,
            "volume": 1000,
            "index": index
        },
        "argus": {
            "freshness": "fresh",
            "status": "available",
            "data": {
                "underlying": {
                    "symbol": "NIFTY",
                    "expiry": exp, # DTE = 4 for Bull Pulse
                    "atm_strike": spot,
                    "market_state": "OPEN",
                    "ltp": spot,
                    "fetched_at": time_str
                },
                "atm_window": [
                    {
                        "strike": spot - 50.0,
                        "ce": {"security_id": "mock_ce_low", "trading_symbol": f"NIFTY-{int(spot-50)}-CE", "ltp": ltp},
                        "pe": {"security_id": "mock_pe_low", "trading_symbol": f"NIFTY-{int(spot-50)}-PE", "ltp": 100.0}
                    },
                    {
                        "strike": spot,
                        "ce": {"security_id": "mock_ce_atm", "trading_symbol": f"NIFTY-{int(spot)}-CE", "ltp": ltp},
                        "pe": {"security_id": "mock_pe_atm", "trading_symbol": f"NIFTY-{int(spot)}-PE", "ltp": 100.0}
                    },
                    {
                        "strike": spot + 50.0,
                        "ce": {"security_id": "mock_ce_high", "trading_symbol": f"NIFTY-{int(spot+50)}-CE", "ltp": ltp},
                        "pe": {"security_id": "mock_pe_high", "trading_symbol": f"NIFTY-{int(spot+50)}-PE", "ltp": 100.0}
                    },
                    {
                        "strike": spot + 100.0,
                        "ce": {"security_id": "63925", "trading_symbol": f"NIFTY-{int(spot+100)}-CE", "ltp": ltp},
                        "pe": {"security_id": "mock_pe_high2", "trading_symbol": f"NIFTY-{int(spot+100)}-PE", "ltp": 100.0}
                    }
                ],
                "tactical_edge": {
                    "pressure": {"direction": "PUT"},
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
                    },
                    "contract_selection": {
                        "ce": {"security_id": "63925"}
                    },
                    "source_timestamp": time_str,
                    "status": "LIVE"
                }
            }
        },
        "lot_size": 50,
        "exchange_segment": "NSE_FNO"
    }

def mock_tc_context(time_str: str, ltp: float, spot: float, index: int = 1) -> dict:
    today_str = date.today().isoformat()
    if time_str.startswith("2026-07-24"):
        time_str = time_str.replace("2026-07-24", today_str)
    dt = datetime.fromisoformat(time_str)
    exp = (dt.date() + timedelta(days=1)).isoformat()
    return {
        "bar": {
            "timestamp": time_str,
            "close": ltp,
            "volume": 1000,
            "index": index
        },
        "argus": {
            "freshness": "fresh",
            "status": "available",
            "data": {
                "underlying": {
                    "symbol": "NIFTY",
                    "expiry": exp, # DTE = 1 for Trend Catcher
                    "atm_strike": spot,
                    "market_state": "OPEN",
                    "ltp": spot,
                    "fetched_at": time_str
                },
                "atm_window": [
                    {
                        "strike": spot - 100.0,
                        "ce": {"security_id": "mock_ce_low2", "trading_symbol": f"NIFTY-{int(spot-100)}-CE", "ltp": 100.0},
                        "pe": {"security_id": "63925", "trading_symbol": f"NIFTY-{int(spot-100)}-PE", "ltp": ltp}
                    },
                    {
                        "strike": spot - 50.0,
                        "ce": {"security_id": "mock_ce_low", "trading_symbol": f"NIFTY-{int(spot-50)}-CE", "ltp": 100.0},
                        "pe": {"security_id": "mock_pe_low", "trading_symbol": f"NIFTY-{int(spot-50)}-PE", "ltp": ltp}
                    },
                    {
                        "strike": spot,
                        "ce": {"security_id": "mock_ce_atm", "trading_symbol": f"NIFTY-{int(spot)}-CE", "ltp": 100.0},
                        "pe": {"security_id": "mock_pe_atm", "trading_symbol": f"NIFTY-{int(spot)}-PE", "ltp": ltp}
                    },
                    {
                        "strike": spot + 50.0,
                        "ce": {"security_id": "mock_ce_high", "trading_symbol": f"NIFTY-{int(spot+50)}-CE", "ltp": 100.0},
                        "pe": {"security_id": "mock_pe_high", "trading_symbol": f"NIFTY-{int(spot+50)}-PE", "ltp": ltp}
                    }
                ],
                "tactical_edge": {
                    "pressure": {"direction": "PUT"},
                    "breadth": {"status": "AVAILABLE"},
                    "persistence": {"distinct_confirmation_count": 3},
                    "iv_intelligence": {"status": "AVAILABLE"},
                    "gamma": {},
                    "continuation_reversal": {},
                    "decision": {
                        "readiness_score": 85.0,
                        "current_action": "Observe put conditions",
                        "gate": "ADVISORY_READY",
                        "action_enabled": True
                    },
                    "contract_selection": {
                        "pe": {"security_id": "63925"}
                    },
                    "source_timestamp": time_str,
                    "status": "LIVE"
                }
            }
        },
        "lot_size": 50,
        "exchange_segment": "NSE_FNO"
    }

@pytest.mark.integration
def test_production_registrations_exist_in_application():
    registry_strategies = strategy_lab_service.strategies()["strategies"]
    expected_ids = {
        "TC_NIFTY_PE_1M",
        "TC_NIFTY_PE_3M",
        "BP_NIFTY_CE_1M",
        "BP_NIFTY_CE_3M",
    }
    registered_ids = {item["strategy_id"] for item in registry_strategies}
    assert expected_ids.issubset(registered_ids)
    
    for item in registry_strategies:
        if item["strategy_id"] in expected_ids:
            assert item["metadata"]["status"] == "PAPER_ACTIVE"
            assert item["paper_only"] is True
            assert item["live_trading_enabled"] is False
            mode = item["metadata"]["parameters"].get("mode")
            if "1M" in item["strategy_id"]:
                assert mode == "SHADOW"
            else:
                assert mode == "OFF"

@pytest.mark.integration
def test_worker_uniqueness_and_non_duplicate_threads(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    request = build_tc(lambda: {}, deployment_id="TC_NIFTY_PE_1M", mode="SHADOW")
    service.deploy(request, start=False)
    with pytest.raises(ValueError, match="strategy runtime already loaded"):
        service.deploy(request, start=False)


@pytest.mark.integration
def test_unavailable_candle_pass_advances_scheduler_heartbeat(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    request = build_tc(
        lambda: {
            "data_readiness": {
                "DATA_READY": False,
                "not_ready_reason": "CANDLE_STALE",
            }
        },
        deployment_id="TC_NIFTY_PE_1M",
        mode="SHADOW",
    )
    runtime = service.deploy(request, start=False)

    result = runtime.tick_once()
    status = runtime.status()

    assert result["status"] == "SKIPPED"
    assert result["reason"] == "CANDLE_STALE"
    assert status["scheduler"]["tick_count"] == 1
    assert status["scheduler"]["skipped_count"] == 1
    assert status["scheduler"]["last_tick_at"] is not None

@pytest.mark.integration
def test_restart_recovery_preserves_state(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    req = build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW")
    runtime = service.deploy(req, start=False)
    
    # 1. Capture 10:30 reference premium
    runtime.tick_once(mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1))
    
    # 2. Trigger entry
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 111.0, 23600.0, index=2)
    runtime.tick_once(ctx_1031)
    
    # Verify state matches
    assert runtime.strategy.state.entry_count == 1
    assert runtime.strategy.state.entry_trigger_status is True
    
    # Simulate restart
    service_new = StrategyLabService(str(tmp_path / "lab"))
    req_new = build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW")
    runtime_new = service_new.deploy(req_new, start=False)
    
    # Verify state is recovered
    assert runtime_new.strategy.state.entry_count == 1
    assert runtime_new.strategy.state.entry_trigger_status is True
    assert runtime_new.strategy.state.reference_premium == 100.0

@pytest.mark.integration
def test_prevent_second_daily_entry_after_restart(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    req = build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW")
    runtime = service.deploy(req, start=False)
    
    # Trigger reference & entry
    runtime.tick_once(mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1))
    runtime.tick_once(mock_bp_context("2026-07-24T10:31:00+05:30", 111.0, 23600.0, index=2))
    
    # Simulate exit
    runtime.tick_once(mock_bp_context("2026-07-24T10:32:00+05:30", 80.0, 23600.0, index=3))
    
    assert runtime.strategy.state.terminal_session_state is True
    
    # Simulate restart
    service_new = StrategyLabService(str(tmp_path / "lab"))
    req_new = build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW")
    runtime_new = service_new.deploy(req_new, start=False)
    
    # Tick again after entry start window
    ctx_next = mock_bp_context("2026-07-24T10:35:00+05:30", 120.0, 23600.0, index=4)
    res = runtime_new.tick_once(ctx_next)
    
    # Verify no second entry is allowed
    assert runtime_new.strategy.state.entry_count == 1
    assert res["decision"]["status"] == "SESSION_COMPLETE"
    assert res["decision"]["reason"] == "SESSION_TERMINATED: LEG_STOP_LOSS_HIT"

@pytest.mark.integration
def test_combined_portfolio_capital_reservation(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    req1 = build_tc(lambda: {}, deployment_id="TC_NIFTY_PE_1M", mode="SHADOW")
    req2 = build_bp(lambda: {}, deployment_id="BP_NIFTY_CE_1M", mode="SHADOW")
    
    # Configure the first strategy to take up 140,000 INR of capital (out of 150k combined limit)
    # 140 * 15 * 65 = 136,500 INR
    req1.metadata.parameters["paper_account"]["initial_capital"] = 200_000.0
    req1.metadata.parameters["paper_account"]["max_daily_loss"] = 50_000.0
    req1.metadata.parameters["paper_account"]["fixed_lots"] = 15
    req1.metadata.parameters["paper_account"]["lot_size"] = 65
    
    rt1 = service.deploy(req1, start=False)
    
    # 1. 09:35 AM: capture reference premium
    rt1.tick_once(mock_tc_context("2026-07-24T09:35:00+05:30", 100.0, 23600.0, index=1))
    
    # 2. 09:36 AM: trigger entry
    ctx_0936 = mock_tc_context("2026-07-24T09:36:00+05:30", 140.0, 23600.0, index=2)
    res1 = rt1.tick_once(ctx_0936)
    assert res1["decision"]["signal"] == "BUY"
    assert res1["decision"]["paper_execution"]["status"] == "FILLED"
    
    # Configure the second strategy to trigger entry which requires 35,750 INR margin
    # Combined: 136,500 + 35,750 = 172,250 > 150,000 (combined_limit)
    # This must be rejected with CAPITAL_UNAVAILABLE!
    req2.metadata.parameters["paper_account"]["initial_capital"] = 100_000.0
    req2.metadata.parameters["paper_account"]["max_daily_loss"] = 50_000.0
    req2.metadata.parameters["paper_account"]["fixed_lots"] = 5
    req2.metadata.parameters["paper_account"]["lot_size"] = 65
    
    rt2 = service.deploy(req2, start=False)
    rt2.tick_once(mock_bp_context("2026-07-24T10:30:00+05:30", 100.0, 23600.0, index=1))
    
    ctx_1031 = mock_bp_context("2026-07-24T10:31:00+05:30", 110.0, 23600.0, index=2)
    res2 = rt2.tick_once(ctx_1031)
    
    assert res2["decision"]["signal"] == "BUY"
    assert res2["decision"]["paper_execution"]["status"] == "REJECTED"
    assert res2["decision"]["paper_execution"]["reason"] == "CAPITAL_UNAVAILABLE"
    
    # Verify CAPITAL_UNAVAILABLE event was written
    journal_rows = rt2.workspace.journal.read()
    cap_event = next((r for r in journal_rows if r.get("event_type") == "CAPITAL_UNAVAILABLE"), None)
    assert cap_event is not None
    assert cap_event["payload"]["reason"] == "CAPITAL_UNAVAILABLE"

@pytest.mark.unit
def test_off_vs_shadow_mode_parity(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    req_off = build_tc(lambda: {}, deployment_id="TC_NIFTY_PE_3M", mode="OFF")
    req_shadow = build_tc(lambda: {}, deployment_id="TC_NIFTY_PE_1M", mode="SHADOW")
    
    rt_off = service.deploy(req_off, start=False)
    rt_shadow = service.deploy(req_shadow, start=False)
    
    # Tick both and verify native decisions are 100% identical
    ctx1 = mock_tc_context("2026-07-24T09:35:00+05:30", 100.0, 23600.0, index=1)
    res_off = rt_off.tick_once(ctx1)
    res_shadow = rt_shadow.tick_once(ctx1)
    
    assert res_off["decision"]["signal"] == res_shadow["decision"]["signal"]
    assert res_off["decision"]["status"] == res_shadow["decision"]["status"]
    
    ctx2 = mock_tc_context("2026-07-24T09:36:00+05:30", 140.0, 23600.0, index=2)
    res_off2 = rt_off.tick_once(ctx2)
    res_shadow2 = rt_shadow.tick_once(ctx2)
    
    assert res_off2["decision"]["signal"] == res_shadow2["decision"]["signal"]
    assert res_off2["decision"]["status"] == res_shadow2["decision"]["status"]

@pytest.mark.unit
def test_fail_closed_on_missing_or_stale_data(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    req = build_tc(lambda: {}, deployment_id="TC_NIFTY_PE_1M", mode="SHADOW")
    runtime = service.deploy(req, start=False)
    
    # 1. Missing underlying info
    ctx = mock_tc_context("2026-07-24T09:35:00+05:30", 100.0, 23600.0, index=1)
    ctx["argus"]["data"]["underlying"] = None
    res = runtime.tick_once(ctx)
    assert res["decision"]["status"] == "UNAVAILABLE"
    assert res["decision"]["reason"] == "ARGUS_UNDERLYING_REQUIRED"
    
    # 2. Missing expiry
    ctx_ex = mock_tc_context("2026-07-24T09:36:00+05:30", 100.0, 23600.0, index=2)
    ctx_ex["argus"]["data"]["underlying"]["expiry"] = None
    res_ex = runtime.tick_once(ctx_ex)
    assert res_ex["decision"]["status"] == "UNAVAILABLE"
    assert res_ex["decision"]["reason"] == "EXPIRY_CALENDAR_UNAVAILABLE"
