"""Strategy Lab deployment manager and read-only API projections."""

from __future__ import annotations

import threading
import shutil
import json
from time import perf_counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .models import DeploymentRequest, StrategyMetadata, deployment_capabilities
from .paper_engine import InstitutionalPaperTradingEngine, aggregate_portfolio
from .runtime import StrategyRuntime, calculate_statistics
from .storage import StrategyRegistryStore, StrategyWorkspace
from .state_truth import authoritative_open_positions, reconcile_deployment_positions


class StrategyLabService:
    SCHEMA_VERSION = 1
    MODE = "STRATEGY_LAB_RESEARCH_PAPER_ONLY"

    def __init__(
        self,
        root: str = "logs/strategy_lab",
        *,
        options_structure_provider=None,
        max_simultaneous_catchup: int = 2,
    ):
        self.root = Path(root).resolve()
        self.registry = StrategyRegistryStore(self.root)
        self._runtimes: Dict[str, StrategyRuntime] = {}
        self._activation: Dict[str, bool] = {}
        self._event_observers = []
        self._lock = threading.RLock()
        self._tail_cache_lock = threading.RLock()
        self._tail_cache: Dict[tuple[str, int], tuple[tuple[int, int, int], List[Dict[str, Any]]]] = {}
        self._review_cache_signature: Optional[tuple[Any, ...]] = None
        self._review_cache: Optional[Dict[str, Any]] = None
        self._snapshot_version = 0
        self._started = False
        self._options_structure_provider = options_structure_provider
        self._max_simultaneous_catchup = max(1, int(max_simultaneous_catchup))
        self._catchup_semaphore = threading.BoundedSemaphore(
            self._max_simultaneous_catchup
        )

    def deploy(self, request: DeploymentRequest, *, start: bool = False) -> StrategyRuntime:
        metadata = request.metadata
        with self._lock:
            if metadata.strategy_id in self._runtimes:
                raise ValueError("strategy runtime already loaded")
            self.registry.register(metadata.to_dict())
            workspace = StrategyWorkspace(self.root / "runtimes", metadata.strategy_id)
            workspace.write("metadata", metadata.to_dict())
            if request.execution is None:
                request = replace(
                    request,
                    execution=InstitutionalPaperTradingEngine.from_metadata(
                        metadata=metadata.to_dict(),
                        workspace=workspace,
                    ),
                )
            event_bus = getattr(request.execution, "event_bus", None)
            if event_bus is not None:
                for observer in self._event_observers:
                    event_bus.subscribe_all(observer)
            runtime = StrategyRuntime(
                request=request,
                workspace=workspace,
                catchup_semaphore=self._catchup_semaphore,
            )
            self._runtimes[metadata.strategy_id] = runtime
            self._activation[metadata.strategy_id] = request.activation_enabled
            if not request.activation_enabled:
                runtime.gate_activation(
                    request.activation_reason or "DEPLOYMENT_ACTIVATION_DISABLED"
                )
            elif start or self._started:
                runtime.bootstrap_data()
                runtime.start()
            return runtime

    def start(self) -> None:
        self._started = True
        for strategy_id, runtime in list(self._runtimes.items()):
            if self._activation.get(strategy_id, True):
                runtime.bootstrap_data()
                runtime.start()

    def stop(self) -> None:
        for strategy_id, runtime in list(self._runtimes.items()):
            if self._activation.get(strategy_id, True):
                runtime.stop()
        self._started = False

    def has_runtime(self, strategy_id: str) -> bool:
        """Return whether the exact deployment runtime is already loaded."""

        with self._lock:
            return strategy_id in self._runtimes

    def pause_runtime(self, strategy_id: str) -> Dict[str, Any]:
        """Pause one exact runtime without affecting peer deployments."""

        with self._lock:
            runtime = self._runtimes.get(strategy_id)
            if runtime is None:
                raise KeyError(strategy_id)
            self._activation[strategy_id] = False
        runtime.stop()
        return runtime.status()

    def resume_runtime(self, strategy_id: str) -> Dict[str, Any]:
        """Resume one exact, already-loaded runtime."""

        with self._lock:
            runtime = self._runtimes.get(strategy_id)
            if runtime is None:
                raise KeyError(strategy_id)
            self._activation[strategy_id] = True
        runtime.bootstrap_data()
        runtime.start()
        return runtime.status()

    def subscribe_events(self, observer) -> None:
        """Attach an operational observer without changing domain-event mutation."""

        with self._lock:
            self._event_observers.append(observer)
            for runtime in self._runtimes.values():
                event_bus = getattr(runtime.execution, "event_bus", None)
                if event_bus is not None:
                    event_bus.subscribe_all(observer)

    def cancel_pending_orders(self) -> Dict[str, Any]:
        """Emergency cancellation surface; it never closes an open position."""

        cancelled = 0
        rejected = []
        for strategy_id, runtime in list(self._runtimes.items()):
            cancel = getattr(runtime.execution, "cancel_strategy", None)
            if not callable(cancel):
                rejected.append(strategy_id)
                continue
            result = cancel()
            cancelled += len(result.get("cancelled_orders") or []) if isinstance(result, Mapping) else 0
        return {"status": "COMPLETE" if not rejected else "PARTIAL", "cancelled_orders": cancelled, "unsupported_runtimes": rejected}

    def reconcile_paper_position(
        self,
        *,
        strategy_id: str,
        position_id: str,
        contract: str,
        quantity: int,
        quote: Mapping[str, Any],
        dry_run: bool = True,
        backup_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Close one exactly identified paper position through its existing OMS."""

        runtime = self._runtimes.get(strategy_id)
        if runtime is None:
            return self._reconciliation_result("REJECTED", "STRATEGY_RUNTIME_NOT_LOADED")
        if not runtime._tick_lock.acquire(blocking=False):
            return self._reconciliation_result("REJECTED", "STRATEGY_RUNTIME_BUSY")
        try:
            state = runtime.execution.projection()
            prior = next((
                order for order in state.get("orders") or []
                if order.get("position_id") == position_id
                and str(order.get("contract") or "") == str(contract)
                and order.get("position_effect") == "CLOSE"
                and order.get("status") == "FILLED"
                and str(order.get("exit_reason") or "").upper() == "RECONCILIATION"
            ), None)
            if prior is not None:
                return self._reconciliation_result(
                    "ALREADY_RECONCILED", "RECONCILIATION_ALREADY_FILLED",
                    order_id=prior.get("order_id"),
                )
            position = next((
                row for row in state.get("positions") or []
                if row.get("position_id") == position_id
            ), None)
            if position is None:
                return self._reconciliation_result("REJECTED", "POSITION_NOT_FOUND")
            checks = (
                (str(position.get("strategy_id") or "") == strategy_id, "STRATEGY_ID_MISMATCH"),
                (str(position.get("contract") or "") == str(contract), "CONTRACT_MISMATCH"),
                (position.get("quantity") == quantity, "QUANTITY_MISMATCH"),
                (position.get("status") == "OPEN", "POSITION_NOT_OPEN"),
                (state.get("paper_only") is True, "PAPER_ONLY_REQUIRED"),
                (state.get("live_trading_enabled") is False, "LIVE_TRADING_MUST_BE_DISABLED"),
                (state.get("broker_submission") is False, "BROKER_SUBMISSION_MUST_BE_DISABLED"),
            )
            failure = next((reason for valid, reason in checks if not valid), None)
            if failure:
                return self._reconciliation_result("REJECTED", failure)
            quote_contract = str(quote.get("security_id") or quote.get("contract") or "")
            quote_price = quote.get("ltp")
            if (
                quote_contract != str(contract)
                or isinstance(quote_price, bool)
                or not isinstance(quote_price, (int, float))
                or float(quote_price) <= 0
            ):
                return self._reconciliation_result("REJECTED", "AUTHORITATIVE_EXIT_PRICE_REQUIRED")
            validation = {
                "strategy_id": strategy_id,
                "position_id": position_id,
                "contract": str(contract),
                "quantity": quantity,
                "exit_price": float(quote_price),
            }
            if dry_run:
                return self._reconciliation_result("VALIDATED", "DRY_RUN_COMPLETE", validation=validation)

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = Path(backup_root).resolve() if backup_root else self.root / "backups"
            backup_path = destination / f"{strategy_id}-{position_id}-{stamp}"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(runtime.workspace.root, backup_path)
            option_type = str((position.get("option_contract") or {}).get("option_type") or "CE").lower()
            result = runtime.execution.process(
                evaluation={
                    "evaluation_id": f"reconciliation:{strategy_id}:{position_id}",
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                    "signal": "SELL",
                    "position_effect": "CLOSE",
                    "position_id": position_id,
                    "contract": str(contract),
                    "side": position.get("side"),
                    "option_contract": position.get("option_contract"),
                    "exit_reason": "RECONCILIATION",
                    "reason": "RECONCILIATION",
                    "paper_only": True,
                    "live_trading_enabled": False,
                    "broker_submission": False,
                },
                context={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "argus": {"data": {"atm_window": [{option_type: dict(quote)}]}},
                },
                workspace=runtime.workspace,
            )
            if result.get("status") != "FILLED":
                return self._reconciliation_result(
                    "REJECTED", str(result.get("reason") or "RECONCILIATION_NOT_FILLED"),
                    backup_path=str(backup_path), execution=result,
                )
            return self._reconciliation_result(
                "RECONCILED", "RECONCILIATION_FILLED",
                backup_path=str(backup_path), execution=result, validation=validation,
            )
        finally:
            runtime._tick_lock.release()

    @staticmethod
    def _reconciliation_result(status: str, reason: str, **values: Any) -> Dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            **values,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    def evaluate_tournament(self, context: Mapping[str, Any], strategy_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        selected = list(strategy_ids or self._runtimes.keys())
        outcomes = {}
        for strategy_id in selected:
            runtime = self._runtimes.get(strategy_id)
            outcomes[strategy_id] = (
                runtime.tick_once(context_override=context)
                if runtime is not None
                else {"status": "NOT_LOADED", "reason": "STRATEGY_RUNTIME_NOT_LOADED"}
            )
        return {
            "status": "EVALUATED",
            "same_context": True,
            "independent_runtimes": True,
            "outcomes": outcomes,
            "winner": None,
            "runner_up": None,
            "worst": None,
            "ranking_reason": "COMPLETED_PAPER_TRADES_REQUIRED",
        }

    def status(self) -> Dict[str, Any]:
        deployments = self.registry.load()["deployments"]
        loaded = [runtime.status() for runtime in self._runtimes.values()]
        return self._status_from_rows(deployments, loaded)

    def _status_from_rows(
        self,
        deployments: Sequence[Mapping[str, Any]],
        loaded: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        running = sum(row["state"] == "RUNNING" for row in loaded)
        degraded = sum(row["health"] != "HEALTHY" for row in loaded)
        ready = sum(row.get("DATA_READY") is True for row in loaded)
        schedulers = [row.get("scheduler") or {} for row in loaded]
        return {
            "status": "READY" if degraded == 0 and ready == len(loaded) else "DEGRADED",
            "health": "HEALTHY" if degraded == 0 else "DEGRADED",
            "readiness": "READY" if ready == len(loaded) else "BLOCKED",
            "mode": self.MODE,
            "schema_version": self.SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "manager_started": self._started,
            "deployment_count": len(deployments),
            "loaded_runtime_count": len(loaded),
            "running_strategy_count": running,
            "data_ready_count": ready,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "frontend_execution": False,
            "production_state_mutated": False,
            "development_state_mutated": False,
            "shared_paper_state": False,
            "shared_ledger": False,
            "shared_scheduler_state": False,
            "shared_strategy_state": False,
            "shared_journal": False,
            "shared_execution_state": False,
            "max_simultaneous_catchup": self._max_simultaneous_catchup,
            "strategy_jobs_running": sum(bool(row.get("catchup_active")) for row in schedulers),
            "strategy_jobs_pending": sum(int(row.get("pending_recovery_contexts") or 0) for row in schedulers),
            "strategy_duplicate_jobs_avoided": sum(int(row.get("unchanged_context_coalesces") or 0) for row in schedulers),
            "strategy_catchup_waits": sum(int(row.get("bounded_catchup_waits") or 0) for row in schedulers),
        }

    def strategies(self) -> Dict[str, Any]:
        deployments = self.registry.load()["deployments"]
        rows = self._strategy_rows(deployments)
        return {"status": "available", "strategies": rows, "count": len(rows)}

    def _strategy_rows(self, deployments: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for metadata in deployments:
            runtime = self._runtimes.get(str(metadata["strategy_id"]))
            if runtime is not None:
                rows.append(runtime.status())
                continue
            workspace = StrategyWorkspace(self.root / "runtimes", str(metadata["strategy_id"]))
            paper = workspace.read("paper_state")
            persisted_open = list(paper.get("open_positions") or [])
            rows.append(
                {
                    "strategy_id": metadata["strategy_id"],
                    "metadata": metadata,
                    "state": "NOT_LOADED",
                    "health": "HEALTHY",
                    "readiness": "ADAPTER_REQUIRED",
                    "reason": "DEPLOYMENT_ADAPTER_NOT_LOADED_AFTER_RESTART",
                    "latency_ms": None,
                    "last_updated": None,
                    "scheduler": workspace.read("scheduler_state"),
                    "current_position": persisted_open[0] if len(persisted_open) == 1 else None,
                    "current_positions": persisted_open,
                    "current_position_count": len(persisted_open),
                    "current_decision": workspace.read("strategy_state").get("current_decision"),
                    "today_trades": calculate_statistics(paper.get("closed_trades") or [])["completed_trades"],
                    "statistics": calculate_statistics(paper.get("closed_trades") or []),
                    "paper_only": True,
                    "live_trading_enabled": False,
                    "broker_submission": False,
                    "production_state_mutated": False,
                    "development_state_mutated": False,
                }
            )
        return rows

    def leaderboard(self, strategy_rows: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        candidates = []
        for row in strategy_rows if strategy_rows is not None else self.strategies()["strategies"]:
            stats = row["statistics"]
            if not stats["ranking_eligible"]:
                continue
            candidates.append(
                {
                    "strategy_id": row["strategy_id"],
                    "strategy_name": row["metadata"]["name"],
                    **{key: stats[key] for key in ("expectancy", "profit_factor", "win_rate", "drawdown", "sharpe", "net_pnl", "completed_trades", "rr")},
                }
            )
        def score(row):
            return (
                row["expectancy"] if row["expectancy"] is not None else float("-inf"),
                row["profit_factor"] if row["profit_factor"] is not None else float("-inf"),
                row["win_rate"] if row["win_rate"] is not None else float("-inf"),
                -(row["drawdown"] or 0),
                row["sharpe"] if row["sharpe"] is not None else float("-inf"),
                row["net_pnl"],
                row["completed_trades"],
                row["rr"] if row["rr"] is not None else float("-inf"),
            )
        candidates.sort(key=score, reverse=True)
        ranked = [{"rank": index, **row} for index, row in enumerate(candidates, start=1)]
        return {
            "status": "available",
            "basis": "COMPLETED_PAPER_TRADES_ONLY",
            "ranking_order": ["expectancy", "profit_factor", "win_rate", "drawdown", "sharpe", "net_pnl", "completed_trades", "rr"],
            "entries": ranked,
            "eligible_strategy_count": len(ranked),
        }

    def strategy_detail(self, strategy_id: str) -> Dict[str, Any]:
        runtime = self._runtimes.get(strategy_id)
        if runtime is not None:
            return runtime.detail()
        metadata = next((row for row in self.registry.load()["deployments"] if row.get("strategy_id") == strategy_id), None)
        if metadata is None:
            raise KeyError(strategy_id)
        workspace = StrategyWorkspace(self.root / "runtimes", strategy_id)
        paper = workspace.read("paper_state")
        stats = calculate_statistics(paper.get("closed_trades") or [])
        return {
            "status": "available",
            "strategy": next(row for row in self.strategies()["strategies"] if row["strategy_id"] == strategy_id),
            "overview": {"workspace": str(workspace.root), "paper_state": paper, "integrity": workspace.integrity()},
            "statistics": stats,
            "journal": workspace.journal.read(limit=100),
            "replay": workspace.replay.read(limit=100),
            "evidence": workspace.evidence.read(limit=100),
            "trades": list(paper.get("closed_trades") or []),
            "equity_curve": stats["equity_curve"],
            "parameters": dict(metadata.get("parameters") or {}),
            "logs": workspace.logs.read(limit=100),
            "order_ledger": workspace.order_ledger.read(limit=100),
            "fill_ledger": workspace.fill_ledger.read(limit=100),
        }

    def dashboard(self) -> Dict[str, Any]:
        dashboard_started = perf_counter()
        lock_started = perf_counter()
        timings: Dict[str, float] = {}
        with self._lock:
            timings["service_lock_wait_ms"] = round((perf_counter() - lock_started) * 1000, 3)
            lock_hold_started = perf_counter()
            operation_started = perf_counter()
            deployments = self.registry.load()["deployments"]
            timings["registry_filesystem_read_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            strategy_rows = self._strategy_rows(deployments)
            timings["runtime_status_projection_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            paper_states = self._paper_states(deployments=deployments)
            timings["paper_state_projection_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            projection_warning = []
            try:
                open_positions = authoritative_open_positions(paper_states)
            except ValueError as error:
                open_positions = [
                    dict(item) for state in paper_states for item in state.get("positions") or []
                    if str(item.get("status") or "").upper() == "OPEN"
                ]
                projection_warning.append(str(error))
            strategy_rows, position_reconciliation = reconcile_deployment_positions(strategy_rows, open_positions)
            timings["position_reconciliation_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            position_reconciliation["warnings"] = [*position_reconciliation["warnings"], *projection_warning]
            if position_reconciliation["warnings"]:
                position_reconciliation["status"] = "WARNING"
            strategies = {"status": "available", "strategies": strategy_rows, "count": len(strategy_rows)}
            leaderboard = self.leaderboard(strategy_rows)
            status = self._status_from_rows(deployments, strategy_rows)
            from src.system_status import CanonicalStatusEngine
            status["canonical_status"] = CanonicalStatusEngine.evaluate(
                backend_online=True,
                deployments_status=strategy_rows,
            )
            timings["status_and_leaderboard_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            execution = self.execution_projection(
                paper_states, authoritative_positions=open_positions,
                reconciliation=position_reconciliation,
            )
            timings["execution_projection_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            review_signature = self._review_execution_signature(paper_states)
            review_cache_hit = (
                self._review_cache is not None
                and self._review_cache_signature == review_signature
            )
            if review_cache_hit:
                review = self._review_cache
            else:
                review = self.review_projection(deployments)
                self._review_cache_signature = review_signature
                self._review_cache = review
            timings["review_cache_hit"] = review_cache_hit
            timings["review_filesystem_read_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            operation_started = perf_counter()
            portfolio = self._portfolio_from_states(paper_states)
            timings["portfolio_projection_ms"] = round((perf_counter() - operation_started) * 1000, 3)
            self._snapshot_version += 1
            snapshot_version = self._snapshot_version
            generated_at = datetime.now(timezone.utc).isoformat()
            for row in strategy_rows:
                row["snapshot_version"] = snapshot_version
                row["generated_at"] = generated_at
            execution.update({"snapshot_version": snapshot_version, "generated_at": generated_at})
            portfolio.update({"snapshot_version": snapshot_version, "generated_at": generated_at})
            timings["service_lock_hold_ms"] = round((perf_counter() - lock_hold_started) * 1000, 3)
        total_completed = sum(row["statistics"]["completed_trades"] for row in strategies["strategies"])
        operator_started = perf_counter()
        operator_strategies = [self._operator_strategy(row) for row in strategies["strategies"]]
        timings["operator_projection_ms"] = round((perf_counter() - operator_started) * 1000, 3)
        timings["filesystem_reads_ms"] = round(
            timings["registry_filesystem_read_ms"] + timings["review_filesystem_read_ms"], 3
        )
        timings["total_ms"] = round((perf_counter() - dashboard_started) * 1000, 3)
        return {
            "generated_at": generated_at,
            "snapshot_version": snapshot_version,
            "status": status,
            "strategies": operator_strategies,
            "leaderboard": leaderboard,
            "summary": {
                "deployed_strategies": strategies["count"],
                "running_strategies": status["running_strategy_count"],
                "completed_paper_trades": total_completed,
                "ranking_eligible_strategies": leaderboard["eligible_strategy_count"],
            },
            "deployment": deployment_capabilities(),
            "tournament": {
                "architecture_status": "READY",
                "same_candle_fanout": True,
                "same_market_context": True,
                "independent_paper_state": True,
                "independent_execution": True,
                "comparison_requires_completed_trades": True,
            },
            "safety_labels": [
                "STRATEGY LAB RESEARCH ONLY",
                "NOT PRODUCTION",
                "NOT DEVELOPMENT",
                "PAPER ONLY",
                "NOT USED FOR LIVE TRADING",
            ],
            "empty_state": (
                "NO_STRATEGIES_DEPLOYED"
                if strategies["count"] == 0
                else None
            ),
            "portfolio": portfolio,
            "execution": execution,
            "review": review,
            "performance": timings,
        }

    def execution_projection(
        self, states: Optional[Sequence[Mapping[str, Any]]] = None, *,
        authoritative_positions: Optional[Sequence[Mapping[str, Any]]] = None,
        reconciliation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        states = list(states) if states is not None else self._paper_states()
        positions = [dict(item) for state in states for item in state.get("positions") or []]
        open_positions = (
            [dict(item) for item in authoritative_positions]
            if authoritative_positions is not None else authoritative_open_positions(states)
        )
        orders = [dict(item) for state in states for item in state.get("orders") or []]
        fills = [dict(item) for state in states for item in state.get("fills") or []]
        closed_trades = [dict(item) for state in states for item in state.get("closed_trades") or []]
        timeline = []
        for order in orders:
            created_at = order.get("created_at")
            strategy_id = str(order.get("strategy_id") or "")
            if created_at:
                timeline.append({"record_id": f"{order.get('order_id')}:signal", "strategy_id": strategy_id,
                    "event_type": "Signal Generated", "entity_id": order.get("signal_id"), "recorded_at": created_at,
                    "payload": self._operator_event_payload({"order": order})})
                timeline.append({"record_id": f"{order.get('order_id')}:submitted", "strategy_id": strategy_id,
                    "event_type": "Entry Submitted" if order.get("position_effect") == "OPEN" else "Exit",
                    "entity_id": order.get("order_id"), "recorded_at": created_at,
                    "payload": self._operator_event_payload({"order": order})})
            status_name = str(order.get("status") or "").upper()
            if status_name in {"REJECTED", "CANCELLED", "EXPIRED"}:
                event_at = order.get("cancelled_at") or order.get("expired_at") or order.get("updated_at") or created_at
                timeline.append({"record_id": f"{order.get('order_id')}:{status_name.lower()}", "strategy_id": strategy_id,
                    "event_type": "Cancelled" if status_name in {"CANCELLED", "EXPIRED"} else "Rejected",
                    "entity_id": order.get("order_id"), "recorded_at": event_at,
                    "payload": self._operator_event_payload({"order": order, "reason": order.get("rejection_reason")})})
        for fill in fills:
            timeline.append({"record_id": fill.get("fill_id"), "strategy_id": str(fill.get("strategy_id") or ""),
                "event_type": "Filled", "entity_id": fill.get("fill_id"), "recorded_at": fill.get("time"),
                "payload": self._operator_event_payload({"fill": fill})})
        for position in positions:
            if position.get("entry_time"):
                timeline.append({"record_id": f"{position.get('position_id')}:open", "strategy_id": str(position.get("strategy_id") or ""),
                    "event_type": "Position Open", "entity_id": position.get("position_id"), "recorded_at": position.get("entry_time"),
                    "payload": self._operator_event_payload({"position": position})})
        # Today's closed trades (Asia/Kolkata timezone date)
        from zoneinfo import ZoneInfo
        ist_now = datetime.now(ZoneInfo("Asia/Kolkata"))
        today_date_str = ist_now.strftime("%Y-%m-%d")

        todays_trades = []
        for trade in closed_trades:
            exit_time_str = trade.get("exit_time") or trade.get("closed_at") or trade.get("entry_time")
            if not exit_time_str:
                continue
            try:
                trade_dt = datetime.fromisoformat(str(exit_time_str).replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata"))
                if trade_dt.strftime("%Y-%m-%d") == today_date_str:
                    pnl = float(trade.get("realized_pnl") or trade.get("pnl") or 0.0)
                    dur = trade.get("duration_seconds")
                    if dur is None and trade.get("entry_time") and trade.get("exit_time"):
                        try:
                            en_dt = datetime.fromisoformat(str(trade["entry_time"]).replace("Z", "+00:00"))
                            ex_dt = datetime.fromisoformat(str(trade["exit_time"]).replace("Z", "+00:00"))
                            dur = (ex_dt - en_dt).total_seconds()
                        except Exception:
                            dur = None

                    status = "WINNING" if pnl > 0 else "LOSING" if pnl < 0 else "BREAKEVEN"
                    todays_trades.append({
                        "trade_id": str(trade.get("trade_id") or trade.get("position_id") or ""),
                        "position_id": str(trade.get("position_id") or trade.get("trade_id") or ""),
                        "deployment_id": str(trade.get("strategy_id") or ""),
                        "strategy": str(trade.get("strategy_id") or ""),
                        "timeframe": str(trade.get("timeframe") or ("1m" if "_1M" in str(trade.get("strategy_id")) else "3m" if "_3M" in str(trade.get("strategy_id")) else "1m")),
                        "contract": str(trade.get("contract") or trade.get("held_security_id") or ""),
                        "held_security_id": str(trade.get("held_security_id") or trade.get("contract") or ""),
                        "option_contract": trade.get("option_contract"),
                        "entry_time": trade.get("entry_time"),
                        "entry_price": float(trade.get("entry") or trade.get("average_price") or 0.0),
                        "exit_time": trade.get("exit_time"),
                        "exit_price": float(trade.get("exit") or 0.0),
                        "quantity": int(trade.get("quantity") or 0),
                        "realized_pnl": round(pnl, 8),
                        "pnl_classification": "GROSS_REALIZED_PAPER_PNL",
                        "exit_reason": str(trade.get("exit_reason") or "STRATEGY_EXIT"),
                        "holding_duration_seconds": round(dur, 2) if dur is not None else None,
                        "status": status,
                        "order_chain": {
                            "signal_id": trade.get("signal_id"),
                            "order_id": trade.get("order_id"),
                            "fill_id": trade.get("fill_id"),
                            "position_id": trade.get("position_id"),
                            "lineage": list(trade.get("lineage") or []),
                        },
                        "calculated_at": ist_now.isoformat(),
                    })
            except Exception:
                continue

        todays_trades.sort(key=lambda x: str(x.get("exit_time") or ""), reverse=True)

        wins = sum(1 for t in todays_trades if t["status"] == "WINNING")
        losses = sum(1 for t in todays_trades if t["status"] == "LOSING")
        breakeven = sum(1 for t in todays_trades if t["status"] == "BREAKEVEN")
        total_today = len(todays_trades)
        win_rate = round((wins / total_today * 100), 2) if total_today > 0 else 0.0
        gross_pnl = float(round(sum(t["realized_pnl"] for t in todays_trades), 8))

        todays_summary = {
            "completed_trades": total_today,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": win_rate,
            "gross_realized_pnl": gross_pnl,
            "pnl_scope": "GROSS_REALIZED_PAPER_PNL_NO_BROKERAGE",
            "last_calculated_at": ist_now.isoformat(),
            "exchange_date": today_date_str,
        }

        # NIFTY VOB Multi-Timeframe Intelligence
        import os
        from pathlib import Path
        from src.vob import NiftyVOBEngine

        state_root = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))
        vob_state_path = state_root / "vob_state.json"
        vob_1m_path = state_root / "vob_1m_candles.json"

        vob_engine = NiftyVOBEngine(persistence_path=vob_state_path)
        
        vob_data = {}
        try:
            from src.broker.dhan_client import DhanClient
            from src.vob.backfill import mark_vob_evaluated, sync_current_session

            dhan_client = DhanClient()
            try:
                vob_sync = sync_current_session(vob_1m_path, dhan_client)
            except Exception as exc:
                vob_sync = {"status": "DEGRADED", "runtime_status": "CATCHING_UP", "reason": type(exc).__name__}
            candles_1m = []
            if vob_1m_path.exists():
                try:
                    c_file = json.loads(vob_1m_path.read_text(encoding="utf-8"))
                    candles_1m = c_file.get("candles") or []
                except Exception:
                    pass

            if candles_1m:
                latest_spot = float(candles_1m[-1]["close"]) if candles_1m else None
                # Try fetching live Nifty Spot quote from DhanClient
                try:
                    spot_quote = dhan_client.get_ltp()
                    if spot_quote and isinstance(spot_quote, dict) and spot_quote.get("ltp") is not None:
                        latest_spot = float(spot_quote["ltp"])
                except Exception:
                    pass

                vob_data = vob_engine.ingest_1m_candles(candles_1m, current_nifty_price=latest_spot)
                latest_source = datetime.fromtimestamp(float(candles_1m[-1]["time"]), tz=timezone.utc)
                vob_data["source_1m_sync"] = mark_vob_evaluated(vob_1m_path, latest_source)
                vob_data["source_1m_sync"]["added"] = vob_sync.get("added", 0)
                vob_data["source_1m_sync"]["invalid_removed"] = vob_sync.get("invalid_removed", 0)
            else:
                vob_data = {
                    "status": "UNAVAILABLE",
                    "reason": "CANONICAL_1M_RESERVOIR_UNAVAILABLE",
                    "execution_influence": 0.0,
                    "advisory_only": True,
                }
        except Exception as e:
            vob_data = {
                "status": "UNAVAILABLE",
                "reason": f"VOB_CALCULATION_ERROR: {str(e)}",
                "execution_influence": 0.0,
                "advisory_only": True,
            }

        options_structure = {
            "status": "UNAVAILABLE",
            "reason": "OPTIONS_STRUCTURE_PROVIDER_UNAVAILABLE",
            "executionInfluence": "ZERO",
            "execution_influence": 0,
            "advisory_only": True,
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }
        if callable(self._options_structure_provider):
            try:
                projected = self._options_structure_provider()
                if isinstance(projected, Mapping):
                    options_structure = deepcopy(dict(projected))
            except Exception as exc:
                options_structure["reason"] = f"OPTIONS_STRUCTURE_PROJECTION_ERROR:{type(exc).__name__}"

        statuses = ("PENDING", "FILLED", "PARTIAL", "REJECTED", "CANCELLED", "EXPIRED")
        return {
            "status": "available",
            "positions": positions,
            "authoritative_open_positions": open_positions,
            "orders": orders,
            "fills": fills,
            "closed_trades": closed_trades,
            "todays_closed_trades": {
                "summary": todays_summary,
                "trades": todays_trades,
            },
            "nifty_vob": vob_data,
            "options_structure": options_structure,
            "timeline": timeline[:50],
            "order_counts": {status: sum(str(order.get("status")).upper() == status for order in orders) for status in statuses},
            "position_count": len(open_positions),
            "order_count": len(orders),
            "fill_count": len(fills),
            "closed_trade_count": len(closed_trades),
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
            "reconciliation": dict(reconciliation or {
                "status": "RECONCILED", "authoritative_open_count": len(open_positions),
                "mapped_open_count": len(open_positions), "warnings": [],
            }),
            "mtm": self._open_position_totals(open_positions),
        }

    @staticmethod
    def _open_position_totals(positions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        valid = [row for row in positions if row.get("pnl_valid") is not False and row.get("pnl") is not None]
        invalid = [row for row in positions if row not in valid]
        exposure = sum(abs(float(row.get("current_price") or row.get("average_price") or 0.0) * int(row.get("quantity") or 0)) for row in positions)
        return {
            "status": "AVAILABLE" if not invalid else "PARTIAL" if valid else "UNAVAILABLE",
            "valid_position_count": len(valid), "unavailable_position_count": len(invalid),
            "live_mtm": round(sum(float(row.get("pnl") or 0.0) for row in valid), 8) if valid else None,
            "exposure": round(exposure, 8),
            "unavailable_position_ids": [row.get("position_id") for row in invalid],
        }

    def review_projection(self, deployments: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        journal = []
        for metadata in deployments if deployments is not None else self.registry.load()["deployments"]:
            strategy_id = str(metadata["strategy_id"])
            workspace = StrategyWorkspace(self.root / "runtimes", strategy_id)
            for row in self._read_recent_jsonl(workspace.journal.path, limit=100):
                payload = dict(row.get("payload") or {})
                if not self._meaningful_journal_event(str(row.get("event_type") or ""), payload):
                    continue
                journal.append({
                    "strategy_id": strategy_id,
                    "record_id": row.get("record_id"),
                    "recorded_at": row.get("recorded_at"),
                    "event_type": row.get("event_type"),
                    "payload": self._operator_journal_payload(payload),
                })
        journal.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
        del journal[50:]
        return {
            "status": "available",
            "journal": journal,
            "replay": [],
            "evidence": [],
            "validation": [],
            "paper_only": True,
        }

    @staticmethod
    def _review_execution_signature(states: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
        """Invalidate operator journal reads only for meaningful execution changes.

        Strategy WAIT decisions append to journal files every candle, but the operator
        projection deliberately filters those records.  Keying the review cache to the
        execution lifecycle prevents WAIT-only file churn from forcing journal rescans.
        """

        signature = []
        for state in states:
            orders = tuple(
                (
                    row.get("order_id"), row.get("status"), row.get("updated_at"),
                    row.get("cancelled_at"), row.get("expired_at"),
                )
                for row in state.get("orders") or []
            )
            fills = tuple(
                (row.get("fill_id"), row.get("order_id"), row.get("time"))
                for row in state.get("fills") or []
            )
            positions = tuple(
                (
                    row.get("position_id"), row.get("status"), row.get("current_stop"),
                    row.get("protective_stop"), row.get("target_price"),
                )
                for row in state.get("positions") or []
            )
            closed_trades = tuple(
                (row.get("trade_id"), row.get("exit_time"), row.get("exit_reason"))
                for row in state.get("closed_trades") or []
            )
            signature.append((state.get("strategy_id"), orders, fills, positions, closed_trades))
        return tuple(signature)

    def _read_recent_jsonl(self, path: Path, *, limit: int) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        stat = path.stat()
        signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        cache_key = (str(path), limit)
        with self._tail_cache_lock:
            cached = self._tail_cache.get(cache_key)
            if cached is not None and cached[0] == signature:
                return cached[1]
        block_size = 64 * 1024
        data = b""
        with path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            while position > 0 and data.count(b"\n") <= limit:
                size = min(block_size, position)
                position -= size
                handle.seek(position)
                data = handle.read(size) + data
        rows = []
        for line in data.splitlines()[-limit:]:
            if line.strip():
                rows.append(json.loads(line))
        final_stat = path.stat()
        final_signature = (final_stat.st_ino, final_stat.st_mtime_ns, final_stat.st_size)
        if final_signature == signature:
            with self._tail_cache_lock:
                self._tail_cache[cache_key] = (signature, rows)
        return rows

    @staticmethod
    def _operator_strategy(row: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        decision = row.get("current_decision")
        if isinstance(decision, Mapping):
            result["current_decision"] = {
                key: decision.get(key)
                for key in (
                    "signal", "side", "reason", "evaluated_at", "confidence", "contract",
                    "entry", "exit", "stop", "target", "underlying_stop", "underlying_target",
                    "position_state", "option_contract",
                )
                if decision.get(key) is not None
            }
            forensics = decision.get("forensics")
            argus = forensics.get("argus") if isinstance(forensics, Mapping) else None
            data = argus.get("data") if isinstance(argus, Mapping) else None
            underlying = data.get("underlying") if isinstance(data, Mapping) else None
            if isinstance(underlying, Mapping) and underlying.get("ltp") is not None:
                result["current_decision"]["underlying_price"] = underlying.get("ltp")
        return result

    @staticmethod
    def _meaningful_journal_event(event_type: str, payload: Mapping[str, Any]) -> bool:
        if event_type != "STRATEGY_DECISION":
            return True
        return str(payload.get("signal") or "WAIT").upper() != "WAIT"

    @staticmethod
    def _operator_journal_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "signal", "side", "reason", "entry", "exit", "stop", "target", "exit_reason",
            "contract", "lot_size", "evaluated_at", "underlying_stop", "underlying_target",
            "position_state", "option_contract", "realized_pnl", "pnl", "rr",
        )
        return {key: payload.get(key) for key in keys if payload.get(key) is not None}

    @staticmethod
    def _operator_event_type(event_type: str, payload: Mapping[str, Any]) -> Optional[str]:
        if event_type == "SignalCreated":
            return "Signal Generated" if str(payload.get("signal") or "WAIT").upper() != "WAIT" else None
        if event_type == "OrderCreated":
            order = payload.get("order")
            effect = str(order.get("position_effect") or "") if isinstance(order, Mapping) else ""
            return "Entry Submitted" if effect == "OPEN" else "Exit"
        if event_type == "OrderFilled":
            return "Filled"
        if event_type == "PositionOpened":
            return "Position Open"
        if event_type == "TradeCompleted":
            trade = payload.get("trade")
            reason = str(trade.get("exit_reason") or "") if isinstance(trade, Mapping) else ""
            if "TARGET" in reason.upper():
                return "Target Hit"
            if "STOP" in reason.upper() or reason.upper() == "SL":
                return "Stop Hit"
            if "SESSION" in reason.upper() or "SQUARE" in reason.upper():
                return "Session Exit"
            return "Exit"
        if event_type == "RiskRejected":
            return "Rejected"
        return None

    @staticmethod
    def _operator_event_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
        nested = next((payload.get(key) for key in ("order", "fill", "position", "trade") if isinstance(payload.get(key), Mapping)), {})
        source = nested if isinstance(nested, Mapping) else {}
        keys = (
            "strategy_id", "contract", "side", "position_effect", "status", "price", "average_price",
            "current_price", "pnl", "realized_pnl", "rr", "protective_stop", "stop", "target_price",
            "target", "underlying_stop", "underlying_target", "exit_reason", "reason", "quantity",
        )
        result = {key: source.get(key) for key in keys if source.get(key) is not None}
        if payload.get("reason") is not None:
            result["reason"] = payload.get("reason")
        return result

    def _paper_states(
        self,
        strategy_id: Optional[str] = None,
        *,
        deployments: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        states = []
        for metadata in deployments if deployments is not None else self.registry.load()["deployments"]:
            current_id = str(metadata["strategy_id"])
            if strategy_id and current_id != strategy_id:
                continue
            runtime = self._runtimes.get(current_id)
            projection = (
                getattr(runtime.execution, "projection", None)
                if runtime is not None
                else None
            )
            if callable(projection):
                state = projection()
            else:
                workspace = StrategyWorkspace(self.root / "runtimes", current_id)
                state = workspace.read("paper_engine_state")
            if state:
                states.append(state)
        if strategy_id and not states:
            raise KeyError(strategy_id)
        return states

    def portfolio(self) -> Dict[str, Any]:
        return self._portfolio_from_states(self._paper_states())

    @staticmethod
    def _portfolio_from_states(states: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        projection = aggregate_portfolio(states)
        projection["strategy_ids"] = [row["strategy_id"] for row in states]
        return projection

    def capital(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [{"strategy_id": row["strategy_id"], **dict(row.get("account") or {})} for row in self._paper_states(strategy_id)]
        return {"status": "available", "accounts": rows, "count": len(rows), "paper_only": True}

    def positions(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [dict(position) for state in self._paper_states(strategy_id) for position in state.get("positions") or []]
        return {"status": "available", "positions": rows, "count": len(rows), "paper_only": True}

    def orders(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [dict(order) for state in self._paper_states(strategy_id) for order in state.get("orders") or []]
        return {"status": "available", "orders": rows, "count": len(rows), "paper_only": True}

    def fills(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [dict(fill) for state in self._paper_states(strategy_id) for fill in state.get("fills") or []]
        return {"status": "available", "fills": rows, "count": len(rows), "paper_only": True}

    def paper_statistics(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [{"strategy_id": state["strategy_id"], **dict(state.get("statistics") or {})} for state in self._paper_states(strategy_id)]
        return {"status": "available", "statistics": rows, "count": len(rows), "paper_only": True}

    def trades(self, *, open_only: bool, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        if open_only:
            rows = [dict(position) for state in self._paper_states(strategy_id) for position in state.get("positions") or [] if position.get("status") == "OPEN"]
            key = "open_trades"
        else:
            rows = [dict(trade) for state in self._paper_states(strategy_id) for trade in state.get("closed_trades") or []]
            key = "closed_trades"
        return {"status": "available", key: rows, "count": len(rows), "paper_only": True}

    def comparison(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        target_ids = ["TC_NIFTY_PE_1M", "TC_NIFTY_PE_3M", "BP_NIFTY_CE_1M", "BP_NIFTY_CE_3M"]
        deployments = {}
        for dep_id in target_ids:
            deployments[dep_id] = self._build_comparison_for_deployment(dep_id)

        selected_id = strategy_id if strategy_id in deployments else "TC_NIFTY_PE_1M"
        selected_comparison = deployments.get(selected_id) or self._build_comparison_for_deployment(selected_id)

        return {
            "status": "available",
            "paper_only": True,
            "comparison": selected_comparison,
            "deployments": deployments,
        }

    def _build_comparison_for_deployment(self, deployment_id: str) -> Dict[str, Any]:
        runtime = self._runtimes.get(deployment_id)
        workspace_root = runtime.workspace.root if runtime else self.root / "runtimes" / deployment_id

        # Defaults
        strategy_name = "Trend Catcher" if "TC" in deployment_id else "Bull Pulse"
        timeframe = "1m" if "1M" in deployment_id else "3m"
        argus_mode = "SHADOW" if "1M" in deployment_id else "OFF"
        runtime_status = runtime.status() if runtime is not None else None
        runtime_health = (
            str(runtime_status.get("health") or "UNAVAILABLE").upper()
            if isinstance(runtime_status, Mapping)
            else ("AVAILABLE" if workspace_root.exists() else "UNAVAILABLE")
        )
        runtime_readiness = (
            str(runtime_status.get("readiness") or "UNAVAILABLE").upper()
            if isinstance(runtime_status, Mapping)
            else "UNAVAILABLE"
        )
        runtime_reason = (
            runtime_status.get("reason")
            if isinstance(runtime_status, Mapping)
            else "RUNTIME_NOT_LOADED"
        )

        # Read state files
        paper_state = {}
        paper_engine_state = {}
        journal_rows = []

        if workspace_root.exists():
            try:
                p_file = workspace_root / "paper_state.json"
                if p_file.exists():
                    with open(p_file, "r", encoding="utf-8") as f:
                        paper_state = json.load(f)
            except Exception:
                pass

            try:
                pe_file = workspace_root / "paper_engine_state.json"
                if pe_file.exists():
                    with open(pe_file, "r", encoding="utf-8") as f:
                        paper_engine_state = json.load(f)
            except Exception:
                pass

            try:
                j_file = workspace_root / "journal.jsonl"
                if j_file.exists():
                    with open(j_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                try:
                                    journal_rows.append(json.loads(line))
                                except Exception:
                                    pass
            except Exception:
                pass

        # Parse trades & statistics
        closed_trades = paper_state.get("closed_trades") or paper_engine_state.get("closed_trades") or []
        stats = paper_engine_state.get("statistics") or {}

        native_executed_trades = len(closed_trades)
        native_net_pnl = float(stats.get("net_pnl") or sum(float(t.get("realized_pnl") or t.get("pnl") or 0.0) for t in closed_trades))
        native_win_rate = float(stats.get("win_rate") or 0.0) if stats.get("win_rate") is not None else (
            round(len([t for t in closed_trades if float(t.get("realized_pnl") or t.get("pnl") or 0.0) > 0]) / len(closed_trades) * 100.0, 2)
            if closed_trades else 0.0
        )
        native_expectancy = float(stats.get("expectancy") or 0.0) if stats.get("expectancy") is not None else (
            round(native_net_pnl / len(closed_trades), 2) if closed_trades else 0.0
        )
        native_profit_factor = float(stats.get("profit_factor") or 0.0) if stats.get("profit_factor") is not None else 0.0
        native_max_drawdown = float(stats.get("drawdown") or paper_engine_state.get("account", {}).get("maximum_drawdown") or 0.0)

        # Parse shadow journal records
        shadow_evaluations_list = [r for r in journal_rows if r.get("event_type") == "ARGUS_SHADOW_EVALUATION"]
        shadow_outcomes_list = [r for r in journal_rows if r.get("event_type") == "ARGUS_SHADOW_OUTCOME"]
        native_signal_rows = [r for r in journal_rows if r.get("event_type") in ("ENTRY_CANDIDATE", "PAPER_ORDER_SUBMITTED")]

        # Deduplicate shadow evaluations by evaluation_id / signal_id
        evals_by_id = {}
        for r in shadow_evaluations_list:
            payload = dict(r.get("payload") or {})
            eid = payload.get("evaluation_id") or payload.get("signal_id") or r.get("idempotency_key")
            if eid and eid not in evals_by_id:
                evals_by_id[eid] = (r, payload)

        outcomes_by_signal = {}
        for r in shadow_outcomes_list:
            payload = dict(r.get("payload") or {})
            sig_id = payload.get("signal_id")
            if sig_id:
                outcomes_by_signal[sig_id] = payload

        total_native_signals = max(len(evals_by_id), len(native_signal_rows), native_executed_trades)
        shadow_evaluations_count = len(evals_by_id)

        argus_allows = 0
        argus_blocks = 0
        argus_delays = 0
        useful_blocks = 0
        false_blocks = 0
        avoided_losses = 0.0
        missed_winners = 0.0
        argus_unavailable_count = 0
        argus_stale_count = 0
        last_signal_time = None
        last_argus_snapshot_time = None

        reason_code_counts: Dict[str, Dict[str, Any]] = {}
        recent_signals = []
        equity_curve = []

        cumulative_native = 0.0
        cumulative_counterfactual = 0.0

        for r, payload in evals_by_id.values():
            time_str = r.get("recorded_at") or payload.get("source_timestamp") or payload.get("timestamp")
            if time_str:
                last_signal_time = time_str
                last_argus_snapshot_time = time_str

            hypothetical = payload.get("hypothetical_allow_block_delay") or "ALLOW"
            if hypothetical == "ALLOW":
                argus_allows += 1
            elif hypothetical == "BLOCK":
                argus_blocks += 1
            elif hypothetical == "DELAY":
                argus_delays += 1

            argus_status = str(payload.get("argus_status") or payload.get("argus_freshness") or "").upper()
            if "UNAVAILABLE" in argus_status:
                argus_unavailable_count += 1
            if "STALE" in argus_status:
                argus_stale_count += 1

            sig_id = payload.get("signal_id")
            outcome = outcomes_by_signal.get(sig_id)
            has_outcome = isinstance(outcome, Mapping) and outcome.get("net_pnl") is not None
            net_pnl = float(outcome["net_pnl"]) if has_outcome else None
            c_outcome = (
                outcome.get("counterfactual_shadow_outcome") or
                ("AVOIDED_LOSS" if net_pnl <= 0 else "MISSED_WINNER")
            ) if has_outcome else "PENDING"

            if has_outcome and hypothetical in ("BLOCK", "DELAY"):
                if net_pnl <= 0:
                    useful_blocks += 1
                    avoided_losses += abs(net_pnl)
                else:
                    false_blocks += 1
                    missed_winners += net_pnl

            # Reason codes breakdown
            codes = payload.get("reason_codes") or payload.get("argus_decision", {}).get("reason_codes") or []
            if isinstance(codes, str):
                codes = [codes]
            for code in codes:
                if code not in reason_code_counts:
                    reason_code_counts[code] = {"reason_code": code, "count": 0, "useful_block_count": 0, "false_block_count": 0, "pnl_sum": 0.0}
                reason_code_counts[code]["count"] += 1
                if has_outcome and hypothetical in ("BLOCK", "DELAY"):
                    if net_pnl <= 0:
                        reason_code_counts[code]["useful_block_count"] += 1
                    else:
                        reason_code_counts[code]["false_block_count"] += 1
                if has_outcome:
                    reason_code_counts[code]["pnl_sum"] += net_pnl

            # Build recent signal row
            native_res = (
                f"CLOSED ({'+' if net_pnl >= 0 else ''}{net_pnl:.2f} INR)"
                if has_outcome else "OUTCOME PENDING"
            )
            contract_str = payload.get("contract", {}).get("trading_symbol") or f"NIFTY_{payload.get('option_type', 'OPT')}"
            recent_signals.append({
                "time": time_str or "",
                "strategy": deployment_id,
                "contract": contract_str,
                "native_result": native_res,
                "argus_action": hypothetical,
                "confidence": float(payload.get("confidence") or payload.get("argus_decision", {}).get("readiness_score") or 0.0),
                "reason_codes": list(codes),
                "journal_status": c_outcome,
            })

            # Cumulative PnL for equity curve comparison
            if has_outcome:
                cumulative_native += net_pnl
                if hypothetical != "BLOCK":
                    cumulative_counterfactual += net_pnl

            if time_str and has_outcome:
                equity_curve.append({
                    "timestamp": time_str,
                    "native_pnl": round(cumulative_native, 2),
                    "counterfactual_pnl": round(cumulative_counterfactual, 2),
                })

        # Process reason codes breakdown list
        reason_breakdown = []
        for code, info in reason_code_counts.items():
            cnt = info["count"]
            reason_breakdown.append({
                "reason_code": code,
                "count": cnt,
                "useful_block_count": info["useful_block_count"],
                "false_block_count": info["false_block_count"],
                "avg_native_outcome": round(info["pnl_sum"] / cnt, 2) if cnt > 0 else 0.0,
            })

        sample_size = shadow_evaluations_count if argus_mode == "SHADOW" else total_native_signals

        if sample_size == 0:
            evidence_status = "NO_DATA"
        elif sample_size < 30:
            evidence_status = "INSUFFICIENT_SAMPLE"
        elif sample_size < 100:
            evidence_status = "COLLECTING"
        else:
            evidence_status = "REVIEW_READY"

        return {
            "deployment_id": deployment_id,
            "strategy_name": strategy_name,
            "timeframe": timeframe,
            "argus_mode": argus_mode,
            "runtime_health": runtime_health,
            "runtime_readiness": runtime_readiness,
            "runtime_reason": runtime_reason,
            "total_native_signals": total_native_signals,
            "native_executed_trades": native_executed_trades,
            "shadow_evaluations": shadow_evaluations_count,
            "native_net_pnl": round(native_net_pnl, 2),
            "native_win_rate": native_win_rate,
            "native_expectancy": native_expectancy,
            "native_profit_factor": native_profit_factor,
            "native_max_drawdown": round(native_max_drawdown, 2),
            "argus_hypothetical_allows": argus_allows,
            "argus_hypothetical_blocks": argus_blocks,
            "argus_hypothetical_delays": argus_delays,
            "useful_blocks": useful_blocks,
            "false_blocks": false_blocks,
            "avoided_losses": round(avoided_losses, 2),
            "missed_winners": round(missed_winners, 2),
            "argus_unavailable_count": argus_unavailable_count,
            "argus_stale_count": argus_stale_count,
            "last_signal_time": last_signal_time,
            "last_argus_snapshot_time": last_argus_snapshot_time,
            "sample_size": sample_size,
            "evidence_status": evidence_status,
            "reason_code_breakdown": reason_breakdown,
            "recent_signals": recent_signals[-20:],
            "equity_curve": equity_curve,
        }
