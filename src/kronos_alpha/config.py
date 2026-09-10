from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KronosAlphaConfig:
    model_name: str = "NeoQuasar/Kronos-small"
    model_variant: str = "small"
    model_revision: str = "901c26c1332695a2a8f243eb2f37243a37bea320"
    tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base"
    tokenizer_revision: str = "0e0117387f39004a9016484a186a908917e22426"
    upstream_revision: str = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
    symbol: str = "NIFTY"
    timeframe: str = "5m"
    context_limit: int = 512
    runtime_context: int = 256
    minimum_context: int = 64
    forecast_horizon: int = 12
    sample_count: int = 20
    sideways_threshold_percentage: float = 0.15
    stale_after_seconds: int = 600
    mode: str = "SHADOW"
    maturity_label: str = "EXPERIMENTAL_SHADOW"
    execution_influence_percentage: int = 0
    aegis_influence_percentage: int = 0
    cache_path: Path = Path("logs/kronos_alpha_forecast.json")
    candle_cache_path: Path = Path("logs/kronos_alpha_candles.json")
    history_path: Path = Path("logs/kronos_alpha_history.json")
    provider_grace_seconds: int = 10
    runner_timeout_seconds: int = 90
    model_environment_python: Path = Path(".venv-kronos-alpha/bin/python")
    source_root: Path = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/source/Kronos")
    model_path: Path = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-small/snapshots/901c26c1332695a2a8f243eb2f37243a37bea320")
    tokenizer_path: Path = Path("/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-Tokenizer-base/snapshots/0e0117387f39004a9016484a186a908917e22426")

    def public_metadata(self):
        return {
            "model_name": self.model_name,
            "model_variant": self.model_variant,
            "model_revision": self.model_revision,
            "tokenizer_name": self.tokenizer_name,
            "tokenizer_revision": self.tokenizer_revision,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "context_limit": self.context_limit,
            "forecast_horizon": self.forecast_horizon,
            "sample_count": self.sample_count,
            "mode": self.mode,
            "maturity_label": self.maturity_label,
            "execution_influence_percentage": self.execution_influence_percentage,
            "aegis_influence_percentage": self.aegis_influence_percentage,
        }
