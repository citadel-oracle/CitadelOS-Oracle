"""One bounded owner for Futures-only Kronos, Chronos-2 and TiRex inference."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping

from src.chronos_2.inputs import build_model_rows

from .math import ForecastValidationError, validate_ohlc_path, validate_quantile_matrix
from .history import context_hash
from .session_time import ForecastTimeError, NSEForecastTimeMapper
from .tirex_state import TiRexStateClassifier
from .workers import LatestWinsQueue, PersistentJsonWorker


_ROOT = Path(__file__).resolve().parents[2]
_KRONOS_PYTHON = Path("/Users/ayushmudgal/Developer/CitadelOS/.venv-kronos-alpha/bin/python")
_CHRONOS_PYTHON = Path("/Users/ayushmudgal/Developer/CitadelOS/.venv-chronos-2/bin/python")
_TIREX_PYTHON = Path("/Users/ayushmudgal/Developer/models/tirex-2/.venv/bin/python")


class ForecastOrchestratorError(ValueError):
    pass


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


class FuturesForecastOrchestrator:
    """Latest-wins background projection; HTTP paths only copy its cache."""

    SCHEMA_VERSION = 1
    HORIZON = 6
    TIMEFRAME = "5m"
    MINIMUM_CONTEXT = 180

    def __init__(
        self,
        *,
        state_path: str | Path | None = None,
        time_mapper: NSEForecastTimeMapper | None = None,
        kronos_worker=None,
        chronos_worker=None,
        tirex_worker=None,
        kronos_sample_count: int = 8,
        tirex_cadence: str = "5m",
        clock: Callable[[], datetime] | None = None,
    ):
        state_root = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))
        self.state_path = Path(state_path or state_root / "futures_forecast" / "snapshot.json")
        self.time_mapper = time_mapper or NSEForecastTimeMapper()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.kronos_sample_count = int(kronos_sample_count)
        self.tirex_cadence = tirex_cadence
        self.queue = LatestWinsQueue()
        self._kronos = kronos_worker or PersistentJsonWorker(
            [
                str(_KRONOS_PYTHON), "-m", "src.kronos_alpha.runner", "--stdio", "--device", "mps",
                "--source-root", "/Users/ayushmudgal/Developer/models/kronos-alpha/source/Kronos",
                "--model-path", "/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-small/snapshots/901c26c1332695a2a8f243eb2f37243a37bea320",
                "--tokenizer-path", "/Users/ayushmudgal/Developer/models/kronos-alpha/huggingface/models--NeoQuasar--Kronos-Tokenizer-base/snapshots/0e0117387f39004a9016484a186a908917e22426",
            ],
            cwd=_ROOT, environment={"HF_HUB_OFFLINE": "1"}, timeout_seconds=90,
        )
        self._chronos = chronos_worker or PersistentJsonWorker(
            [
                str(_CHRONOS_PYTHON), "-m", "src.chronos_2.runner", "--stdio", "--device", "mps",
                "--model-path", "/Users/ayushmudgal/Developer/models/chronos-2",
            ],
            cwd=_ROOT, environment={"HF_HUB_OFFLINE": "1"}, timeout_seconds=45,
        )
        self._tirex = tirex_worker or PersistentJsonWorker(
            [str(_TIREX_PYTHON), "-m", "src.futures_forecast.tirex_runner", "--stdio", "--device", "cpu"],
            cwd=_ROOT,
            environment={
                "HF_HUB_OFFLINE": "1",
                "HF_HOME": "/Users/ayushmudgal/Developer/models/tirex-2/huggingface",
            },
            timeout_seconds=55,
        )
        self._classifier = TiRexStateClassifier()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_requested_key: str | None = None
        self._snapshot = self._load()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._latencies: dict[str, list[float]] = {"kronos": [], "chronos": [], "tirex": []}
        self._stale_rejections = 0
        self._failures: dict[str, int] = {"kronos": 0, "chronos": 0, "tirex": 0}
        self._state_transitions = 0
        self._last_tirex_state = "NEUTRAL"
        self._forecast_history: deque[dict[str, Any]] = deque(maxlen=10)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="futures-forecast-orchestrator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.queue.close()
        if self._thread:
            self._thread.join(timeout=3)
        for worker in (self._chronos, self._kronos, self._tirex):
            worker.stop()

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def ingest(self, projection: Mapping[str, Any]) -> bool:
        """Non-blocking callback from the sole canonical Futures producer."""
        try:
            request = self._request_from_projection(projection, require_live=True)
        except ForecastOrchestratorError:
            return False
        key = request["forecast_id"]
        with self._lock:
            self._latest_requested_key = key
        return self.queue.submit(key, request)

    def evaluate_historical(self, projection: Mapping[str, Any]) -> dict[str, Any]:
        """Bounded synchronous replay using genuine stored bars and genuine workers."""
        request = self._request_from_projection(projection, require_live=False)
        with self._lock:
            self._latest_requested_key = request["forecast_id"]
        self._process(request["forecast_id"], request, mode="HISTORICAL_REPLAY")
        return self.projection()

    def projection(self) -> dict[str, Any]:
        with self._lock:
            snapshot = deepcopy(self._snapshot)
        if not snapshot:
            return self._unavailable("FORECAST_SNAPSHOT_NOT_READY")
        snapshot["orchestrator"] = self.telemetry()
        return snapshot

    def public_projection(self) -> dict[str, Any]:
        """Browser-safe projection: compact TiRex state, no raw quantile grid."""
        value = self.projection()
        tirex = value.get("tirex")
        if isinstance(tirex, dict):
            for key in ("_raw_quantiles", "raw_state", "classifier_evidence", "classifier_uncertainty"):
                tirex.pop(key, None)
        return value

    def projection_for(self, chart_projection: Mapping[str, Any]) -> dict[str, Any]:
        value = self.public_projection()
        identity = value.get("instrument") or {}
        expected = (
            str(chart_projection.get("contract") or ""),
            str(chart_projection.get("security_id") or ""),
            str(chart_projection.get("expiry") or ""),
            str(chart_projection.get("timeframe") or ""),
        )
        actual = (
            str(identity.get("contract") or ""),
            str(identity.get("security_id") or ""),
            str(identity.get("expiry") or ""),
            str(value.get("timeframe") or ""),
        )
        if not all(expected) or expected != actual:
            return self._unavailable("FORECAST_INSTRUMENT_IDENTITY_MISMATCH", expected=expected, actual=actual)
        expected_source = str(chart_projection.get("source_timestamp") or "")
        actual_source = str(value.get("source_bar_timestamp") or "")
        if not expected_source or expected_source != actual_source:
            return self._unavailable(
                "FORECAST_SOURCE_CANDLE_MISMATCH",
                expected_source=expected_source,
                actual_source=actual_source,
            )
        return value

    def kronos_status(self) -> dict[str, Any]:
        snapshot = self.projection()
        model = snapshot.get("kronos") or {}
        return {
            "schema_version": 2,
            "model_status": model.get("status", "UNAVAILABLE"),
            "cache_status": "READY" if model.get("status") == "READY" else "MISSING",
            "model_name": model.get("model", "NeoQuasar/Kronos-small"),
            "model_revision": model.get("model_revision"),
            "device": model.get("device"),
            "sample_count": model.get("sample_count"),
            "last_input_candle_at": model.get("source_bar_timestamp"),
            "last_inference_at": model.get("generated_at"),
            "inference_duration_ms": model.get("inference_duration_ms"),
            "ghost_ohlc": model.get("ghost_ohlc", []),
            "execution_influence_percentage": 0,
            "advisory_only": True,
            "runtime_owner": "FUTURES_FORECAST_ORCHESTRATOR",
        }

    def chronos_status(self) -> dict[str, Any]:
        snapshot = self.projection()
        model = snapshot.get("chronos") or {}
        return {
            "schema_version": 2,
            "status": model.get("status", "UNAVAILABLE"),
            "model_name": model.get("model", "amazon/chronos-2"),
            "model_revision": model.get("model_revision"),
            "device": model.get("device"),
            "context_end": model.get("source_bar_timestamp"),
            "generated_at": model.get("generated_at"),
            "inference_duration_ms": model.get("inference_duration_ms"),
            "forecast_rows": model.get("forecast_rows", []),
            "execution_influence": 0,
            "advisory_only": True,
            "runtime_owner": "FUTURES_FORECAST_ORCHESTRATOR",
        }

    def comparison(self) -> dict[str, Any]:
        snapshot = self.projection()
        chronos = snapshot.get("chronos") or {}
        kronos = snapshot.get("kronos") or {}
        same_origin = bool(
            chronos.get("source_bar_timestamp")
            and chronos.get("source_bar_timestamp") == kronos.get("source_bar_timestamp")
        )
        return {
            "status": "AVAILABLE" if same_origin else "UNAVAILABLE",
            "same_origin": same_origin,
            "chronos_source_bar_timestamp": chronos.get("source_bar_timestamp"),
            "kronos_source_bar_timestamp": kronos.get("source_bar_timestamp"),
            "warning": "DESCRIPTIVE_FORECASTS_NOT_PROBABILITY",
            "execution_influence": 0,
        }

    def telemetry(self) -> dict[str, Any]:
        with self._lock:
            source = (self._snapshot or {}).get("source_bar_timestamp")
            revision = (self._snapshot or {}).get("forecast_revision")
            snapshot = deepcopy(self._snapshot or {})
        repair = snapshot.get("data_repair") or {}
        generated_at = snapshot.get("generated_at")
        try:
            snapshot_age = max(0.0, (self.clock().astimezone(timezone.utc) - datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))).total_seconds())
        except (TypeError, ValueError):
            snapshot_age = None
        return {
            "status": "RUNNING" if self._thread and self._thread.is_alive() else "STOPPED",
            "runtime_owner": "FUTURES_FORECAST_ORCHESTRATOR",
            "queue_depth": self.queue.depth,
            "dropped_superseded_work": self.queue.dropped,
            "duplicate_source_suppression": self.queue.duplicates,
            "stale_result_rejections": self._stale_rejections,
            "forecast_revision": revision,
            "last_source_candle": source,
            "snapshot_age_seconds": round(snapshot_age, 3) if snapshot_age is not None else None,
            "KRONOS_CONTEXT_BARS": snapshot.get("context_bars"),
            "KRONOS_CONTEXT_FIRST_TIMESTAMP": snapshot.get("context_first_timestamp"),
            "KRONOS_CONTEXT_LAST_TIMESTAMP": snapshot.get("context_last_timestamp"),
            "MISSING_1M_COUNT_BEFORE_REPAIR": repair.get("missing_1m_count_before_repair"),
            "MISSING_1M_COUNT_AFTER_REPAIR": repair.get("missing_1m_count_after_repair"),
            "BACKFILLED_1M_COUNT": repair.get("backfilled_1m_count"),
            "INPUT_CONTEXT_HASH": snapshot.get("input_context_hash"),
            "DATA_REPAIR_STATUS": repair.get("data_repair_status"),
            "last_10_forecast_revisions": deepcopy(list(self._forecast_history)),
            "kronos": {**self._kronos.status(), "p50_ms": _percentile(self._latencies["kronos"], .5), "p95_ms": _percentile(self._latencies["kronos"], .95), "failures": self._failures["kronos"]},
            "chronos": {**self._chronos.status(), "p50_ms": _percentile(self._latencies["chronos"], .5), "p95_ms": _percentile(self._latencies["chronos"], .95), "failures": self._failures["chronos"]},
            "tirex": {**self._tirex.status(), "p50_ms": _percentile(self._latencies["tirex"], .5), "p95_ms": _percentile(self._latencies["tirex"], .95), "failures": self._failures["tirex"], "cadence": self.tirex_cadence, "state_transitions": self._state_transitions},
            "execution_influence": "ZERO",
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self.queue.get(.5)
            if item is None:
                continue
            key, request = item
            self._process(key, request, mode="LIVE")

    def _process(self, key: str, request: dict[str, Any], *, mode: str) -> None:
        base = self._base_snapshot(request, mode)
        self._publish(base)
        for name, worker in (("chronos", self._chronos), ("kronos", self._kronos), ("tirex", self._tirex)):
            started = time.perf_counter()
            try:
                payload = self._worker_request(name, request)
                result = worker.request(payload)
                latency = (time.perf_counter() - started) * 1000
                self._latencies[name].append(latency)
                self._latencies[name] = self._latencies[name][-200:]
                normalized = self._normalize_result(name, result, request)
            except Exception as exc:
                self._failures[name] += 1
                normalized = {
                    "status": "UNAVAILABLE",
                    "reason": f"{type(exc).__name__}:{exc}",
                    "source_bar_timestamp": request["source_bar_timestamp"],
                    "execution_influence": "ZERO",
                }
            with self._lock:
                if key != self._latest_requested_key:
                    self._stale_rejections += 1
                    return
                current = deepcopy(self._snapshot or base)
            current[name] = normalized
            current["generated_at"] = self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            ready = sum((current.get(model) or {}).get("status") == "READY" for model in ("chronos", "kronos", "tirex"))
            current["status"] = "READY" if ready == 3 else "PARTIAL" if ready else "UNAVAILABLE"
            self._publish(current)

    def _request_from_projection(self, projection: Mapping[str, Any], *, require_live: bool) -> dict[str, Any]:
        if projection.get("status") != "AVAILABLE" or projection.get("timeframe") != self.TIMEFRAME:
            raise ForecastOrchestratorError("FUTURES_5M_PROJECTION_UNAVAILABLE")
        if require_live and projection.get("market_status") != "OPEN":
            raise ForecastOrchestratorError("MARKET_NOT_OPEN")
        if projection.get("is_synthetic") is True:
            raise ForecastOrchestratorError("SYNTHETIC_CANDLES_REJECTED")
        contract = str(projection.get("contract") or "")
        security_id = str(projection.get("security_id") or "")
        expiry = str(projection.get("expiry") or "")
        source = str(projection.get("source_timestamp") or "")
        if not contract or not security_id or not expiry or not source:
            raise ForecastOrchestratorError("FUTURES_IDENTITY_INCOMPLETE")
        candles = []
        for item in projection.get("candles") or []:
            if not isinstance(item, Mapping) or item.get("forecast") or item.get("predicted"):
                raise ForecastOrchestratorError("PREDICTION_FEEDBACK_REJECTED")
            try:
                row = {
                    "timestamp": datetime.fromtimestamp(int(item["time"]), tz=timezone.utc).isoformat(),
                    "open": float(item["open"]), "high": float(item["high"]),
                    "low": float(item["low"]), "close": float(item["close"]),
                    "volume": float(item.get("volume") or 0.0),
                    "amount": float(item.get("amount") or 0.0),
                    "closed": True,
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ForecastOrchestratorError("FUTURES_CANDLE_INVALID") from exc
            if row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]):
                raise ForecastOrchestratorError("FUTURES_CANDLE_OHLC_INVALID")
            candles.append(row)
        if len(candles) < self.MINIMUM_CONTEXT:
            raise ForecastOrchestratorError("INSUFFICIENT_CONTEXT")
        timestamps = [row["timestamp"] for row in candles]
        if len(timestamps) != len(set(timestamps)) or timestamps != sorted(timestamps):
            raise ForecastOrchestratorError("FUTURES_CONTEXT_NOT_CHRONOLOGICALLY_UNIQUE")
        self.time_mapper.assert_valid(timestamps)
        if any(int(item.get("input_candles_count") or 0) != 5 for item in projection.get("candles") or []):
            raise ForecastOrchestratorError("FUTURES_5M_OBSERVATION_COVERAGE_INCOMPLETE")
        if candles[-1]["timestamp"] != datetime.fromisoformat(source.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat():
            raise ForecastOrchestratorError("FUTURES_SOURCE_CANDLE_MISMATCH")
        repair = projection.get("data_repair") or {}
        if require_live and repair.get("data_repair_status") != "READY":
            raise ForecastOrchestratorError(str(repair.get("data_repair_status") or "WAITING_FOR_DATA_REPAIR"))
        if require_live:
            now_session = self.time_mapper.calendar.status(self.clock())
            source_date = datetime.fromisoformat(source.replace("Z", "+00:00")).astimezone(self.time_mapper.calendar.TIMEZONE).date()
            if now_session.get("market_open") and source_date.isoformat() != now_session.get("session_date"):
                raise ForecastOrchestratorError("WAITING_FOR_COMPLETED_OPENING_5M_CANDLE")
        future = self.time_mapper.future_timestamps(source, steps=self.HORIZON, interval_minutes=5)
        self.time_mapper.assert_valid(future)
        identity = {"contract": contract, "security_id": security_id, "expiry": expiry, "exchange_segment": "NSE_FNO", "instrument_type": "FUTIDX"}
        canonical = json.dumps({"instrument": identity, "source": source, "timeframe": self.TIMEFRAME}, sort_keys=True, separators=(",", ":"))
        forecast_id = hashlib.sha256(canonical.encode()).hexdigest()
        return {
            "forecast_id": forecast_id,
            "forecast_revision": int(datetime.fromisoformat(source.replace("Z", "+00:00")).timestamp()),
            "instrument": identity,
            "timeframe": self.TIMEFRAME,
            "source_bar_timestamp": source,
            "future_timestamps": list(future),
            "candles": candles[-256:],
            "data_repair": deepcopy(repair),
            "input_context_hash": context_hash([
                {"time": int(datetime.fromisoformat(row["timestamp"]).timestamp()), **{field: row[field] for field in ("open", "high", "low", "close", "volume")}}
                for row in candles[-256:]
            ]),
        }

    def _base_snapshot(self, request: dict[str, Any], mode: str) -> dict[str, Any]:
        previous = self.projection()
        compatible = (previous.get("instrument") == request["instrument"] and previous.get("timeframe") == self.TIMEFRAME)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": "COMPUTING",
            "mode": mode,
            "forecast_id": request["forecast_id"],
            "forecast_revision": request["forecast_revision"],
            "generated_at": self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_bar_timestamp": request["source_bar_timestamp"],
            "future_timestamps": request["future_timestamps"],
            "timeframe": self.TIMEFRAME,
            "instrument": request["instrument"],
            "data_repair": deepcopy(request.get("data_repair") or {}),
            "context_bars": len(request["candles"]),
            "context_first_timestamp": request["candles"][0]["timestamp"],
            "context_last_timestamp": request["candles"][-1]["timestamp"],
            "input_context_hash": request["input_context_hash"],
            "chronos": deepcopy(previous.get("chronos")) if compatible else {"status": "PENDING"},
            "kronos": deepcopy(previous.get("kronos")) if compatible else {"status": "PENDING"},
            "tirex": deepcopy(previous.get("tirex")) if compatible else {"status": "PENDING", "state": "NEUTRAL"},
            "safety": {"advisory_only": True, "execution_influence": "ZERO", "live_trading_enabled": False, "broker_submission": False},
        }

    def _worker_request(self, name: str, request: dict[str, Any]) -> dict[str, Any]:
        if name == "kronos":
            return {
                "symbol": request["instrument"]["contract"], "source": "DHAN_FUTIDX_CANONICAL_CACHE",
                "candles": request["candles"], "minimum_context": self.MINIMUM_CONTEXT, "forecast_horizon": self.HORIZON,
                "sample_count": self.kronos_sample_count, "future_timestamps": request["future_timestamps"],
                "source_bar_timestamp": request["source_bar_timestamp"],
            }
        if name == "chronos":
            rows, mode, feature_names, coverage = build_model_rows(request["candles"])
            return {
                "symbol": request["instrument"]["contract"], "rows": rows,
                "feature_names": feature_names, "mode": mode, "input_coverage": coverage,
                "prediction_length": self.HORIZON, "future_timestamps": request["future_timestamps"],
                "source_bar_timestamp": request["source_bar_timestamp"],
            }
        return {
            "closes": [row["close"] for row in request["candles"]],
            "prediction_length": self.HORIZON,
            "source_bar_timestamp": request["source_bar_timestamp"],
        }

    def _normalize_result(self, name: str, result: Mapping[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        generated = self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if name == "kronos":
            path = validate_ohlc_path(result.get("representative_path") or [], self.HORIZON)
            ghost = [{"timestamp": request["future_timestamps"][index], **row} for index, row in enumerate(path)]
            return {
                "status": "READY", "model": result.get("model_name", "NeoQuasar/Kronos-small"),
                "model_revision": result.get("model_revision"), "device": result.get("device"),
                "source_bar_timestamp": request["source_bar_timestamp"], "generated_at": generated,
                "inference_duration_ms": result.get("inference_duration_ms"),
                "model_load_duration_ms": result.get("model_load_duration_ms"),
                "sample_count": result.get("sample_count"), "raw_path_count": result.get("raw_path_count"),
                "representative_path_id": result.get("representative_path_id"),
                "terminal_above_source_count": result.get("terminal_above_source_count"),
                "terminal_above_source_share": result.get("terminal_above_source_share"),
                "terminal_below_source_count": result.get("terminal_below_source_count"),
                "terminal_below_source_share": result.get("terminal_below_source_share"),
                "dispersion": result.get("terminal_dispersion"), "ghost_ohlc": ghost,
                "execution_influence": "ZERO", "not_probability": True,
            }
        if name == "chronos":
            rows = result.get("forecast_rows") or []
            if len(rows) != self.HORIZON:
                raise ForecastValidationError("CHRONOS_FORECAST_LENGTH_MISMATCH")
            normalized = []
            for index, row in enumerate(rows):
                values = [float(row[label]) for label in ("p10", "p50", "p90")]
                if values != sorted(values):
                    raise ForecastValidationError("CHRONOS_QUANTILE_ORDER_INVALID")
                normalized.append({"timestamp": request["future_timestamps"][index], "p10": values[0], "p50": values[1], "p90": values[2]})
            return {
                "status": "READY", "model": "amazon/chronos-2",
                "model_revision": "29ec3766d36d6f73f0696f85560a422f50e8498c",
                "device": result.get("device"), "source_bar_timestamp": request["source_bar_timestamp"],
                "generated_at": generated, "inference_duration_ms": result.get("inference_duration_ms"),
                "model_load_duration_ms": result.get("model_load_duration_ms"),
                "forecast_rows": normalized, "visible_quantiles": [0.1, 0.5, 0.9],
                "input_feature_names": list(result.get("input_feature_names") or []),
                "mode": result.get("mode"), "input_coverage": result.get("input_coverage"),
                "execution_influence": "ZERO", "not_probability": True,
            }
        quantiles = validate_quantile_matrix(result.get("quantiles"), quantile_count=9, horizon=self.HORIZON)
        classification = self._classifier.classify(quantiles, request["candles"][-1]["close"], [row["close"] for row in request["candles"][-64:]])
        if classification["state"] != self._last_tirex_state:
            self._state_transitions += 1
            self._last_tirex_state = classification["state"]
        return {
            "status": "READY", "model": result.get("model", "NX-AI/TiRex-2"),
            "model_revision": result.get("model_revision"), "package_version": result.get("package_version"),
            "device": result.get("device"), "dtype": result.get("dtype"),
            "source_bar_timestamp": request["source_bar_timestamp"], "generated_at": generated,
            "inference_duration_ms": result.get("inference_duration_ms"),
            "model_load_duration_ms": result.get("model_load_duration_ms"),
            "raw_shape": result.get("raw_shape"), "quantile_levels": result.get("quantile_levels"),
            "state": classification["state"], "raw_state": classification["raw_state"],
            "classifier_evidence": classification["evidence_score"],
            "classifier_uncertainty": classification["uncertainty_widths"],
            "classifier_formula": classification["formula_version"],
            "cadence": self.tirex_cadence, "execution_influence": "ZERO", "not_probability": True,
            "_raw_quantiles": quantiles,
        }

    def _publish(self, value: dict[str, Any]) -> None:
        immutable = deepcopy(value)
        with self._lock:
            if immutable.get("status") == "READY":
                revision = immutable.get("forecast_revision")
                entry = _forecast_history_entry(immutable)
                if self._forecast_history and self._forecast_history[-1].get("forecast_revision") == revision:
                    self._forecast_history[-1] = entry
                else:
                    self._forecast_history.append(entry)
            self._snapshot = immutable
            subscribers = tuple(self._subscribers)
        self._save(immutable)
        for callback in subscribers:
            try:
                callback(deepcopy(immutable))
            except Exception:
                pass

    def _load(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and value.get("schema_version") == self.SCHEMA_VERSION else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _save(self, value: dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
            os.replace(temporary, self.state_path)
        except (OSError, TypeError, ValueError):
            pass
    def _unavailable(self, reason: str, **details: Any) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION, "status": "UNAVAILABLE", "reason": reason,
            "mode": "PASSIVE", "forecast_id": None, "forecast_revision": None,
            "generated_at": self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_bar_timestamp": None, "future_timestamps": [], "timeframe": self.TIMEFRAME,
            "instrument": {}, "chronos": {"status": "UNAVAILABLE"}, "kronos": {"status": "UNAVAILABLE"},
            "tirex": {"status": "UNAVAILABLE", "state": "NEUTRAL"},
            "safety": {"advisory_only": True, "execution_influence": "ZERO", "live_trading_enabled": False, "broker_submission": False},
            **details,
        }


def _forecast_history_entry(value: Mapping[str, Any]) -> dict[str, Any]:
    kronos = value.get("kronos") or {}
    chronos = value.get("chronos") or {}
    tirex = value.get("tirex") or {}
    ghost = kronos.get("ghost_ohlc") or []
    quantiles = chronos.get("forecast_rows") or []
    return {
        "source_timestamp": value.get("source_bar_timestamp"),
        "context_hash": value.get("input_context_hash"),
        "forecast_revision": value.get("forecast_revision"),
        "kronos": {
            "representative_path_id": kronos.get("representative_path_id"),
            "ghost_ohlc_hash": hashlib.sha256(json.dumps(ghost, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20],
            "inference_latency_ms": kronos.get("inference_duration_ms"),
        },
        "chronos2": {
            "quantile_hash": hashlib.sha256(json.dumps(quantiles, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20],
            "inference_latency_ms": chronos.get("inference_duration_ms"),
        },
        "tirex2": {
            "state": tirex.get("state"),
            "inference_latency_ms": tirex.get("inference_duration_ms"),
        },
    }
