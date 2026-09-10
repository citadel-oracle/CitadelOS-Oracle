"""Asynchronous, read-only research aggregation from immutable flow evidence."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategy_lab.storage import _atomic_write
from src.oracle.reliability import is_nse_market_open

from .recorder import OrderFlowEvidenceRecorder


class OrderFlowResearchAggregator:
    """Build bounded human-readable research artifacts outside the packet path."""

    def __init__(
        self,
        recorder: OrderFlowEvidenceRecorder,
        root: str | Path,
        *,
        interval_seconds: float = 30.0,
        scan_limit: int = 50_000,
        market_open_provider=is_nse_market_open,
    ):
        self.recorder = recorder
        self.root = Path(root)
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.scan_limit = max(100, int(scan_limit))
        self._market_open_provider = market_open_provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._latest: dict[str, Any] = self._empty("NOT_STARTED")

    def start(self) -> bool:
        """Start EOD/research aggregation only outside the live market path.

        The aggregator reads immutable episode history and is intentionally not
        a live Oracle authority.  Re-reading a large journal during a session
        creates avoidable Python/GIL and storage contention; defer it rather
        than letting a research view perturb the canonical feed, recorder, or
        health endpoints.  Its stored data and aggregation semantics are
        unchanged.
        """
        if self._market_open_provider():
            with self._lock:
                self._latest = self._empty("DEFERRED_LIVE_SESSION")
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="order-flow-research",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._latest)

    def aggregate_once(self) -> dict[str, Any]:
        try:
            rows = self.recorder.episodes.read(limit=self.scan_limit)
            result = self._aggregate(rows)
            self._persist(result)
        except Exception as error:
            result = self._empty(f"DEGRADED_{type(error).__name__}")
        with self._lock:
            self._latest = result
        return deepcopy(result)

    def _run(self) -> None:
        self.aggregate_once()
        while not self._stop.wait(self.interval_seconds):
            self.aggregate_once()

    def _aggregate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        latest_by_episode: dict[str, dict[str, Any]] = {}
        completed_by_episode: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            episode_id = str(payload.get("episode_id") or "")
            if not episode_id:
                continue
            latest_by_episode[episode_id] = payload
            if row.get("event_type") == "EPISODE_COMPLETED" or payload.get("complete") is True:
                completed_by_episode[episode_id] = payload

        episodes = sorted(
            latest_by_episode.values(),
            key=lambda item: (str(item.get("started_at") or ""), str(item.get("episode_id") or "")),
        )
        completed = list(completed_by_episode.values())
        current = next((item for item in reversed(episodes) if not item.get("complete")), None)
        call_count = sum(item.get("direction") == "CALL" for item in episodes)
        put_count = sum(item.get("direction") == "PUT" for item in episodes)
        quality_rows = [item for item in episodes if item.get("data_quality")]
        good_rows = sum(item.get("data_quality") == "GOOD" for item in quality_rows)
        bands = []
        for low, high in ((60, 69), (70, 79), (80, 89), (90, None)):
            qualifying = [
                item for item in episodes
                if any(int(key) >= low and (high is None or int(key) <= high)
                       for key in (item.get("band_crossings") or {}))
            ]
            bands.append({
                "band": f"{low}+" if high is None else f"{low}-{high}",
                "sample_count": len(qualifying),
                "status": "RESEARCHING",
                "outcome_rate": None,
                "expectancy": None,
                "entry_lateness": None,
            })

        reversal_log = []
        for item in episodes[-24:]:
            states = item.get("reversal_states") or []
            if states:
                reversal_log.append({
                    "episode_id": item.get("episode_id"),
                    "direction": item.get("direction"),
                    "latest": states[-1],
                    "actual_reversal": None,
                    "lead_lag_ms": None,
                    "option_points": None,
                    "underlying_points": None,
                    "false_reversal": None,
                })

        timeline = [{
            "episode_id": item.get("episode_id"),
            "timestamp": item.get("started_at"),
            "event": "EPISODE_COMPLETED" if item.get("complete") else "EPISODE_ACTIVE",
            "direction": item.get("direction"),
            "result": item.get("final_result"),
        } for item in episodes[-12:]]

        generated = datetime.now(timezone.utc).isoformat()
        session_id = str(episodes[-1].get("session_id")) if episodes else generated[:10]
        return {
            "status": "READY",
            "generated_at": generated,
            "session_id": session_id,
            "source": "ORDER_FLOW_IMMUTABLE_EPISODE_STREAM",
            "current_episode": deepcopy(current),
            "today": {
                "call_episodes": call_count,
                "put_episodes": put_count,
                "completed": len(completed),
                "successful": None,
                "failed": None,
                "neutral": None,
                "false_signals": None,
                "reversals": sum(
                    any(state.get("state") == "REVERSAL_CONFIRMED" for state in (item.get("reversal_states") or []))
                    for item in episodes
                ),
                "clean_reversals": None,
                "median_reversal_lead_ms": None,
                "data_quality_coverage": round(good_rows / len(quality_rows), 6) if quality_rows else None,
            },
            "score_edge": bands,
            "best_combination": {
                "status": "RESEARCHING",
                "families": ["FUTURES_PRESSURE", "RESPONSE", "OPTION_CONFIRMATION", "CONTEXTUAL_LOCATION"],
                "incremental_evidence": None,
            },
            "reversal_log": reversal_log,
            "event_timeline": timeline,
            "shadow_pnl": {"status": "NOT_YET_AVAILABLE", "reason": "NO_DEFINED_SHADOW_EXIT_OUTCOME"},
            "edge_health": {
                "sample_count": len(episodes),
                "score_band_stability": None,
                "recent_expectancy": None,
                "long_window_expectancy": None,
                "current_drawdown": None,
                "peak_drawdown": None,
                "edge_stability": "RESEARCHING",
                "maturity": "RESEARCH",
            },
            "provisional_config": {
                "book_weight": 0.45,
                "response_weight": 0.35,
                "option_weight": 0.20,
                "reversal_entry": 0.35,
                "stable_hysteresis": 0.20,
                "forming_ms": 750,
                "confirmation_ms": 1500,
                "basket_authority_ttl_seconds": 20,
                "validation": "ENGINEERING_DEFAULTS_NOT_VALIDATED",
            },
        }

    def _persist(self, result: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        session = str(result.get("session_id") or "unknown")
        _atomic_write(self.root / "current.json", result)
        _atomic_write(self.root / "Daily" / f"{session}.json", result)
        _atomic_write(self.root / "Probability Ledger.json", {"status": "RESEARCHING", "score_edge": result["score_edge"]})
        _atomic_write(self.root / "Threshold Research.json", {"status": "RESEARCHING", "config": result["provisional_config"]})
        _atomic_write(self.root / "Reversal Research.json", {"status": "RESEARCHING", "events": result["reversal_log"]})
        _atomic_write(self.root / "Regime Analysis.json", {"status": "NOT_YET_AVAILABLE"})
        _atomic_write(self.root / "Validated Learnings.json", {"status": "EMPTY", "maturity": "RESEARCH"})

    @staticmethod
    def _empty(status: str) -> dict[str, Any]:
        return {
            "status": status,
            "generated_at": None,
            "source": "ORDER_FLOW_IMMUTABLE_EPISODE_STREAM",
            "current_episode": None,
            "today": None,
            "score_edge": [],
            "best_combination": {"status": "RESEARCHING"},
            "reversal_log": [],
            "event_timeline": [],
            "shadow_pnl": {"status": "NOT_YET_AVAILABLE"},
            "edge_health": {"maturity": "RESEARCH", "sample_count": 0},
        }
