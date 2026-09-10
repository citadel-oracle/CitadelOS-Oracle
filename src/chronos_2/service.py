from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.market.session_calendar import NSESessionCalendar

from .analytics import derive_analytics, unavailable_analytics
from .config import Chronos2Config
from .evaluation import ChronosRealizationEvaluator
from .inputs import (
    argus_features,
    build_model_rows,
    future_timestamps,
    input_fingerprint,
    recent_volatility_points,
    validate_closed_candles,
)
from .storage import AtomicJsonDocument, ChronosStorageError, ForecastLedger


IST = ZoneInfo("Asia/Kolkata")


class IsolatedChronosWorker:
    def __init__(self, config=None):
        self.config = config or Chronos2Config()

    def run(self, request, preferred_device="mps"):
        errors = []
        for device in ([preferred_device, "cpu"] if preferred_device != "cpu" else ["cpu"]):
            try:
                return self._invoke(request, device), errors
            except (subprocess.TimeoutExpired, RuntimeError, OSError, ValueError) as error:
                errors.append({"device": device, "error": type(error).__name__})
        raise RuntimeError("CHRONOS_2_INFERENCE_FAILED")

    def _invoke(self, request, device):
        input_handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        output_handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        input_path, output_path = Path(input_handle.name), Path(output_handle.name)
        try:
            json.dump(request, input_handle, separators=(",", ":")); input_handle.close(); output_handle.close()
            environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            completed = subprocess.run(
                [str(self.config.environment_python), "-m", "src.chronos_2.runner", "--input", str(input_path),
                 "--output", str(output_path), "--model-path", str(self.config.model_path), "--device", device],
                cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True,
                timeout=self.config.runner_timeout_seconds, check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("CHRONOS_2_RUNNER_FAILED")
            value = json.loads(output_path.read_text(encoding="utf-8"))
            if value.get("model_class") != "Chronos2Pipeline":
                raise RuntimeError("UNOFFICIAL_MODEL_RUNTIME")
            return value
        finally:
            try: input_handle.close(); output_handle.close()
            except OSError: pass
            input_path.unlink(missing_ok=True); output_path.unlink(missing_ok=True)


class Chronos2Scheduler:
    def __init__(self, *, config=None, calendar=None, candle_source=None, argus_provider=None, worker=None, clock=None):
        self.config = config or Chronos2Config()
        self.calendar = calendar or NSESessionCalendar()
        self.candle_source = candle_source
        self.argus_provider = argus_provider or (lambda: None)
        self.worker = worker or IsolatedChronosWorker(self.config)
        self.clock = clock or (lambda: datetime.now(IST))
        self.cache = AtomicJsonDocument(self.config.forecast_cache_path)
        self.ledger = ForecastLedger(self.config.history_path)
        self.evaluator = ChronosRealizationEvaluator(self.ledger)
        self._lock = threading.Lock(); self._stop = threading.Event(); self._thread = None
        self._state = "NOT_STARTED"; self._last_error = None; self._last_origin = None; self._next_inference = None

    def initialize(self):
        candles = self._cached_candles()
        try: self.evaluator.evaluate(candles, now=self.clock())
        except ChronosStorageError: self._state, self._last_error = "DEGRADED", "HISTORY_CORRUPT"
        session = self.calendar.status(self.clock())
        if self._state != "DEGRADED": self._state = "READY" if session["market_open"] else "MARKET_CLOSED"
        self._next_inference = self._next_after_open(session) if not session["market_open"] else self._next_close(self.clock())
        return self.projection()

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self.initialize(); self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="chronos-2-scheduler", daemon=True); self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=2)
        self._state = "STOPPED"

    def tick(self, now=None):
        reference = self._aware(now or self.clock()); session = self.calendar.status(reference)
        if not session["market_open"]:
            self._state = "MARKET_CLOSED"; self._next_inference = self._next_after_open(session)
            return {"ran": False, "reason": session["session_state"]}
        if not self._lock.acquire(blocking=False): return {"ran": False, "reason": "JOB_ALREADY_RUNNING"}
        try:
            candles = validate_closed_candles(self._cached_candles(), minimum=self.config.minimum_context,
                                               limit=self.config.runtime_context, now=reference)
            self.evaluator.evaluate(candles, now=reference)
            origin = candles[-1]["timestamp"]
            cached = self.cache.read()
            if origin == self._last_origin or cached and cached.get("context_end") == origin:
                return {"ran": False, "reason": "SKIPPED_DUPLICATE"}
            result = self.run_with_candles(candles, generated_at=reference, session=session)
            self._state = "READY"; self._last_error = None; self._last_origin = origin; self._next_inference = self._next_close(reference)
            return {"ran": True, "forecast_id": result["forecast_id"]}
        except Exception as error:
            self._state, self._last_error = "DEGRADED", type(error).__name__
            return {"ran": False, "reason": "JOB_FAILED"}
        finally:
            self._lock.release()

    def run_with_candles(self, candles, *, generated_at=None, session=None, preferred_device="mps"):
        generated = self._aware(generated_at or self.clock())
        validated = validate_closed_candles(candles, minimum=self.config.minimum_context,
                                             limit=self.config.runtime_context, now=generated)
        rows, mode, feature_names, coverage = build_model_rows(validated)
        future = future_timestamps(validated[-1]["timestamp"], self.config.prediction_length, self.calendar)
        fingerprint = input_fingerprint(validated, feature_names, self.config.model_revision)
        request = {"symbol": self.config.symbol, "rows": rows, "feature_names": feature_names,
                   "prediction_length": self.config.prediction_length, "future_timestamps": future}
        raw, fallbacks = self.worker.run(request, preferred_device=preferred_device)
        forecast_rows = raw["forecast_rows"]
        origin = validated[-1]["close"]
        terminal = forecast_rows[-1]
        result = {
            **self.config.public_metadata(), "generated_at": generated.isoformat(), "forecast_origin": origin,
            "context_start": validated[0]["timestamp"], "context_end": validated[-1]["timestamp"],
            "input_candle_count": len(validated), "input_feature_count": 1 + len(feature_names),
            "input_feature_names": ["close", *feature_names], "input_coverage": coverage, "mode": mode,
            "forecast_rows": forecast_rows, "terminal_p10": terminal["p10"], "terminal_p50": terminal["p50"],
            "terminal_p90": terminal["p90"], "median_terminal_move_points": terminal["p50"] - origin,
            "median_terminal_move_percentage": 100 * (terminal["p50"] / origin - 1),
            "forecast_low": min(row["p10"] for row in forecast_rows),
            "forecast_high": max(row["p90"] for row in forecast_rows),
            "prediction_interval_width": max(row["p90"] for row in forecast_rows) - min(row["p10"] for row in forecast_rows),
            "forecast_dispersion": sum(row["p90"] - row["p10"] for row in forecast_rows) / len(forecast_rows),
            "freshness": validated[-1].get("freshness") or "HISTORICAL", "device": raw["device"],
            "inference_duration_ms": raw["inference_duration_ms"], "model_load_duration_ms": raw["model_load_duration_ms"],
            "status": "READY", "warnings": ["CLOSED_CANDLE_INPUTS_ONLY", *(["MPS_FALLBACK_USED"] if fallbacks else []),
                *(["MULTIVARIATE_INPUT_INSUFFICIENT"] if mode == "UNIVARIATE" else []),
                "ARGUS_CURRENT_SNAPSHOT_NOT_USED_AS_MODEL_HISTORY"],
            "input_fingerprint": fingerprint, "session": session or self.calendar.status(generated), "schema_version": 1,
        }
        argus = argus_features(self.argus_provider())
        result["argus_feature_projection"] = argus
        result["derived_analytics"] = derive_analytics(result, origin=origin,
                                                        recent_volatility=recent_volatility_points(validated), argus=argus)
        forecast_id, _ = self.ledger.append_forecast(result); result["forecast_id"] = forecast_id
        self.cache.write(result)
        return result

    def projection(self):
        candles = self._cached_candles(); session = self.calendar.status(self.clock())
        return {"scheduler_health": self._state, "last_error": self._last_error, "last_origin": self._last_origin,
                "next_expected_inference": self._next_inference, "session": session,
                "input_metadata": {"health": "READY" if len(candles) >= self.config.runtime_context else "DEGRADED" if len(candles) >= self.config.minimum_context else "UNAVAILABLE",
                                   "candle_count": len(candles), "last_candle_at": candles[-1]["timestamp"] if candles else None,
                                   "source": "SHARED_KRONOS_CLOSED_CANDLE_CACHE", "provider_refresh_on_read": False}}

    def _cached_candles(self):
        return self.candle_source.load_cache() if self.candle_source is not None else []

    def _loop(self):
        while not self._stop.wait(5):
            now = self._aware(self.clock()); session = self.calendar.status(now)
            if not session["market_open"]:
                self._state = "MARKET_CLOSED"; self._next_inference = self._next_after_open(session); self._stop.wait(55); continue
            if self._next_inference is None or now >= datetime.fromisoformat(self._next_inference): self.tick(now)

    def _next_close(self, now):
        minute = (now.minute // 5 + 1) * 5; boundary = now.replace(second=0, microsecond=0)
        boundary = boundary.replace(minute=0) + timedelta(hours=1) if minute >= 60 else boundary.replace(minute=minute)
        return (boundary + timedelta(seconds=self.config.provider_grace_seconds)).isoformat()

    def _next_after_open(self, session):
        return (datetime.fromisoformat(session["next_valid_open"]) + timedelta(minutes=5, seconds=self.config.provider_grace_seconds)).isoformat() if session.get("next_valid_open") else None

    @staticmethod
    def _aware(value):
        return value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)


class Chronos2Service:
    def __init__(self, scheduler, kronos_provider=None):
        self.scheduler = scheduler; self.config = scheduler.config; self.cache = scheduler.cache
        self.ledger = scheduler.ledger; self.evaluator = scheduler.evaluator; self.kronos_provider = kronos_provider or (lambda: {})

    def status(self):
        runtime = self.scheduler.projection()
        try: document = self.cache.read()
        except ChronosStorageError as error: return self._unavailable(str(error), runtime, corrupt=True)
        if document is None: return self._unavailable("FORECAST_CACHE_MISSING", runtime)
        result = dict(document); result.update({"runtime": runtime})
        generated = datetime.fromisoformat(result["generated_at"].replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds())
        result["age_seconds"] = age
        market_closed = runtime["session"].get("market_open") is False
        if market_closed: result["status"], result["freshness"] = "LAST_FORECAST", "HISTORICAL"
        elif age > self.config.stale_after_seconds: result["status"], result["freshness"] = "STALE", "STALE"
        result["warnings"] = list(dict.fromkeys(result.get("warnings", []) + (["MARKET_CLOSED_LAST_FORECAST_NOT_ACTIONABLE"] if market_closed else [])))
        return result

    def forecast(self): return self.status()
    def outlook(self):
        value = self.status()
        return {"status": value["status"], "generated_at": value["generated_at"], "derived_analytics": value.get("derived_analytics"),
                "shadow_mode": True, "execution_influence": 0, "aegis_direct_influence": 0, "schema_version": 1}
    def history(self, limit=50):
        try: return self.ledger.history(limit)
        except ChronosStorageError as error: return {"status": "unavailable", "error": str(error), "count": 0, "forecasts": [], "evaluation_count": 0, "schema_version": 1}
    def evaluation(self):
        try: return self.evaluator.summary()
        except ChronosStorageError as error: return {"status": "unavailable", "error": str(error), "evaluated_forecasts": 0, "maturity": "COLLECTING"}
    def features(self):
        value = self.status()
        return {"status": value["status"], "mode": value.get("mode"), "input_feature_names": value.get("input_feature_names", []),
                "input_coverage": value.get("input_coverage"), "argus_feature_projection": value.get("argus_feature_projection"),
                "historical_option_features_used": False, "reason": "NO_TIMESTAMPED_ARGUS_HISTORY", "schema_version": 1}
    def comparison(self):
        chronos = self.status(); kronos = self.kronos_provider() or {}
        same_origin = chronos.get("context_end") and chronos.get("context_end") == kronos.get("last_input_candle_at")
        c_direction = (chronos.get("derived_analytics") or {}).get("directional_bias")
        k_direction = kronos.get("expected_direction")
        comparable = bool(same_origin and c_direction not in {None, "UNAVAILABLE"} and k_direction not in {None, "UNKNOWN"})
        agreement = "UNAVAILABLE" if not comparable else "AGREE" if c_direction == k_direction else "PARTIAL" if "SIDEWAYS" in {c_direction, k_direction} else "CONFLICT"
        count = 0; maturity = "COLLECTING"
        return {"status": "available", "comparable": comparable, "same_origin": bool(same_origin), "agreement": agreement,
                "chronos_direction": c_direction, "kronos_direction": k_direction,
                "chronos_uncertainty": (chronos.get("derived_analytics") or {}).get("uncertainty"), "kronos_uncertainty": kronos.get("uncertainty_label"),
                "chronos_ce_quality": ((chronos.get("derived_analytics") or {}).get("ce_quality") or {}).get("score"),
                "chronos_pe_quality": ((chronos.get("derived_analytics") or {}).get("pe_quality") or {}).get("score"),
                "kronos_ce_quality": (((kronos.get("outlooks") or {}).get("ce") or {}).get("option_buying_quality_score")),
                "kronos_pe_quality": (((kronos.get("outlooks") or {}).get("pe") or {}).get("option_buying_quality_score")),
                "rolling_sample_count": count, "maturity": maturity, "rolling_winner": None,
                "warning": "NO_SUPERIOR_MODEL_BEFORE_20_COMPARABLE_FORECASTS", "schema_version": 1}

    def _unavailable(self, reason, runtime, corrupt=False):
        session = runtime.get("session") or {}; candles = (runtime.get("input_metadata") or {}).get("candle_count", 0)
        input_ready = candles >= self.config.minimum_context
        return {**self.config.public_metadata(), "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "UNAVAILABLE" if corrupt or not input_ready else "WAITING_FOR_ELIGIBLE_CLOSED_CANDLE_INPUT",
                "freshness": "UNAVAILABLE", "mode": None, "forecast_id": None, "context_start": None, "context_end": None,
                "input_candle_count": candles or None, "input_feature_count": None, "input_feature_names": [], "input_coverage": None,
                "forecast_rows": [], "median_terminal_move_points": None, "median_terminal_move_percentage": None,
                "forecast_low": None, "forecast_high": None, "prediction_interval_width": None, "forecast_dispersion": None,
                "terminal_p10": None, "terminal_p50": None, "terminal_p90": None, "device": None, "inference_duration_ms": None,
                "warnings": [reason, "NO_SYNTHETIC_FORECAST", "FRONTEND_GET_DOES_NOT_TRIGGER_INFERENCE"],
                "derived_analytics": unavailable_analytics(reason), "runtime": runtime, "next_eligible_session": session.get("next_valid_open"),
                "model_readiness": "READY" if self.config.model_path.exists() else "UNAVAILABLE", "input_readiness": "READY" if input_ready else "UNAVAILABLE",
                "schema_version": 1}
