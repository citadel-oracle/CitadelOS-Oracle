from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chronos2Config:
    model_name: str = "amazon/chronos-2"
    model_revision: str = "29ec3766d36d6f73f0696f85560a422f50e8498c"
    upstream_repository: str = "https://github.com/amazon-science/chronos-forecasting"
    upstream_revision: str = "7dc4435706a4454feb79df44ca9f33631f3027bf"
    package_name: str = "chronos-forecasting"
    package_version: str = "2.3.1"
    license: str = "Apache-2.0"
    symbol: str = "NIFTY"
    timeframe: str = "5m"
    runtime_context: int = 256
    minimum_context: int = 64
    prediction_length: int = 12
    quantile_levels: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)
    stale_after_seconds: int = 600
    provider_grace_seconds: int = 10
    runner_timeout_seconds: int = 45
    shadow_mode: bool = True
    execution_influence: int = 0
    aegis_direct_influence: int = 0
    advisory_only: bool = True
    environment_python: Path = Path(".venv-chronos-2/bin/python")
    model_path: Path = Path("/Users/ayushmudgal/Developer/models/chronos-2")
    candle_cache_path: Path = Path("logs/kronos_alpha_candles.json")
    forecast_cache_path: Path = Path("logs/chronos_2_forecast.json")
    history_path: Path = Path("logs/chronos_2_history.json")

    def public_metadata(self):
        return {
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "upstream_revision": self.upstream_revision,
            "package_version": self.package_version,
            "license": self.license,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "prediction_length": self.prediction_length,
            "quantile_levels": list(self.quantile_levels),
            "shadow_mode": self.shadow_mode,
            "execution_influence": self.execution_influence,
            "aegis_direct_influence": self.aegis_direct_influence,
            "advisory_only": self.advisory_only,
        }
