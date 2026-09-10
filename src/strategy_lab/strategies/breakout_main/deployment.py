"""Paper-only Strategy Lab deployment for BREAKOUT MAIN."""

from typing import Any, Callable, Mapping

from ...models import DeploymentRequest, StrategyInputType, StrategyMetadata
from .adapters import BreakoutMainSignalEngine

STRATEGY_ID = "breakout-main-pine-v5"
PHASE_STATUS = "MARKET_STRUCTURE_COMPLETE"
DEPLOYMENT_STATUS = "PAPER_ACTIVE"


def build_deployment_request(
    context_provider: Callable[[], Mapping[str, Any]] | None = None,
    *,
    deployment_id: str = STRATEGY_ID,
    deployment_name: str = "BREAKOUT MAIN",
    chart_symbol: str | None = None,
    chart_timeframe: str | None = None,
    option_type: str = "CE",
) -> DeploymentRequest:
    parameters = {
        "pine_version": 5, "direction": "LONG_ONLY", "phase": "PAPER_ACTIVATION",
        "market_structure_status": PHASE_STATUS, "implementation_status": "COMPLETE",
        "runtime_mode": "PAPER",
        "option_selection": {
            "underlying": "NIFTY", "option_type": option_type,
            "strike_offset": 0, "expiry": None,
        },
        "paper_account": {
            "portfolio_id": "portfolio_strategy_lab_default", "currency": "INR",
            "initial_capital": 100_000.0, "sizing_mode": "FIXED_LOTS",
            "fixed_lots": 1, "lot_size": None, "max_daily_loss": 3_000.0,
            "max_daily_loss_percent": 3.0, "max_risk_per_trade_percent": 1.0,
            "max_concurrent_positions": 1, "max_trades_per_day": 20,
            "max_exposure_percent": 100.0, "margin_rate": 1.0,
        },
    }
    if deployment_id != STRATEGY_ID:
        parameters["chart_input"] = {
            "symbol": chart_symbol, "timeframe": chart_timeframe, "option_type": option_type,
        }
    metadata = StrategyMetadata(
        strategy_id=deployment_id,
        name=deployment_name,
        version="PINE_V5_NATIVE_RUNTIME",
        author="NOT_DETERMINABLE_FROM_SOURCE",
        input_type=StrategyInputType.PINE_SCRIPT,
        supported_markets=[chart_symbol or "NIFTY"],
        supported_timeframes=[chart_timeframe or "5m"],
        rr=None,
        risk_model="PINE_NATIVE_SL_TARGET_MAPPED_PAPER_ONLY",
        status=DEPLOYMENT_STATUS,
        deployment_date="2026-07-14T00:00:00+00:00",
        parameters=parameters,
    )
    return DeploymentRequest(
        metadata=metadata,
        adapter=BreakoutMainSignalEngine(),
        context_provider=context_provider or (lambda: {}),
        scheduler_interval_seconds=5.0,
        activation_enabled=True,
        activation_reason=None,
    )
