"""Deployment request builder for Bull Pulse strategy."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ...models import DeploymentRequest, StrategyInputType, StrategyMetadata
from .strategy import BullPulseStrategyEngine, BullPulseConfig, BullPulseState

STRATEGY_ID = "BP_NIFTY_CE_1M"
SOURCE_SHA256 = "bull_pulse_native_v1"
DEPLOYMENT_STATUS = "PAPER_ACTIVE"
CLASSIFICATION = "UNDERLYING_STRATEGY"

def build_deployment_request(
    context_provider: Callable[[], Mapping[str, Any]] | None = None,
    *,
    deployment_id: str = STRATEGY_ID,
    deployment_name: str = "Bull Pulse",
    chart_symbol: str = "NIFTY",
    chart_timeframe: str = "1m",
    option_type: str = "CE",
    mode: str = "SHADOW",
) -> DeploymentRequest:
    """Build the paper-only Strategy Lab deployment for Bull Pulse."""

    parameters = {
        "classification": CLASSIFICATION,
        "runtime_mode": "PAPER",
        "mode": mode,
        "option_selection": {
            "underlying": "NIFTY",
            "option_type": option_type,
            "strike_offset": 2,
            "expiry": None,
        },
        "paper_account": {
            "portfolio_id": "portfolio_strategy_lab_default",
            "currency": "INR",
            "initial_capital": 100_000.0,
            "sizing_mode": "FIXED_LOTS",
            "fixed_lots": 1,
            "lot_size": 50,
            "max_daily_loss": 3_000.0,
            "max_daily_loss_percent": 3.0,
            "max_risk_per_trade_percent": 1.0,
            "max_concurrent_positions": 1,
            "max_trades_per_day": 20,
            "max_exposure_percent": 100.0,
            "margin_rate": 1.0,
        },
    }
    metadata = StrategyMetadata(
        strategy_id=deployment_id,
        name=deployment_name,
        version="1.0.0",
        author="Tester",
        input_type=StrategyInputType.PYTHON,
        supported_markets=[chart_symbol],
        supported_timeframes=[chart_timeframe],
        rr=1.0,
        risk_model="IsolatedRisk",
        status=DEPLOYMENT_STATUS,
        deployment_date="2026-07-25T00:00:00+00:00",
        parameters=parameters,
    )
    engine = BullPulseStrategyEngine(config=BullPulseConfig(), state=BullPulseState())
    return DeploymentRequest(
        metadata=metadata,
        adapter=engine,
        context_provider=context_provider or (lambda: {}),
        scheduler_interval_seconds=5.0,
        activation_enabled=True,
        activation_reason=None,
    )
