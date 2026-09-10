"""Twelve paper-only option-chart deployment definitions."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .completed_candle import CompletedCandleContextProvider, deployment_held_security_id_provider
from .option_charts import OptionChartCandleFeed
from .strategies.breakout_main import build_deployment_request as breakout_request
from .strategies.pullback_master import build_deployment_request as pullback_request


OPTION_CHART_DEPLOYMENTS = (
    # Pullback
    ("PB_NIFTY_CE_1M", "PULLBACK", "CE", "1m"),
    ("PB_NIFTY_CE_3M", "PULLBACK", "CE", "3m"),
    ("PB_NIFTY_PE_1M", "PULLBACK", "PE", "1m"),
    ("PB_NIFTY_PE_3M", "PULLBACK", "PE", "3m"),
    # Breakout
    ("BO_NIFTY_CE_1M", "BREAKOUT", "CE", "1m"),
    ("BO_NIFTY_CE_3M", "BREAKOUT", "CE", "3m"),
    ("BO_NIFTY_PE_1M", "BREAKOUT", "PE", "1m"),
    ("BO_NIFTY_PE_3M", "BREAKOUT", "PE", "3m"),
    # Trend Catcher
    ("TC_NIFTY_PE_1M", "TREND_CATCHER", "PE", "1m"),
    ("TC_NIFTY_PE_3M", "TREND_CATCHER", "PE", "3m"),
    # Bull Pulse
    ("BP_NIFTY_CE_1M", "BULL_PULSE", "CE", "1m"),
    ("BP_NIFTY_CE_3M", "BULL_PULSE", "CE", "3m"),
)


def build_option_chart_deployments(
    *,
    feed: OptionChartCandleFeed,
    argus_provider: Callable[[], Mapping[str, Any] | None],
    service: Optional[Any] = None,
) -> list[Any]:
    from .strategies.trend_catcher import build_deployment_request as build_trend_catcher_deployment
    from .strategies.bull_pulse import build_deployment_request as build_bull_pulse_deployment

    requests = []
    for deployment_id, kind, side, timeframe in OPTION_CHART_DEPLOYMENTS:
        held_provider = (
            deployment_held_security_id_provider(service, deployment_id)
            if service is not None
            else None
        )
        context = CompletedCandleContextProvider(
            candle_source=feed.source(side, timeframe),
            argus_provider=argus_provider,
            max_age_seconds=600.0,
            held_security_id_provider=held_provider,
            canonical_5m_source=feed.source(side, "5m") if kind == "PULLBACK" else None,
        )
        if kind == "PULLBACK":
            builder = pullback_request
            requests.append(builder(
                context,
                deployment_id=deployment_id,
                deployment_name=deployment_id,
                chart_symbol=f"NIFTY_{side}",
                chart_timeframe=timeframe,
                option_type=side,
            ))
        elif kind == "BREAKOUT":
            builder = breakout_request
            requests.append(builder(
                context,
                deployment_id=deployment_id,
                deployment_name=deployment_id,
                chart_symbol=f"NIFTY_{side}",
                chart_timeframe=timeframe,
                option_type=side,
            ))
        elif kind == "TREND_CATCHER":
            mode = "SHADOW" if timeframe == "1m" else "OFF"
            requests.append(build_trend_catcher_deployment(
                context,
                deployment_id=deployment_id,
                deployment_name=deployment_id,
                chart_symbol="NIFTY",
                chart_timeframe=timeframe,
                option_type=side,
                mode=mode,
            ))
        elif kind == "BULL_PULSE":
            mode = "SHADOW" if timeframe == "1m" else "OFF"
            requests.append(build_bull_pulse_deployment(
                context,
                deployment_id=deployment_id,
                deployment_name=deployment_id,
                chart_symbol="NIFTY",
                chart_timeframe=timeframe,
                option_type=side,
                mode=mode,
            ))
    return requests
