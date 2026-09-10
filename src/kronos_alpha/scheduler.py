import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.market.session_calendar import NSESessionCalendar

from .cache import ForecastCache
from .candle_source import RealNiftyCandleSource
from .config import KronosAlphaConfig
from .history import ForecastHistoryLedger, RealizationEvaluator
from .outlooks import forecast_quality, option_outlooks


class LocalModelWorker:
    def __init__(self, config):
        self.config = config

    def run(self, candles, device="mps"):
        request = {
            "symbol": self.config.symbol,
            "source": "DHAN_DATA_API",
            "candles": candles[-self.config.runtime_context:],
            "minimum_context": self.config.minimum_context,
            "forecast_horizon": self.config.forecast_horizon,
            "sample_count": self.config.sample_count,
            "sideways_threshold_percentage": self.config.sideways_threshold_percentage,
        }
        input_handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        output_handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        input_path, output_path = Path(input_handle.name), Path(output_handle.name)
        try:
            json.dump(request, input_handle, separators=(",", ":"))
            input_handle.close()
            output_handle.close()
            environment = {**os.environ, "HF_HUB_OFFLINE": "1"}
            command = [
                str(self.config.model_environment_python), "-m", "src.kronos_alpha.runner",
                "--input", str(input_path), "--output", str(output_path),
                "--source-root", str(self.config.source_root),
                "--model-path", str(self.config.model_path),
                "--tokenizer-path", str(self.config.tokenizer_path),
                "--device", device,
            ]
            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True, timeout=self.config.runner_timeout_seconds, check=False)
            if completed.returncode != 0:
                raise RuntimeError("KRONOS ALPHA runner failed")
            return json.loads(output_path.read_text(encoding="utf-8"))
        finally:
            input_handle.close()
            output_handle.close()
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


class KronosAlphaScheduler:
    TIMEZONE = ZoneInfo("Asia/Kolkata")

    def __init__(self, config=None, calendar=None, candle_source=None, worker=None, cache=None, ledger=None, clock=None):
        self.config = config or KronosAlphaConfig()
        self.calendar = calendar or NSESessionCalendar()
        self.clock = clock or (lambda: datetime.now(self.TIMEZONE))
        self.candle_source = candle_source or RealNiftyCandleSource(calendar=self.calendar, cache_path=self.config.candle_cache_path, clock=self.clock)
        self.worker = worker or LocalModelWorker(self.config)
        self.cache = cache or ForecastCache(self.config.cache_path)
        self.ledger = ledger or ForecastHistoryLedger(self.config.history_path)
        self.evaluator = RealizationEvaluator(self.ledger)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._state = "NOT_STARTED"
        self._last_error = None
        self._last_job_candle = None
        self._next_inference = None

    def initialize(self):
        try:
            candles = self.candle_source.backfill(self.config.runtime_context, now=self.clock())
            self.evaluator.evaluate(candles, now=self.clock())
            session = self.calendar.status(self.clock())
            self._state = "READY" if session["market_open"] else "MARKET_CLOSED"
            if session["market_open"]:
                self.tick()
            else:
                self._next_inference = self._next_after_open(session)
        except Exception as exc:
            self._state = "DEGRADED"
            self._last_error = str(exc)
        return self.projection()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.initialize()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="kronos-alpha-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._state = "STOPPED"

    def tick(self, now=None):
        reference = self._aware(now or self.clock())
        session = self.calendar.status(reference)
        if not session["market_open"]:
            self._state = "MARKET_CLOSED" if session["session_state"] != "UNKNOWN" else "CALENDAR_UNAVAILABLE"
            self._next_inference = self._next_after_open(session)
            return {"ran": False, "reason": session["session_state"]}
        if not self._lock.acquire(blocking=False):
            return {"ran": False, "reason": "JOB_ALREADY_RUNNING"}
        try:
            self._state = "FETCHING_CLOSED_CANDLE"
            candles = self.candle_source.backfill(self.config.runtime_context, now=reference)
            if len(candles) < self.config.minimum_context:
                raise RuntimeError("INPUT_INSUFFICIENT")
            last_candle = candles[-1]["timestamp"]
            cached = self.cache.read()
            if last_candle == self._last_job_candle or (cached and cached.get("last_input_candle_at") == last_candle):
                self._state = "READY"
                self._next_inference = self._next_close(reference)
                return {"ran": False, "reason": "DUPLICATE_CANDLE"}
            self._state = "INFERENCE_RUNNING"
            result = self.worker.run(candles, device="mps")
            result.update(self.config.public_metadata())
            result["model_revision"] = self.config.model_revision
            result["tokenizer_revision"] = self.config.tokenizer_revision
            result["session"] = session
            result["scheduler_health"] = "READY"
            result["next_expected_inference"] = self._next_close(reference)
            result["input_metadata"] = {**self.candle_source.last_status, "freshness": candles[-1]["freshness"]}
            quality = forecast_quality(result, self.config.sample_count, input_fresh=candles[-1]["freshness"] == "FRESH")
            result["outlooks"] = option_outlooks(result, quality, input_fresh=candles[-1]["freshness"] == "FRESH")
            result["evaluation"] = self.evaluator.summary()
            result["reason_codes"] = [*result.get("reason_codes", []), "REAL_CANDLE_DATA", "SCHEDULER_CANDLE_CLOSE"]
            self.cache.write(result)
            forecast_id, _ = self.ledger.append_forecast(result)
            result["forecast_id"] = forecast_id
            self._last_job_candle = last_candle
            self.evaluator.evaluate(candles, now=reference)
            self._state = "READY"
            self._last_error = None
            self._next_inference = self._next_close(reference)
            return {"ran": True, "forecast_id": forecast_id}
        except subprocess.TimeoutExpired:
            self._state, self._last_error = "DEGRADED", "MODEL_TIMEOUT"
            return {"ran": False, "reason": "MODEL_TIMEOUT"}
        except Exception as exc:
            self._state, self._last_error = "DEGRADED", str(exc)
            return {"ran": False, "reason": "JOB_FAILED"}
        finally:
            self._lock.release()

    def projection(self):
        session = self.calendar.status(self.clock())
        return {
            "scheduler_health": self._state,
            "next_expected_inference": self._next_inference,
            "last_job_candle": self._last_job_candle,
            "last_error": self._last_error,
            "session": session,
            "input_metadata": self.candle_source.last_status,
            "evaluation": self.evaluator.summary(),
        }

    def _loop(self):
        while not self._stop.wait(5):
            now = self._aware(self.clock())
            session = self.calendar.status(now)
            if not session["market_open"]:
                self._state = "MARKET_CLOSED" if session["session_state"] != "UNKNOWN" else "CALENDAR_UNAVAILABLE"
                self._next_inference = self._next_after_open(session)
                self._stop.wait(55)
                continue
            if self._next_inference is None or now >= datetime.fromisoformat(self._next_inference):
                self.tick(now)

    def _next_close(self, now):
        minute = (now.minute // 5 + 1) * 5
        boundary = now.replace(second=0, microsecond=0)
        boundary = boundary.replace(minute=0) + timedelta(hours=1) if minute >= 60 else boundary.replace(minute=minute)
        return (boundary + timedelta(seconds=self.config.provider_grace_seconds)).isoformat()

    def _next_after_open(self, session):
        if not session.get("next_valid_open"):
            return None
        return (datetime.fromisoformat(session["next_valid_open"]) + timedelta(minutes=5, seconds=self.config.provider_grace_seconds)).isoformat()

    def _aware(self, value):
        return value.replace(tzinfo=self.TIMEZONE) if value.tzinfo is None else value.astimezone(self.TIMEZONE)
