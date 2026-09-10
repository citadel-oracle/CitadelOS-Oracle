from datetime import datetime, timezone

from .cache import ForecastCache
from .config import KronosAlphaConfig
from .history import ForecastHistoryLedger, RealizationEvaluator
from .outlooks import option_outlooks


class KronosAlphaService:
    """Read-only production projection over a separately produced forecast cache."""

    def __init__(self, config=None, cache=None, runtime_provider=None, ledger=None):
        self.config = config or KronosAlphaConfig()
        self.cache = cache or ForecastCache(self.config.cache_path)
        self.runtime_provider = runtime_provider
        self.ledger = ledger or ForecastHistoryLedger(self.config.history_path)
        self.evaluator = RealizationEvaluator(self.ledger)

    def status(self):
        document = self.cache.read()
        if document is None:
            return self._unavailable()
        result = dict(document)
        runtime = self._runtime()
        result.update({key: value for key, value in runtime.items() if value is not None})
        age = self.cache.age_seconds(document)
        result["input_age_seconds"] = age
        if age is None:
            return self._unavailable("FORECAST_CACHE_CORRUPT")
        market_closed = runtime.get("session", {}).get("market_open") is False and runtime.get("session", {}).get("session_state") != "UNKNOWN"
        if market_closed:
            result["cache_status"] = "CACHED_MARKET_CLOSED"
            result["reason_codes"] = sorted(set(result.get("reason_codes", [])) | {"MARKET_CLOSED", "FORECAST_FROZEN", "ADVISORY_ONLY", "NO_EXECUTION_PERMISSION"})
        elif age > self.config.stale_after_seconds:
            result["model_status"] = "STALE"
            result["cache_status"] = "STALE"
            result["reason_codes"] = sorted(set(result.get("reason_codes", [])) | {"FORECAST_STALE", "ADVISORY_ONLY", "NO_EXECUTION_PERMISSION"})
        return self._sanitize(result)

    def forecast(self):
        return self.status()

    def outlooks(self):
        status = self.status()
        return {"generated_at": status["generated_at"], "model_status": status["model_status"], "session": status.get("session"), "outlooks": status.get("outlooks"), "mode": "SHADOW", "execution_influence_percentage": 0, "aegis_influence_percentage": 0}

    def history(self):
        return self.ledger.payload()

    def evaluation(self):
        return self.evaluator.summary()

    def _unavailable(self, reason="MODEL_CACHE_MISSING"):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        runtime = self._runtime()
        input_metadata = runtime.get("input_metadata") or {}
        session = runtime.get("session") or {}
        input_ready = input_metadata.get("candle_count", 0) >= self.config.minimum_context and input_metadata.get("health") in {"READY", "DEGRADED"}
        market_closed = session.get("market_open") is False and session.get("session_state") != "UNKNOWN"
        readiness = "READY_FOR_NEXT_OPEN" if input_ready and market_closed else "INPUT_READY" if input_ready else "INPUT_UNAVAILABLE"
        warning = "Real closed-candle input is cached; no genuine forecast exists until the next eligible candle-close job." if input_ready else "Authoritative closed-candle history is not available to the shadow cache."
        missing = ["genuine_forecast"] if input_ready else ["authoritative_closed_candles", "forecast_cache"]
        return self._sanitize({
            "schema_version": ForecastCache.SCHEMA_VERSION,
            "generated_at": now,
            "model_status": "UNAVAILABLE",
            "device": None,
            "input_candle_count": None,
            "last_input_candle_at": None,
            "input_age_seconds": None,
            "last_inference_at": None,
            "inference_duration_ms": None,
            "cache_status": "INPUT_CACHED_MARKET_CLOSED" if input_ready and market_closed else "INPUT_CACHED" if input_ready else "MISSING",
            "readiness_state": readiness,
            "expected_direction": "UNKNOWN",
            "bullish_probability": None,
            "bearish_probability": None,
            "sideways_probability": None,
            "expected_return_percentage": None,
            "median_return_percentage": None,
            "forecast_volatility": None,
            "volatility_label": "UNKNOWN",
            "trend_persistence_probability": None,
            "reversal_probability": None,
            "forecast_uncertainty": None,
            "uncertainty_label": "UNKNOWN",
            "forecast_dispersion": None,
            "upside_quantile": None,
            "downside_quantile": None,
            "expected_high": None,
            "expected_low": None,
            "path_count": None,
            "valid_path_count": None,
            "horizon_candles": self.config.forecast_horizon,
            "horizon_minutes": 60,
            "reason_codes": ["INPUT_CACHE_READY" if input_ready else reason, "MARKET_CLOSED" if market_closed else "FORECAST_PENDING", "KRONOS_ALPHA_SHADOW_MODE", "EXECUTION_INFLUENCE_ZERO", "ADVISORY_ONLY", "NO_EXECUTION_PERMISSION"],
            "warnings": [warning],
            "missing_inputs": missing,
            "source_metadata": {"source": "KRONOS_ALPHA_CACHE", "fixture_data": False, "external_refresh_on_read": False},
            "outlooks": option_outlooks(None, None),
            "session": session or None,
            "scheduler_health": runtime.get("scheduler_health", "NOT_STARTED"),
            "next_expected_inference": runtime.get("next_expected_inference"),
            "input_metadata": input_metadata or None,
            "evaluation": runtime.get("evaluation", self.evaluator.summary()),
        })

    def _runtime(self):
        if self.runtime_provider is None:
            return {}
        try:
            value = self.runtime_provider()
            return value if isinstance(value, dict) else {}
        except Exception:
            return {"scheduler_health": "DEGRADED"}

    def _sanitize(self, result):
        merged = {**self.config.public_metadata(), **result}
        merged["mode"] = "SHADOW"
        merged.setdefault("readiness_state", "FORECAST_READY" if merged.get("model_status") == "READY" else "UNAVAILABLE")
        merged["execution_influence_percentage"] = 0
        merged["aegis_influence_percentage"] = 0
        merged["maturity_label"] = "EXPERIMENTAL_SHADOW"
        merged["reason_codes"] = list(dict.fromkeys(merged.get("reason_codes") or ["KRONOS_ALPHA_SHADOW_MODE"]))[:32]
        merged["warnings"] = list(merged.get("warnings") or [])[:16]
        merged["missing_inputs"] = list(merged.get("missing_inputs") or [])[:16]
        return merged
