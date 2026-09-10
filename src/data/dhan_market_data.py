from src.broker.dhan_client import DhanClient


class DhanMarketDataClient:
    """Narrow read-only Dhan Data API boundary; exposes no order methods."""

    def __init__(self, client=None):
        self._client = client or DhanClient()

    def get_intraday_candles(self, **kwargs):
        return self._client.get_intraday_candles(**kwargs)

    def get_quote(self, segment, security_id):
        """Expose the existing read-only quote path for an already locked contract."""

        return self._client.get_quote(segment, security_id)
