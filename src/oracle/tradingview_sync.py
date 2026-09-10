"""Backend-owned, metadata-only TradingView auto-sync for Oracle Phase 6A."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Condition, Event, RLock, Thread
from time import monotonic, perf_counter
from typing import Any, Callable, Mapping

from src.oracle.contracts.tradingview import (
    SYNC_POLICY_VERSION, TradingViewAvailability, TradingViewCaptureReference,
    TradingViewChartState, TradingViewFreshness, TradingViewInstrumentIdentity,
    TradingViewLayoutIdentity, TradingViewOptionIdentity, TradingViewRoute,
    TradingViewStateChangeEvent, TradingViewSymbolIdentity,
    TradingViewSyncProjection, seal,
)
from src.strategy_lab.storage import ImmutableStream, _atomic_write
from src.oracle.async_lanes import IdentityEpoch, CanonicalLiveState, AsyncLaneProcessor


_INDEXES = {"NIFTY", "BANKNIFTY", "SENSEX"}
_TIMEFRAMES = {"1": "1m", "3": "3m", "5": "5m", "15": "15m", "60": "1H", "240": "4H", "1D": "1D", "D": "1D"}
_CRYPTO_EXCHANGES = {"BINANCE", "COINBASE", "BYBIT", "BITSTAMP", "KRAKEN", "OKX"}
_OPTION_PATTERNS = (
    re.compile(r"^(?P<underlying>[A-Z][A-Z0-9-]*?)(?P<expiry>\d{6})(?P<strike>\d+(?:\.\d+)?)(?P<side>CE|PE)$"),
    re.compile(r"^(?P<underlying>[A-Z][A-Z0-9-]*?)(?P<expiry>\d{6})(?P<side>C|P)(?P<strike>\d+(?:\.\d+)?)$"),
    re.compile(r"^(?P<underlying>[A-Z][A-Z0-9-]*?)(?P<day>\d{2})(?P<month>[A-Z]{3})(?P<year>\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<side>CE|PE)$"),
)


class TradingViewSyncError(RuntimeError):
    pass


PERFORMANCE_STAGES = (
    "mcp_subprocess", "chart_state_parsing", "normalization_routing",
    "dhan_security_mapping", "htf_cache_binding", "refresh_5m", "refresh_3m",
    "refresh_1m", "exact_premium_candle_retrieval", "exact_premium_feature_retrieval",
    "argus_retrieval", "dashboard_snapshot_retrieval", "ose_retrieval", "vob_retrieval", "analysis_snapshot",
    "market_analyst", "option_candidate_comparison", "deterministic_analysis",
    "phase3_persistence", "exact_option_composition", "knowledge_retrieval",
    "similarity_calibration", "phase4_persistence", "evidence_bundle", "decision_envelope", "event_publication",
    "api_serialization",
)


class PerformanceTelemetry:
    """Bounded thread-safe stage telemetry; never participates in decisions."""

    def __init__(self, *, maximum_samples: int = 512):
        self.maximum_samples = max(16, int(maximum_samples))
        self._lock = RLock()
        self._samples = {stage: deque(maxlen=self.maximum_samples) for stage in PERFORMANCE_STAGES}
        self._errors = {stage: 0 for stage in PERFORMANCE_STAGES}

    def record(self, stage: str, duration_ms: float, *, error: bool = False) -> None:
        if stage not in self._samples:
            return
        try:
            value = max(0.0, float(duration_ms))
        except (TypeError, ValueError):
            value = 0.0
            error = True
        with self._lock:
            self._samples[stage].append(value)
            if error:
                self._errors[stage] += 1

    def snapshot(self) -> dict[str, dict[str, float | int | None]]:
        with self._lock:
            samples = {stage: list(values) for stage, values in self._samples.items()}
            errors = dict(self._errors)
        result = {}
        for stage in PERFORMANCE_STAGES:
            chronological = samples[stage]
            values = sorted(chronological)
            count = len(values)
            result[stage] = {
                "latest_ms": round(chronological[-1], 3) if chronological else None,
                "mean_ms": round(sum(values) / count, 3) if values else None,
                "p50_ms": round(values[max(0, (count + 1) // 2 - 1)], 3) if values else None,
                "p95_ms": round(values[max(0, (95 * count + 99) // 100 - 1)], 3) if values else None,
                "maximum_ms": round(max(values), 3) if values else None,
                "sample_count": count,
                "error_count": errors[stage],
            }
        return result


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _now(clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TradingViewSyncError("VERIFIED_TIME_UNAVAILABLE")
    return value.astimezone(timezone.utc)


def _expiry(match: re.Match[str]) -> str:
    groups = match.groupdict()
    if groups.get("expiry"):
        value = groups["expiry"]
        parsed = date(2000 + int(value[:2]), int(value[2:4]), int(value[4:6]))
    else:
        parsed = datetime.strptime(f"{groups['day']}{groups['month']}{groups['year']}", "%d%b%y").date()
    return parsed.isoformat()


def normalize_timeframe(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in _TIMEFRAMES:
        return _TIMEFRAMES[normalized]
    raise TradingViewSyncError(f"UNSUPPORTED_TRADINGVIEW_TIMEFRAME:{normalized or 'EMPTY'}")


def route_tradingview_symbol(
    raw_symbol: str,
    *,
    option_identity_resolver: Callable[[TradingViewOptionIdentity], str | None] | None = None,
) -> tuple[TradingViewSymbolIdentity, TradingViewInstrumentIdentity, TradingViewOptionIdentity | None]:
    raw = str(raw_symbol or "").strip().upper()
    if not raw:
        raise TradingViewSyncError("TRADINGVIEW_SYMBOL_IDENTITY_MISSING")
    exchange, display = (raw.split(":", 1) if ":" in raw else (None, raw))
    display = display.replace(" ", "")
    if not display or display in {"UNKNOWN", "UNDEFINED"}:
        raise TradingViewSyncError("TRADINGVIEW_SYMBOL_AMBIGUOUS")

    for pattern in _OPTION_PATTERNS:
        match = pattern.fullmatch(display)
        if not match:
            continue
        try:
            expiry = _expiry(match)
            strike = float(match.group("strike"))
        except (TypeError, ValueError):
            continue
        underlying = match.group("underlying")
        side = match.group("side")
        side = {"C": "CE", "P": "PE"}.get(side, side)
        supported_exchange = exchange in {"NSE", "BSE"}
        unresolved = TradingViewOptionIdentity(underlying=underlying, expiry=expiry, strike=strike,
                                               option_side=side, trading_symbol=display)
        try:
            security_id = str(option_identity_resolver(unresolved)) if option_identity_resolver else ""
        except Exception:
            security_id = ""
        mapped = bool(security_id)
        route = TradingViewRoute.EXACT_OPTION if supported_exchange and mapped else TradingViewRoute.UNSUPPORTED
        symbol = TradingViewSymbolIdentity(raw_symbol=raw, normalized_symbol=display, exchange=exchange,
                                           route=route, ambiguity_status="RESOLVED" if mapped else
                                           "EXACT_SECURITY_MAPPING_UNAVAILABLE")
        instrument = TradingViewInstrumentIdentity(route=route, instrument_id=security_id or None,
            security_id=security_id or None, underlying=underlying,
            analysis_supported=supported_exchange and mapped and underlying == "NIFTY",
            mapping_status="AUTHORITATIVE_DHAN_MAPPING" if mapped else "EXACT_SECURITY_MAPPING_UNAVAILABLE")
        option = TradingViewOptionIdentity(underlying=underlying, expiry=expiry, strike=strike,
                                           option_side=side, trading_symbol=display, security_id=security_id or None)
        return symbol, instrument, option

    if re.search(r"\d(?:CE|PE)$", display):
        raise TradingViewSyncError("UNSUPPORTED_OPTION_FORMAT")
    if display.endswith("!") or re.search(r"(?:FUT|FUTURES)$", display):
        route = TradingViewRoute.FUTURE
        supported = False
        underlying = display.rstrip("!0123456789") or display
    elif exchange in _CRYPTO_EXCHANGES or display.endswith(("USDT", "USD.P", "USD")) and exchange not in {"NSE", "BSE"}:
        route = TradingViewRoute.CRYPTO
        supported = False
        underlying = display
    elif exchange not in {"NSE", "BSE"}:
        route = TradingViewRoute.AMBIGUOUS if exchange is None else TradingViewRoute.UNSUPPORTED
        supported = False
        underlying = display
    elif display in _INDEXES:
        route = TradingViewRoute.UNDERLYING_INDEX
        supported = display == "NIFTY"
        underlying = display
    elif re.fullmatch(r"[A-Z][A-Z0-9&-]{1,30}", display):
        route = TradingViewRoute.UNDERLYING_STOCK
        supported = False
        underlying = display
    else:
        route = TradingViewRoute.UNSUPPORTED
        supported = False
        underlying = display
    availability = "RESOLVED" if route not in {TradingViewRoute.AMBIGUOUS, TradingViewRoute.UNSUPPORTED} else route.value
    return (
        TradingViewSymbolIdentity(raw_symbol=raw, normalized_symbol=display, exchange=exchange, route=route,
                                  ambiguity_status=availability),
        TradingViewInstrumentIdentity(route=route, instrument_id=None, security_id=None, underlying=underlying,
            analysis_supported=supported, mapping_status="CANONICAL_ANALYSIS_AVAILABLE" if supported else "DETECTION_ONLY"),
        None,
    )


class TradingViewMCPReader:
    """Bounded read-only adapter over the audited local TradingView MCP Server via persistent JSON-RPC."""

    def __init__(self, root: str | Path = "/Users/ayushmudgal/tradingview-mcp", *, timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.timeout_seconds = max(0.2, float(timeout_seconds))
        self.server_js = self.root / "src" / "server.js"
        configured = os.environ.get("CITADEL_TRADINGVIEW_NODE")
        candidates = (configured, shutil.which("node"), "/usr/local/bin/node", "/opt/homebrew/bin/node")
        self.node_binary = next((str(item) for item in candidates if item and Path(str(item)).is_file()), None)
        self._process = None
        self._req_id = 1

    def _start_process(self):
        if not self.server_js.is_file():
            raise TradingViewSyncError("TRADINGVIEW_MCP_SERVER_UNAVAILABLE")
        if not self.node_binary:
            raise TradingViewSyncError("TRADINGVIEW_MCP_NODE_RUNTIME_UNAVAILABLE")

        import subprocess
        self._process = subprocess.Popen(
            [self.node_binary, str(self.server_js)],
            cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=False, bufsize=0, env={**os.environ, "NO_COLOR": "1"}
        )
        self._buffer = ""

        try:
            # Initialize sequence
            init_req = {"jsonrpc": "2.0", "id": self._req_id, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "citadel", "version": "1.0.0"}}}
            self._req_id += 1
            self._process.stdin.write((json.dumps(init_req) + "\n").encode('utf-8'))
            
            # We must read the init response before sending initialized
            import select, time
            deadline = time.time() + self.timeout_seconds
            buf = ""
            init_res = None
            while not init_res:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TradingViewSyncError("TRADINGVIEW_MCP_TIMEOUT")
                ready, _, _ = select.select([self._process.stdout], [], [], remaining)
                if not ready:
                    raise TradingViewSyncError("TRADINGVIEW_MCP_TIMEOUT")
                chunk = os.read(self._process.stdout.fileno(), 4096)
                if not chunk:
                    raise TradingViewSyncError("TRADINGVIEW_MCP_EOF")
                buf += chunk.decode('utf-8', errors='replace')
                if "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        init_res = line
                        
            self._buffer = buf # Save leftover for read()

            init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._process.stdin.write((json.dumps(init_notif) + "\n").encode('utf-8'))
        except Exception as error:
            if self._process:
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except Exception:
                    pass
                self._process = None
            if isinstance(error, TradingViewSyncError):
                raise
            raise TradingViewSyncError("TRADINGVIEW_MCP_INITIALIZATION_FAILED") from error

    def read(self) -> Mapping[str, Any]:
        if not self._process or self._process.poll() is not None:
            self._start_process()

        import time, select
        expected_id = self._req_id
        req = {"jsonrpc": "2.0", "id": expected_id, "method": "tools/call", "params": {"name": "pane_list", "arguments": {}}}
        self._req_id += 1

        try:
            self._process.stdin.write((json.dumps(req) + "\n").encode('utf-8'))
            self._process.stdin.flush()

            deadline = time.time() + self.timeout_seconds
            res = None
            if not hasattr(self, '_buffer'):
                self._buffer = ""

            while True:
                if "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                else:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise TradingViewSyncError("TRADINGVIEW_MCP_TIMEOUT")
                    
                    ready, _, _ = select.select([self._process.stdout], [], [], remaining)
                    if not ready:
                        raise TradingViewSyncError("TRADINGVIEW_MCP_TIMEOUT")
                    
                    chunk = os.read(self._process.stdout.fileno(), 4096)
                    if not chunk:
                        raise TradingViewSyncError("TRADINGVIEW_MCP_EOF")
                    
                    self._buffer += chunk.decode('utf-8', errors='replace')
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if parsed.get("id") == expected_id:
                    res = parsed
                    break

            if "error" in res:
                raise TradingViewSyncError(f"TRADINGVIEW_MCP_RPC_ERROR:{res['error']}")

            content = res.get("result", {}).get("content", [{}])[0].get("text", "{}")
            value = json.loads(content)
        except Exception as error:
            if self._process:
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except Exception:
                    pass
                self._process = None
            if isinstance(error, TradingViewSyncError):
                raise
            raise TradingViewSyncError("TRADINGVIEW_MCP_RESPONSE_INVALID") from error

        if not value.get("success"):
            raise TradingViewSyncError("TRADINGVIEW_MCP_READ_FAILED")
        return value

    def close(self):
        """Terminate child process on shutdown."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                pass
            self._process = None


class TradingViewAutoSyncService:
    """Poll, deduplicate, analyse only changed identity, and publish one projection."""

    SAFETY = {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
              "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False}

    def __init__(self, root: str | Path, *, reader=None, analysis_provider: Callable[[Any], Mapping[str, Any]] | None = None,
                 decision_observer: Callable[[Mapping[str, Any]], Any] | None = None,
                 phase5_provider: Callable[[], Mapping[str, Any]] | None = None,
                 personal_oracle_provider: Callable[[], Mapping[str, Any]] | None = None,
                 second_brain_provider: Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
                 dependency_state_provider: Callable[[], Mapping[str, Any]] | None = None,
                 option_identity_resolver: Callable[[TradingViewOptionIdentity], str | None] | None = None,
                 fast_path_provider: Callable[[dict, dict], dict] | None = None,
                 telemetry: PerformanceTelemetry | None = None,
                 clock=None, poll_seconds: float = 0.1, debounce_seconds: float = 0.1,
                 stale_seconds: float = 5.0):
        self.root = Path(root)
        self.reader = reader or TradingViewMCPReader()
        self.analysis_provider = analysis_provider
        self.decision_observer = decision_observer
        self.phase5_provider = phase5_provider or (lambda: {})
        self.personal_oracle_provider = personal_oracle_provider or (lambda: {})
        self.second_brain_provider = second_brain_provider or (lambda decision, knowledge, context: {})
        self.dependency_state_provider = dependency_state_provider or (lambda: {})
        self.option_identity_resolver = option_identity_resolver
        self.fast_path_provider = fast_path_provider
        self.telemetry = telemetry or PerformanceTelemetry()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        self.stale_seconds = max(self.poll_seconds, float(stale_seconds))
        self.checkpoint_path = self.root / "checkpoint.json"
        self.events = ImmutableStream(self.root / "events.jsonl", max_bytes=50 * 1024 * 1024, max_files=1)
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._event_condition = Condition(RLock())
        self._live_events: deque[dict[str, Any]] = deque(maxlen=256)
        self._live_sequence = 0
        self._boot_id = _hash({"root": str(self.root), "started": _now(self.clock).isoformat()})[:12]
        self._last_chart: TradingViewChartState | None = None
        self._projection: dict[str, Any] = self._initial_projection()
        self._projection_record: TradingViewSyncProjection | None = None
        self._candidate: tuple[str, Mapping[str, Any], float] | None = None
        self._last_dependency_hash: str | None = None
        self._last_phase5_hash: str | None = None
        self._retry_count = 0
        self._retry_at = 0.0
        self._stats = {"polls": 0, "changes": 0, "duplicates": 0, "analysis_runs": 0,
                       "context_cache_hits": 0, "context_cache_misses": 0,
                       "last_state_read_ms": None, "last_analysis_ms": None,
                       "last_success_at": None, "last_error": None, "restart_recovered": False}
        self.canonical_state = CanonicalLiveState()
        self.canonical_state.observers.append(self._on_canonical_state)
        self.fast_lane = AsyncLaneProcessor("fast", self._process_fast_lane, self.canonical_state.update_fast)
        self.slow_lane = AsyncLaneProcessor("slow", self._process_slow_lane, self.canonical_state.update_slow)
        self._epoch_counter = 0
        self._restore()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.fast_lane.start()
            self.slow_lane.start()
            self._thread = Thread(target=self._run, name="oracle-tradingview-auto-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.fast_lane.stop()
        self.slow_lane.stop()
        thread = self._thread
        if thread:
            thread.join(timeout=4.0)

    def poll_once(self, *, force_debounce: bool = False, wait_for_lanes: bool = False) -> dict[str, Any]:
        started = perf_counter()
        now = _now(self.clock)
        self._stats["polls"] += 1
        if monotonic() < self._retry_at:
            return self.projection()
        try:
            mcp_started = perf_counter()
            try:
                raw = self.reader.read()
            except Exception:
                self.telemetry.record("mcp_subprocess", (perf_counter() - mcp_started) * 1000, error=True)
                raise
            mcp_duration = (perf_counter() - mcp_started) * 1000
            self.telemetry.record("mcp_subprocess", mcp_duration)
            self._stats["last_state_read_ms"] = round(mcp_duration, 3)
            self._stats["last_success_at"] = now.isoformat()
            self._stats["last_error"] = None
            self._retry_count = 0
            self._retry_at = 0.0
            parsing_started = perf_counter()
            candidate_hash = self._identity_hash(raw)
            self.telemetry.record("chart_state_parsing", (perf_counter() - parsing_started) * 1000)
            dependency_hash = self._dependency_hash()
            phase5 = dict(self.phase5_provider())
            phase5_hash = _hash(phase5)
            same_identity = self._last_chart and self._identity_hash(self._last_chart.to_dict()) == candidate_hash
            recovered = self._projection.get("sync_state") in {"UNAVAILABLE", "DETECTING"}
            if same_identity and not recovered:
                if self._last_phase5_hash is not None and phase5_hash != self._last_phase5_hash:
                    self._candidate = None
                    return self._publish_control_update(now, phase5, phase5_hash)
                if self._last_dependency_hash is None or dependency_hash == self._last_dependency_hash:
                    self._stats["duplicates"] += 1
                    self._candidate = None
                    return self.projection()
            if not force_debounce:
                if self._candidate is None or self._candidate[0] != candidate_hash:
                    self._candidate = (candidate_hash, raw, monotonic())
                    return self.projection()
                if monotonic() - self._candidate[2] < self.debounce_seconds:
                    return self.projection()
                raw = self._candidate[1]
            self._candidate = None
            reason = "CANONICAL_EVIDENCE_CHANGED" if same_identity and dependency_hash != self._last_dependency_hash else None
            res = self._accept(raw, now, reason_override=reason, phase5=phase5,
                                dependency_hash=dependency_hash, phase5_hash=phase5_hash)
            if force_debounce or wait_for_lanes:
                if not self.fast_lane._thread.is_alive():
                    self.fast_lane.execute_all_pending()
                else:
                    self.fast_lane.wait_until_idle(timeout=5.0)

                if not self.slow_lane._thread.is_alive():
                    self.slow_lane.execute_all_pending()
                else:
                    self.slow_lane.wait_until_idle(timeout=5.0)
                res = self.projection()
            return res
        except Exception as error:
            self._retry_count += 1
            self._retry_at = monotonic() + min(30.0, 0.5 * (2 ** min(self._retry_count - 1, 6)))
            self._stats["last_error"] = f"{type(error).__name__}:{error}"
            return self._unavailable(now, str(error))

    def projection(self) -> dict[str, Any]:
        with self._lock:
            value = json.loads(json.dumps(self._projection, default=str))
        value["health"] = {**value.get("health", {}), **self.health()}
        return value

    def health(self) -> dict[str, Any]:
        with self._lock:
            last = self._stats.get("last_success_at")
            age = None
            if last:
                age = max(0.0, (_now(self.clock) - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds())
            return {**self._stats, "worker_alive": bool(self._thread and self._thread.is_alive()),
                    "poll_interval_ms": round(self.poll_seconds * 1000), "state_age_seconds": age,
                    "backoff_active": monotonic() < self._retry_at, "retry_count": self._retry_count,
                    "backend_owned": True, "browser_page_required": False, "llm_required": False,
                    "policy_version": SYNC_POLICY_VERSION,
                    "push_transport": "SSE_PRIMARY_POLLING_FALLBACK",
                    "telemetry": self.telemetry.snapshot()}

    def event_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.events.read()[-max(1, min(int(limit), 500)):]

    def live_events_since(self, after_event_id: str | None = None) -> list[dict[str, Any]]:
        """Return ordered replay events; an unknown prior boot receives latest state."""
        with self._event_condition:
            values = list(self._live_events)
        if not values:
            return []
        if not after_event_id:
            return [values[-1]]
        index = next((i for i, row in enumerate(values) if row["event_id"] == after_event_id), None)
        return values[index + 1:] if index is not None else [values[-1]]

    def wait_for_live_events(self, after_event_id: str | None, timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
        with self._event_condition:
            values = self.live_events_since(after_event_id)
            if values:
                return values
            self._event_condition.wait(timeout=max(0.05, float(timeout_seconds)))
            return self.live_events_since(after_event_id)

    def _publish_live_event(self, event_type: str, projection: Mapping[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        with self._event_condition:
            self._live_sequence += 1
            event = {
                "event_id": f"oracle-live-{self._boot_id}-{self._live_sequence}",
                "event_type": event_type,
                "published_at": _now(self.clock).isoformat(),
                "state_hash": str(projection.get("content_hash") or ""),
                "projection": json.loads(json.dumps(projection, default=str)),
            }
            self._live_events.append(event)
            self._event_condition.notify_all()
        self.telemetry.record("event_publication", (perf_counter() - started) * 1000)
        return event

    def _accept(self, raw: Mapping[str, Any], now: datetime, *, reason_override: str | None = None,
                phase5: Mapping[str, Any] | None = None, dependency_hash: str | None = None,
                phase5_hash: str | None = None) -> dict[str, Any]:
        pane_index = raw.get("active_index")
        panes = raw.get("panes") if isinstance(raw.get("panes"), list) else []
        pane = next((row for row in panes if row.get("index") == pane_index), panes[0] if panes else {})
        normalization_started = perf_counter()
        symbol, instrument, option = route_tradingview_symbol(
            str(pane.get("symbol") or ""), option_identity_resolver=self.option_identity_resolver,
        )
        timeframe = normalize_timeframe(pane.get("resolution"))
        self.telemetry.record("normalization_routing", (perf_counter() - normalization_started) * 1000)
        previous_hash = self._last_chart.content_hash if self._last_chart else None
        reason = reason_override or self._change_reason(symbol.raw_symbol, timeframe, str(raw.get("layout")))
        seed = _hash({"symbol": symbol.raw_symbol, "timeframe": timeframe, "layout": raw.get("layout"), "pane": pane_index})[:24]
        event_seed = _hash({"identity": seed, "previous": previous_hash, "received": now.isoformat()})[:24]
        chart = seal(TradingViewChartState(
            event_id=f"tvstate_{event_seed}", correlation_id=f"oracle-sync-{event_seed}", source_timestamp=now.isoformat(),
            received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
            provenance={"source": "tradingview-mcp", "mode": "METADATA_ONLY", "market_data_used": False,
                        "mcp_repository": "/Users/ayushmudgal/tradingview-mcp", "policy": SYNC_POLICY_VERSION},
            symbol=symbol, instrument=instrument, option=option,
            layout=TradingViewLayoutIdentity(session_identity="TRADINGVIEW_DESKTOP_LOCAL",
                browser_identity="CDP_127.0.0.1_9222", chart_identity=f"pane-{pane_index if pane_index is not None else 0}",
                layout_identity=str(raw.get("layout") or "unknown"), active_pane_index=pane_index,
                chart_count=max(1, int(raw.get("chart_count") or len(panes) or 1))),
            timeframe=timeframe, chart_state_version=seed, availability=TradingViewAvailability.AVAILABLE,
            freshness=TradingViewFreshness.FRESH, previous_state_hash=previous_hash, change_reason=reason,
        ))
        event = seal(TradingViewStateChangeEvent(
            event_id=f"tvevent_{event_seed}", correlation_id=chart.correlation_id, source_timestamp=now.isoformat(),
            received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
            provenance={"source": "TradingViewAutoSyncService", "polling": True, "deduplicated": True},
            chart_state_hash=chart.content_hash, previous_state_hash=previous_hash, change_reason=reason,
            deduplication_key=f"tradingview:{event_seed}",
        ))
        self.events.append("TRADINGVIEW_STATE_CHANGED", event.to_dict(), recorded_at=now.isoformat(), idempotency_key=event.deduplication_key)
        self._publish_intermediate(chart, now, reason)
        self._epoch_counter += 1
        epoch_id = self._epoch_counter

        with self._lock:
            self._last_chart = chart

        payload = {
            "chart": chart,
            "now": now,
            "reason": reason,
            "dependency_hash": dependency_hash,
            "phase5_hash": phase5_hash,
            "event_seed": event_seed,
            "symbol": symbol
        }

        import time
        epoch = IdentityEpoch(
            identity_epoch=epoch_id,
            input_version=1,
            output_version=1,
            source_ts=now.timestamp(),
            gateway_received_ts=time.time(),
            calculated_at=time.time(),
            payload=payload
        )

        self.fast_lane.enqueue(epoch)
        self.slow_lane.enqueue(epoch)

        return self.projection()

    def _publish_intermediate(self, chart: TradingViewChartState, now: datetime, reason: str) -> None:
        value = seal(TradingViewSyncProjection(
            event_id=f"loading_{chart.chart_state_version}", correlation_id=chart.correlation_id,
            source_timestamp=now.isoformat(), received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
            provenance={"service": "TradingViewAutoSyncService", "transition": "LOADING_CONTEXT"},
            sync_state="LOADING_CONTEXT", chart_state=chart,
            decision=self._unavailable_decision("FRESH_ANALYSIS_PENDING"), knowledge={}, phase5=dict(self.phase5_provider()),
            personal_oracle=self._personal_projection(self._second_brain_projection(
                self._unavailable_decision("FRESH_ANALYSIS_PENDING"), {}, chart,
            )), health=self.health(), safety=self.SAFETY,
            alert_event=None,
        ))
        with self._lock:
            self._projection_record = value
            self._projection = value.to_dict()
        chart_event = "chart_detected" if reason == "INITIAL_CHART_DETECTED" else "chart_changed"
        self._publish_live_event(chart_event, self.projection())
        self._publish_live_event("context_loading", self.projection())

    def _unavailable(self, now: datetime, reason: str) -> dict[str, Any]:
        chart = None
        if self._last_chart:
            chart = seal(replace(self._last_chart, event_id=f"stale_{self._last_chart.chart_state_version}",
                received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
                availability=TradingViewAvailability.UNAVAILABLE, freshness=TradingViewFreshness.STALE,
                change_reason="MCP_DISCONNECTED", content_hash=""))
        seed = _hash({"reason": reason, "last": chart.content_hash if chart else None})[:24]
        alert = {"event_id": f"alert_{seed}", "event_type": "TRADINGVIEW_DISCONNECTED", "severity": "CRITICAL",
                 "message": "TradingView/MCP unavailable; Oracle decisions are non-actionable.",
                 "deduplication_key": f"TRADINGVIEW_DISCONNECTED:{seed}", "cooldown_seconds": 30,
                 "generated_at": now.isoformat()}
        projection = seal(TradingViewSyncProjection(
            event_id=f"unavailable_{seed}", correlation_id=f"oracle-sync-{seed}", source_timestamp=now.isoformat(),
            received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
            provenance={"service": "TradingViewAutoSyncService", "fail_closed": True},
            sync_state="UNAVAILABLE", chart_state=chart, decision=self._unavailable_decision(reason), knowledge={},
            phase5=dict(self.phase5_provider()), personal_oracle=self._personal_projection(
                self._second_brain_projection(self._unavailable_decision(reason), {}, chart)
            ), health=self.health(),
            safety=self.SAFETY, alert_event=alert,
        ))
        with self._lock:
            previous_alert = self._projection.get("alert_event") or {}
            self._projection_record = projection
            self._projection = projection.to_dict()
        if previous_alert.get("deduplication_key") != alert["deduplication_key"]:
            self.events.append("ORACLE_ALERT", alert, recorded_at=now.isoformat(), idempotency_key=alert["deduplication_key"])
        self._publish_live_event("stale_disconnect", self.projection())
        return self.projection()

    def _initial_projection(self) -> dict[str, Any]:
        now = _now(self.clock).isoformat()
        return seal(TradingViewSyncProjection(
            event_id="tradingview-detecting", correlation_id="oracle-sync-startup", source_timestamp=now,
            received_timestamp=now, generated_timestamp=now, provenance={"service": "TradingViewAutoSyncService"},
            sync_state="DETECTING", chart_state=None, decision=self._unavailable_decision("CHART_STATE_NOT_ACQUIRED"),
            knowledge={}, phase5={}, personal_oracle=self._personal_projection(
                self._second_brain_projection(self._unavailable_decision("CHART_STATE_NOT_ACQUIRED"), {}, None)
            ), health={}, safety=self.SAFETY,
        )).to_dict()

    def _restore(self) -> None:
        try:
            raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            projection = raw.get("projection")
            if isinstance(projection, dict):
                projection["sync_state"] = "DETECTING"
                projection["decision"] = self._unavailable_decision("RESTART_REACQUISITION_REQUIRED")
                projection["alert_event"] = None
                self._projection = projection
                self._stats["restart_recovered"] = True
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_seconds)

    def _dependency_hash(self) -> str:
        try:
            value = dict(self.dependency_state_provider())
        except Exception as error:
            value = {"status": "UNAVAILABLE", "error": f"{type(error).__name__}:{error}"}
        return _hash(value)

    def _publish_control_update(self, now: datetime, phase5: Mapping[str, Any], phase5_hash: str) -> dict[str, Any]:
        current = self._projection_record
        if current is None or current.chart_state is None:
            self._last_phase5_hash = phase5_hash
            return self.projection()
        base_state = self._center_state(current.decision, current.chart_state)
        state = self._phase5_state(base_state, phase5)
        alert = self._alert("PHASE5_STATE_CHANGED", state, current.chart_state, current.decision, phase5)
        seed = _hash({"phase5": phase5_hash, "previous": current.content_hash})[:24]
        updated = seal(replace(
            current, event_id=f"tvcontrol_{seed}", received_timestamp=now.isoformat(),
            generated_timestamp=now.isoformat(), sync_state=state, phase5=dict(phase5),
            health=self.health(), alert_event=alert, content_hash="",
        ))
        with self._lock:
            self._projection_record = updated
            self._projection = updated.to_dict()
            self._last_phase5_hash = phase5_hash
            _atomic_write(self.checkpoint_path, {"projection": self._projection,
                "chart_identity_hash": self._identity_hash(current.chart_state.to_dict()),
                "saved_at": now.isoformat(), "policy_version": SYNC_POLICY_VERSION})
        self.events.append("ORACLE_CONTROL_PROJECTION_CHANGED", {
            "event_id": updated.event_id, "phase5": dict(phase5), "projection_hash": updated.content_hash,
            "analysis_rerun": False, "execution_influence": "ZERO",
        }, recorded_at=now.isoformat(), idempotency_key=f"oracle-control:{seed}")
        self.events.append("ORACLE_ALERT", alert, recorded_at=now.isoformat(), idempotency_key=alert["deduplication_key"])
        condition_state = str(phase5.get("condition_state") or "").upper()
        event_type = ("paper_order_updated" if phase5.get("paper_order_state") else
                      "guardian_updated" if phase5.get("guardian_action") else
                      "condition_updated" if condition_state else "decision_updated")
        self._publish_live_event(event_type, self.projection())
        return self.projection()

    @staticmethod
    def _identity_hash(value: Mapping[str, Any]) -> str:
        if "chart_count" in value:
            panes = value.get("panes") or []
            active = value.get("active_index")
            pane = next((row for row in panes if row.get("index") == active), panes[0] if panes else {})
            try:
                resolution = normalize_timeframe(pane.get("resolution"))
            except TradingViewSyncError:
                resolution = pane.get("resolution")
            identity = {"symbol": pane.get("symbol"), "resolution": resolution,
                        "layout": value.get("layout"), "active_index": active, "chart_count": value.get("chart_count")}
        else:
            symbol = value.get("symbol") or {}
            layout = value.get("layout") or {}
            identity = {"symbol": symbol.get("raw_symbol"), "resolution": value.get("timeframe"),
                        "layout": layout.get("layout_identity"), "active_index": layout.get("active_pane_index"),
                        "chart_count": layout.get("chart_count")}
        return _hash(identity)

    def _change_reason(self, symbol: str, timeframe: str, layout: str) -> str:
        if not self._last_chart:
            return "INITIAL_CHART_DETECTED"
        if self._last_chart.symbol.raw_symbol != symbol:
            return "SYMBOL_CHANGED"
        if self._last_chart.timeframe != timeframe:
            return "TIMEFRAME_CHANGED"
        if self._last_chart.layout.layout_identity != layout:
            return "LAYOUT_CHANGED"
        return "ACTIVE_PANE_CHANGED"

    @staticmethod
    def _unavailable_decision(reason: str) -> dict[str, Any]:
        return {"decision_id": None, "content_hash": None, "action": "UNAVAILABLE", "exact_contract": None,
                "displayed_option": None, "current_contract_accepted": False,
                "current_contract_rejected": False, "current_contract_reason": reason,
                "better_option_found": False,
                "setup_quality": None, "visual_certainty": "UNAVAILABLE", "data_completeness": 0,
                "execution_quality": 0, "evidence_agreement": 0, "calibration_status": "NOT_AVAILABLE",
                "historical_probability": None, "trigger": "NOT REPORTED", "entry_band": None,
                "structural_invalidation": None, "premium_stop": None, "targets": [], "costs": None,
                "resulting_rr": [], "why": reason, "risk_conflict": reason, "freshness": "UNAVAILABLE",
                "missing_evidence": [reason], "execution_authority": False}

    @staticmethod
    def _center_state(decision: Mapping[str, Any], chart: TradingViewChartState) -> str:
        if chart.symbol.route is TradingViewRoute.AMBIGUOUS:
            return "AMBIGUOUS"
        action = str(decision.get("action") or "UNAVAILABLE").upper()
        return action if action in {"BUY", "WAIT", "NO_TRADE"} else "UNAVAILABLE"

    @staticmethod
    def _phase5_state(default: str, phase5: Mapping[str, Any]) -> str:
        state = str(phase5.get("condition_state") or "").upper()
        return {"WATCHING": "WATCHING", "TRIGGERED": "REVALIDATING", "REVALIDATING": "REVALIDATING",
                "RISK_APPROVED": "PAPER_ORDER", "ORDER_SUBMITTED": "PAPER_ORDER", "PARTIALLY_FILLED": "PAPER_ORDER",
                "FILLED": "MANAGE", "MANAGING": "MANAGE", "EXITED": "EXITED"}.get(state, default)

    def _second_brain_projection(self, decision: Mapping[str, Any], knowledge: Mapping[str, Any],
                                 chart: TradingViewChartState | None) -> dict[str, Any]:
        context = {"symbol": chart.instrument.underlying if chart else None,
                   "timeframe": chart.timeframe if chart else None}
        try:
            return dict(self.second_brain_provider(decision, knowledge, context))
        except Exception:
            return {"status": "UNAVAILABLE", "constitution": {}, "discipline": {},
                    "explainability": {"why": ["Second-brain projection unavailable."],
                                       "why_not": ["Advisory memory cannot be used while unavailable."]},
                    "safety": dict(self.SAFETY)}

    def _personal_projection(self, second_brain: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            raw = dict(self.personal_oracle_provider())
        except Exception:
            raw = {}
        projected_brain = dict(second_brain or raw.get("second_brain") or {})
        return {"available": bool(raw) or bool(projected_brain), "user_override_count": raw.get("user_override_count"),
                "cooldown_status": ((projected_brain.get("discipline") or {}).get("recommendation")
                                    or raw.get("cooldown_status", "NOT_EVALUATED")),
                "trades_today": raw.get("trades_today"), "duplicate_thesis": raw.get("duplicate_thesis"),
                "missed_opportunity_review_reference": raw.get("missed_opportunity_review_reference"),
                "obsidian_sync_status": ((projected_brain.get("obsidian") or {}).get("status")
                                         or raw.get("obsidian_sync_status", "NO_COMPLETED_TRADE_SYNC")),
                "second_brain": projected_brain, "read_only": True}

    @staticmethod
    def _alert(reason: str, state: str, chart: TradingViewChartState, decision: Mapping[str, Any],
               phase5: Mapping[str, Any], second_brain: Mapping[str, Any] | None = None) -> dict[str, Any]:
        condition_state = str(phase5.get("condition_state") or "").upper()
        event_type = {
            "INITIAL_CHART_DETECTED": "CHART_DETECTED", "SYMBOL_CHANGED": "CHART_DETECTED",
            "TIMEFRAME_CHANGED": "TIMEFRAME_DETECTED", "LAYOUT_CHANGED": "LAYOUT_CHANGED",
        }.get(reason, "ORACLE_STATE_CHANGED")
        severity = "CRITICAL" if state in {"BUY", "REVALIDATING", "PAPER_ORDER", "MANAGE", "EXIT"} else "INFO"
        if state == "BUY": event_type = "BUY_READY"
        elif condition_state == "WATCHING": event_type = "CONDITION_WATCHING"
        elif condition_state == "TRIGGERED": event_type = "CONDITION_TRIGGERED"
        elif condition_state == "REVALIDATING": event_type = "CONDITION_REVALIDATING"
        elif state == "PAPER_ORDER": event_type = "PAPER_ORDER_STATE"
        elif state == "MANAGE": event_type = "GUARDIAN_MANAGE"
        elif state == "EXITED": event_type = "GUARDIAN_EXIT"
        order_state = str(phase5.get("paper_order_state") or "").upper()
        if order_state in {"SUBMITTED", "PARTIALLY_FILLED", "FILLED", "REJECTED"}:
            event_type = f"PAPER_ORDER_{order_state}"
        elif str(phase5.get("guardian_action") or "").upper() == "EXIT":
            event_type = "GUARDIAN_EXIT"
        elif decision.get("current_contract_rejected") and decision.get("better_option_found"):
            event_type = "BETTER_OPTION_FOUND"
        elif decision.get("current_contract_rejected"):
            event_type = "CURRENT_OPTION_REJECTED"
        else:
            evidence_text = " ".join(str(item).upper() for item in (
                list(decision.get("missing_evidence") or ()) + list(decision.get("reason_codes") or ())
            ))
            if "SPREAD" in evidence_text or "LIQUIDITY" in evidence_text:
                event_type = "SPREAD_LIQUIDITY_DETERIORATED"
            elif any(authority in evidence_text for authority in ("ARGUS", "OSE", "VOB")) and any(
                    marker in evidence_text for marker in ("CONFLICT", "NON_CONFIRMATION", "REVERSAL", "STALE")):
                event_type = "AUTHORITY_CONFIRMATION_LOST"
            elif "INVALIDAT" in evidence_text:
                event_type = "SETUP_INVALIDATED"
            elif state == "WAIT" and "TRIGGER" in evidence_text:
                event_type = "WAIT_CONDITION_TRIGGERED"
        discipline = dict((second_brain or {}).get("discipline") or {})
        recommendation = str(discipline.get("recommendation") or "").upper()
        if event_type == "ORACLE_STATE_CHANGED" and recommendation in {"REVIEW", "COOLDOWN"}:
            event_type = f"DISCIPLINE_{recommendation}"
        if event_type in {"BUY_READY", "SETUP_INVALIDATED", "BETTER_OPTION_FOUND",
                          "SPREAD_LIQUIDITY_DETERIORATED", "AUTHORITY_CONFIRMATION_LOST",
                          "CONDITION_TRIGGERED", "CONDITION_REVALIDATING", "PAPER_ORDER_REJECTED",
                          "GUARDIAN_EXIT"}:
            severity = "CRITICAL"
        seed = _hash({"event": event_type, "chart": chart.content_hash, "decision": decision.get("content_hash"),
                      "phase5": phase5.get("latest_event_hash"), "discipline": recommendation})[:24]
        return {"event_id": f"alert_{seed}", "event_type": event_type, "severity": severity,
                "message": f"{chart.symbol.normalized_symbol} {chart.timeframe} · {state}",
                "deduplication_key": f"{event_type}:{seed}", "cooldown_seconds": 15,
                "generated_at": chart.generated_timestamp}

    def _process_fast_lane(self, payload: Any) -> Any:
        phase5 = dict(self.phase5_provider())
        return {
            "phase5": phase5,
            "chart": payload["chart"],
            "now": payload["now"],
            "reason": payload["reason"],
            "dependency_hash": payload["dependency_hash"],
            "phase5_hash": payload["phase5_hash"],
            "event_seed": payload["event_seed"]
        }

    def _process_slow_lane(self, payload: Any) -> Any:
        chart = payload["chart"]
        analysis_started = perf_counter()
        analysis_attempted = False
        analysis_error = False

        if chart.instrument.analysis_supported and self.analysis_provider:
            analysis_attempted = True
            try:
                result = dict(self.analysis_provider(chart))
                decision = dict(result.get("decision") or {})
                knowledge = dict(result.get("knowledge") or {})
                second_brain = dict(result.get("second_brain") or {})
            except Exception as error:
                analysis_error = True
                decision = self._unavailable_decision(f"CANONICAL_ANALYSIS_UNAVAILABLE:{type(error).__name__}:{error}")
                knowledge = {"references": [], "conflicts": [], "status": "UNAVAILABLE"}
                second_brain = {}
        else:
            decision = self._unavailable_decision(f"CITADEL_ANALYSIS_UNSUPPORTED:{chart.instrument.route.value}:{chart.instrument.underlying}")
            if chart.option is not None:
                decision.update({"displayed_option": chart.option.trading_symbol,
                    "current_contract_accepted": False, "current_contract_rejected": True,
                    "current_contract_reason": chart.instrument.mapping_status, "better_option_found": False})
            knowledge = {"references": [], "conflicts": [], "status": "UNAVAILABLE"}
            second_brain = {}

        return {
            "decision": decision,
            "knowledge": knowledge,
            "second_brain": second_brain,
            "analysis_attempted": analysis_attempted,
            "analysis_error": analysis_error,
            "analysis_duration": (perf_counter() - analysis_started) * 1000
        }

    def _on_canonical_state(self, snapshot: dict[str, Any]) -> None:
        fast = snapshot.get("fast_state", {})
        slow = snapshot.get("slow_state", {})

        if not fast or not slow:
            return

        chart = fast.get("chart")
        if not chart:
            return

        now = fast["now"]
        reason = fast["reason"]
        dependency_hash = fast["dependency_hash"]
        phase5_hash = fast["phase5_hash"]
        event_seed = fast["event_seed"]

        decision = slow.get("decision", {})
        knowledge = slow.get("knowledge", {})
        second_brain = slow.get("second_brain", {})
        phase5 = fast.get("phase5", {})

        if self.fast_path_provider:
            decision = self.fast_path_provider(decision, phase5)

        with self._lock:
            self._stats["last_analysis_ms"] = slow.get("analysis_duration")
            if slow.get("analysis_attempted"):
                self._stats["analysis_runs"] += 1

        if slow.get("analysis_attempted"):
            self.telemetry.record("deterministic_analysis", slow.get("analysis_duration", 0), error=slow.get("analysis_error", False))

        sync_state = self._center_state(decision, chart)
        sync_state = self._phase5_state(sync_state, phase5)
        if not second_brain:
            second_brain = self._second_brain_projection(decision, knowledge, chart)

        alert = self._alert(reason, sync_state, chart, decision, phase5, second_brain)
        personal_oracle = self._personal_projection(second_brain)

        projection = seal(TradingViewSyncProjection(
            event_id=f"tvprojection_{event_seed}", correlation_id=chart.correlation_id,
            source_timestamp=now.isoformat(), received_timestamp=now.isoformat(), generated_timestamp=now.isoformat(),
            provenance={"service": "TradingViewAutoSyncService", "decision_authority": "OracleDecisionEnvelope",
                        "market_data_authority": "CITADEL", "tradingview_role": "IDENTITY_METADATA_ONLY"},
            sync_state=sync_state, chart_state=chart, decision=decision, knowledge=knowledge,
            phase5=phase5, personal_oracle=personal_oracle, health=self.health(), safety=self.SAFETY,
            alert_event=alert,
        ))

        with self._lock:
            if self._last_chart and self._last_chart.chart_state_version != chart.chart_state_version:
                return

            self._projection_record = projection
            self._projection = projection.to_dict()
            self._last_dependency_hash = dependency_hash if dependency_hash is not None else self._dependency_hash()
            self._last_phase5_hash = phase5_hash if phase5_hash is not None else _hash(phase5)
            self._stats["changes"] += 1
            _atomic_write(self.checkpoint_path, {"projection": self._projection, "chart_identity_hash": self._identity_hash(chart.to_dict()),
                                                 "saved_at": now.isoformat(), "policy_version": SYNC_POLICY_VERSION})

        self._publish_live_event("decision_updated", self.projection())
        if self.decision_observer is not None:
            try:
                self.decision_observer(self.projection())
            except Exception as error:
                self._stats["last_observer_error"] = f"{type(error).__name__}:{error}"
        if alert:
            self.events.append("ORACLE_ALERT", alert, recorded_at=now.isoformat(), idempotency_key=str(alert["deduplication_key"]))
            self._publish_live_event("alert", self.projection())
