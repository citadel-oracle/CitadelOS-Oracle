"""R1: EOD aggregation must not contend with the live market runtime."""

from pathlib import Path

from src.order_flow.research import OrderFlowResearchAggregator


class _Recorder:
    pass


def test_research_aggregation_defers_when_market_is_open(tmp_path):
    aggregator = OrderFlowResearchAggregator(
        _Recorder(), Path(tmp_path), market_open_provider=lambda: True,
    )

    assert aggregator.start() is False
    assert aggregator.latest()["status"] == "DEFERRED_LIVE_SESSION"
