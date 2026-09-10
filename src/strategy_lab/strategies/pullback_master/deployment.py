"""Deployment definition for the reviewed PULLBACK MASTER Pine strategy."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ...models import DeploymentRequest, StrategyInputType, StrategyMetadata

STRATEGY_ID = "pullback-master-pine-v5"
SOURCE_SHA256 = "e75c83b50c09618fb025ad50772d2e13b04100b4b23d6db7fbc25c0638fa63eb"
SOURCE_REFERENCE = "/Users/ayushmudgal/Documents/Codex/2026-05-30/files-mentioned-by-the-user-pasted-2/outputs/PULLBACK_MASTER.pine"
PARITY_STATUS = "PROVISIONAL_PENDING_PARITY_VALIDATION"
DEPLOYMENT_STATUS = "PAPER_ACTIVE"
CLASSIFICATION = "UNDERLYING_STRATEGY"


def build_deployment_request(
    context_provider: Callable[[], Mapping[str, Any]] | None = None,
    *,
    deployment_id: str = STRATEGY_ID,
    deployment_name: str = "PULLBACK MASTER",
    chart_symbol: str | None = None,
    chart_timeframe: str | None = None,
    option_type: str = "CE",
) -> DeploymentRequest:
    """Build the paper-only Strategy Lab deployment."""

    from .adapter import PullbackMasterNativeAdapter
    from .parity import load_parity_manifest, parity_config_hash
    from .strategy import PullbackMasterConfig

    parity_manifest = load_parity_manifest()

    parameters = {
        "pine_version": 5,
        "input_count": 157,
        "classification": CLASSIFICATION,
        "default_pullback_mode": "V4",
        "default_target_mode": "Bearish VOB",
        "default_fixed_rr": 4.0,
        "process_orders_on_close": True,
        "calc_on_every_tick": True,
        "pyramiding": 0,
        "source_sha256": SOURCE_SHA256,
        "parity_authority_pine_sha256": parity_manifest["authority"]["pine_sha256"],
        "parity_config_hash": parity_config_hash(parity_manifest),
        "parity_settings_strategy": parity_manifest["authority"]["settings_strategy"],
        "parity_status": PARITY_STATUS,
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
        version="PINE_V5_SOURCE_E75C83B5",
        author="UNSPECIFIED_IN_SOURCE",
        input_type=StrategyInputType.PINE_SCRIPT,
        supported_markets=[chart_symbol or "TRADINGVIEW_CHART_SYMBOL"],
        supported_timeframes=[chart_timeframe or "CHART_TIMEFRAME"],
        rr=4.0,
        risk_model="PINE_NATIVE_SL_TARGET_MAPPED_PAPER_ONLY",
        status=DEPLOYMENT_STATUS,
        deployment_date="2026-07-14T00:00:00+00:00",
        parameters=parameters,
        source_reference=SOURCE_REFERENCE,
    )
    return DeploymentRequest(
        metadata=metadata,
        adapter=PullbackMasterNativeAdapter(PullbackMasterConfig.tradingview_v2_20260814()),
        context_provider=context_provider or (lambda: {}),
        scheduler_interval_seconds=5.0,
        activation_enabled=True,
        activation_reason=None,
    )
