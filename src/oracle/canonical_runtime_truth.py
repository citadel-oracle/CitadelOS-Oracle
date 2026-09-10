"""Canonical Oracle Runtime Truth and Readiness Evaluator.

Unifies runtime state across all endpoints (/health/ready, /v1/oracle/status,
/v1/oracle/fast-lane, /v1/oracle/fast-lane/health, and SSE streams).
Ensures all readiness surfaces consume the identical multi-dimensional truth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class GlobalReadinessState(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


class SubsystemState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class StoragePersistenceState(str, Enum):
    PERSISTENCE_HEALTHY = "PERSISTENCE_HEALTHY"
    PERSISTENCE_WARNING = "PERSISTENCE_WARNING"
    PERSISTENCE_DEGRADED = "PERSISTENCE_DEGRADED"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"


@dataclass
class RuntimeTruthSnapshot:
    global_readiness: GlobalReadinessState
    is_ready: bool
    market_data_state: str
    futures_available: bool
    analytics_available: bool
    persistence_state: StoragePersistenceState
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_readiness": self.global_readiness.value,
            "is_ready": self.is_ready,
            "full_oracle_ready": self.is_ready,
            "market_data_state": self.market_data_state,
            "futures_available": self.futures_available,
            "analytics_available": self.analytics_available,
            "persistence_state": self.persistence_state.value,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evaluated_at": self.evaluated_at,
        }


class CanonicalRuntimeTruth:
    """Canonical multi-dimensional evaluator for Oracle system state."""

    def __init__(self) -> None:
        self._process_live: bool = True
        self._futures_live: bool = True
        self._spot_live: bool = True
        self._options_live: bool = True
        self._order_flow_live: bool = True

        self._analytics_worker_alive: bool = True
        self._argus_live: bool = True
        self._ose_live: bool = True
        self._vob_live: bool = True
        self._strategy_lab_live: bool = True

        self._persistence_live: bool = True
        self._persistence_degraded_reason: str | None = None
        self._storage_free_gb: float = 20.0

        self._paper_only: bool = True
        self._live_trading_enabled: bool = False
        self._execution_influence: str = "ZERO"
        self._broker_submission: bool = False

        self._last_error: str | None = None

    def update_process(self, process_live: bool) -> None:
        self._process_live = bool(process_live)

    def update_market_data(
        self,
        *,
        futures_live: bool = True,
        spot_live: bool = True,
        options_live: bool = True,
        order_flow_live: bool = True,
    ) -> None:
        self._futures_live = bool(futures_live)
        self._spot_live = bool(spot_live)
        self._options_live = bool(options_live)
        self._order_flow_live = bool(order_flow_live)

    def update_analytics(
        self,
        *,
        argus_live: bool = True,
        ose_live: bool = True,
        vob_live: bool = True,
        strategy_lab_live: bool = True,
        worker_alive: bool = True,
        error: str | None = None,
    ) -> None:
        self._argus_live = bool(argus_live)
        self._ose_live = bool(ose_live)
        self._vob_live = bool(vob_live)
        self._strategy_lab_live = bool(strategy_lab_live)
        self._analytics_worker_alive = bool(worker_alive)
        self._last_error = error

    def update_persistence(
        self,
        *,
        persistence_live: bool = True,
        degraded_reason: str | None = None,
        free_gb: float = 20.0,
    ) -> None:
        self._persistence_live = bool(persistence_live)
        self._persistence_degraded_reason = degraded_reason
        self._storage_free_gb = float(free_gb)

    def update_safety(
        self,
        *,
        paper_only: bool = True,
        live_trading_enabled: bool = False,
        execution_influence: str = "ZERO",
        broker_submission: bool = False,
        execution_safe: bool | None = None,
    ) -> None:
        if execution_safe is not None:
            self._paper_only = bool(execution_safe)
            self._live_trading_enabled = not bool(execution_safe)
            self._execution_influence = "ZERO" if execution_safe else "FULL"
            self._broker_submission = not bool(execution_safe)
            return

        self._paper_only = bool(paper_only)
        self._live_trading_enabled = bool(live_trading_enabled)
        self._execution_influence = str(execution_influence)
        self._broker_submission = bool(broker_submission)

    def is_execution_safe(self) -> bool:
        return bool(
            self._paper_only is True
            and self._live_trading_enabled is False
            and str(self._execution_influence).upper() == "ZERO"
            and self._broker_submission is False
        )

    def check_vob_engine_freshness(
        self,
        *,
        zone_formation_timestamp: str | None,
        last_evaluated_monotonic: float | None,
        max_evaluation_age_seconds: float = 5.0,
    ) -> bool:
        """Evaluates VOB freshness strictly by engine evaluation time, NOT zone formation."""
        if last_evaluated_monotonic is None:
            return False
        age = time.monotonic() - float(last_evaluated_monotonic)
        return age <= float(max_evaluation_age_seconds)

    def evaluate(self) -> RuntimeTruthSnapshot:
        blockers: list[str] = []
        warnings: list[str] = []

        # 1. Absolute Execution Safety
        if not self.is_execution_safe():
            blockers.append("SAFETY_INVARIANT_BREACH")

        # 2. Process Liveness
        if not self._process_live:
            blockers.append("BACKEND_PROCESS_TERMINATED")

        # 3. Market Data
        if not (self._futures_live or self._spot_live):
            blockers.append("MARKET_DATA_GATEWAY_DOWN")
        elif not self._options_live:
            warnings.append("OPTION_CHAIN_FEED_DEGRADED")

        # 4. Analytics Worker
        analytics_healthy = bool(
            self._analytics_worker_alive
            and self._argus_live
            and self._ose_live
            and self._vob_live
        )
        if not self._analytics_worker_alive:
            blockers.append("LIVE_ANALYTICS_WORKER_DEAD")
        elif not analytics_healthy:
            warnings.append("ANALYTICS_CALCULATION_DEGRADED")

        # 5. Persistence
        persist_state = StoragePersistenceState.PERSISTENCE_HEALTHY
        if not self._persistence_live:
            persist_state = StoragePersistenceState.PERSISTENCE_DEGRADED
            warnings.append(f"PERSISTENCE_DEGRADED:{self._persistence_degraded_reason or 'UNKNOWN'}")
        elif self._storage_free_gb < 2.0:
            persist_state = StoragePersistenceState.PERSISTENCE_WARNING
            warnings.append("STORAGE_DISK_SPACE_LOW")

        # Determine Global State
        if blockers:
            global_state = GlobalReadinessState.NOT_READY
            is_ready = False
        elif warnings:
            global_state = GlobalReadinessState.DEGRADED
            is_ready = False
        else:
            global_state = GlobalReadinessState.READY
            is_ready = True

        market_state_label = "FULLY_FRESH" if (self._futures_live and self._spot_live and self._options_live) else (
            "PARTIALLY_FRESH" if (self._futures_live or self._spot_live) else "STALE"
        )

        return RuntimeTruthSnapshot(
            global_readiness=global_state,
            is_ready=is_ready,
            market_data_state=market_state_label,
            futures_available=bool(self._futures_live),
            analytics_available=bool(self._analytics_worker_alive and analytics_healthy),
            persistence_state=persist_state,
            blockers=blockers,
            warnings=warnings,
        )
