"""Focused unit test for Today's Closed Trades projection in StrategyLabService."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.strategy_lab.service import StrategyLabService


pytestmark = pytest.mark.unit

IST = ZoneInfo("Asia/Kolkata")


def test_todays_closed_trades_projection():
    service = StrategyLabService("/Users/ayushmudgal/Developer/CitadelOS/logs/strategy_lab")
    proj = service.execution_projection()
    
    assert "todays_closed_trades" in proj
    data = proj["todays_closed_trades"]
    assert "summary" in data
    assert "trades" in data
    
    summary = data["summary"]
    assert summary["pnl_scope"] == "GROSS_REALIZED_PAPER_PNL_NO_BROKERAGE"
    assert isinstance(summary["completed_trades"], int)
    assert isinstance(summary["win_rate"], float)
    assert isinstance(summary["gross_realized_pnl"], float)
    
    trades = data["trades"]
    for trade in trades:
        assert "trade_id" in trade
        assert "deployment_id" in trade
        assert "realized_pnl" in trade
        assert trade["pnl_classification"] == "GROSS_REALIZED_PAPER_PNL"
        assert trade["status"] in {"WINNING", "LOSING", "BREAKEVEN"}
        assert "order_chain" in trade
