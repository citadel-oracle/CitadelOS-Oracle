"""Durable Strategy Registry and atomic deployment command plane."""

from __future__ import annotations

import importlib
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.strategy_lab.storage import ImmutableStream

from .models import (
    AggregationMode,
    DeploymentPath,
    RuntimeState,
    StrategyContract,
    aggregate_timeframe_votes,
    canonical_configuration_hash,
    default_configuration,
    validate_configuration,
)
from .price_action import PARITY_SCOPE, SOURCE


DISCOVERY_PACKAGE = "src.strategy_lab.strategies"
SCHEMA_VERSION = 1


class StrategyCommandService:
    """One canonical authority for definitions, versions, and instances."""

    def __init__(
        self,
        root: str | Path,
        *,
        runtime_provider: Callable[[], Mapping[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str, Mapping[str, Any]], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.audit = ImmutableStream(self.root / "audit.jsonl")
        self.notifications = ImmutableStream(self.root / "notifications.jsonl")
        self.receipts = ImmutableStream(self.root / "receipts.jsonl")
        self._runtime_provider = runtime_provider or (lambda: {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._failure_injector = failure_injector
        self._lock = threading.RLock()
        if not self.state_path.exists():
            self._write_state(self._empty_state())
        self.discover()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "definitions": {},
            "versions": {},
            "deployments": {},
            "registration_errors": [],
            "updated_at": None,
        }

    def discover(self) -> dict[str, Any]:
        """Discover deployment packages; invalid packages remain visible as errors."""

        package = importlib.import_module(DISCOVERY_PACKAGE)
        package_root = Path(next(iter(package.__path__)))
        modules = sorted(
            f"{DISCOVERY_PACKAGE}.{path.parent.name}.deployment"
            for path in package_root.glob("*/deployment.py")
            if path.parent.name != "__pycache__"
        )
        contracts: list[StrategyContract] = []
        failures: list[dict[str, Any]] = []
        for module_name in modules:
            try:
                contracts.append(self._contract_from_module(module_name))
            except Exception as error:
                failures.append({
                    "module": module_name,
                    "reason": f"{type(error).__name__}:{error}",
                })
        with self._lock:
            state = self._read_state()
            seen_ids: dict[str, str] = {}
            for contract in contracts:
                prior_module = seen_ids.get(contract.strategy_id)
                if prior_module is not None:
                    failures.append({
                        "module": contract.source_module,
                        "reason": (
                            f"DUPLICATE_STRATEGY_ID:{contract.strategy_id}:"
                            f"{prior_module}:{contract.source_module}"
                        ),
                    })
                    continue
                seen_ids[contract.strategy_id] = contract.source_module
                version_key = contract.version_key
                row = contract.to_dict()
                existing = state["versions"].get(version_key)
                if existing is not None and self._contract_fingerprint(existing) != self._contract_fingerprint(row):
                    failures.append({
                        "module": contract.source_module,
                        "reason": f"VERSION_IMMUTABILITY_VIOLATION:{version_key}",
                    })
                    continue
                if existing is None:
                    row["registered_at"] = self._now()
                    state["versions"][version_key] = row
                    self._audit(
                        "STRATEGY_REGISTERED",
                        {
                            "strategy_id": contract.strategy_id,
                            "strategy_version": contract.version,
                            "state": "DRAFT",
                            "enabled": False,
                        },
                        f"register:{version_key}",
                    )
                    self._notify(
                        "SUCCESS",
                        "Strategy registered as disabled draft",
                        strategy_id=contract.strategy_id,
                        strategy_version=contract.version,
                        instance_id=None,
                        destination=None,
                        key=f"notify:register:{version_key}",
                    )
                state["definitions"][contract.strategy_id] = {
                    "strategy_id": contract.strategy_id,
                    "name": contract.name,
                    "family": contract.family,
                    "latest_version": contract.version,
                    "versions": sorted({
                        *state["definitions"].get(contract.strategy_id, {}).get("versions", []),
                        contract.version,
                    }),
                    "registration_state": "DRAFT",
                    "enabled": False,
                }
            state["registration_errors"] = failures
            state["updated_at"] = self._now()
            self._write_state(state)
        for failure in failures:
            self._notify(
                "CRITICAL",
                f"Strategy registration failed: {failure['reason']}",
                strategy_id=None,
                strategy_version=None,
                instance_id=None,
                destination=None,
                key=f"notify:registration-error:{self._stable_key(failure)}",
            )
        return {
            "discovered": len(contracts),
            "registered": len(contracts) - len(failures),
            "errors": deepcopy(failures),
        }

    def register_contracts(self, contracts: Iterable[StrategyContract]) -> dict[str, Any]:
        """Register immutable programmatic contracts through the same registry.

        This is intentionally narrow: managed research runtimes still own their
        execution lifecycle, while the canonical registry owns definition and
        version identity exactly as it does for discovered deployment modules.
        """

        rows = list(contracts)
        with self._lock:
            state = self._read_state()
            registered = 0
            for contract in rows:
                version_key = contract.version_key
                row = contract.to_dict()
                existing = state["versions"].get(version_key)
                if existing is not None:
                    if self._contract_fingerprint(existing) != self._contract_fingerprint(row):
                        raise ValueError(f"VERSION_IMMUTABILITY_VIOLATION:{version_key}")
                else:
                    row["registered_at"] = self._now()
                    state["versions"][version_key] = row
                    registered += 1
                    self._audit(
                        "STRATEGY_REGISTERED",
                        {
                            "strategy_id": contract.strategy_id,
                            "strategy_version": contract.version,
                            "state": "DRAFT",
                            "enabled": False,
                        },
                        f"register:{version_key}",
                    )
                definition = state["definitions"].get(contract.strategy_id, {})
                state["definitions"][contract.strategy_id] = {
                    "strategy_id": contract.strategy_id,
                    "name": contract.name,
                    "family": contract.family,
                    "latest_version": contract.version,
                    "versions": sorted({*definition.get("versions", []), contract.version}),
                    "registration_state": "DRAFT",
                    "enabled": False,
                }
            state["updated_at"] = self._now()
            self._write_state(state)
        return {"contracts": len(rows), "registered": registered}

    def _contract_from_module(self, module_name: str) -> StrategyContract:
        module = importlib.import_module(module_name)
        builder = getattr(module, "build_deployment_request", None)
        if not callable(builder):
            raise ValueError("STRATEGY_CONTRACT_BUILDER_MISSING")
        request = builder(lambda: {})
        metadata = request.metadata
        adapter = request.adapter
        adapter_path = f"{adapter.__class__.__module__}.{adapter.__class__.__name__}"
        parameters = dict(metadata.parameters)
        schema = {
            key: {"type": _type_name(value), "required": False}
            for key, value in sorted(parameters.items())
        }
        option_selection = parameters.get("option_selection")
        optional_inputs = ["ARGUS_OPTION_CHAIN"] if isinstance(option_selection, Mapping) else []
        return StrategyContract(
            strategy_id=str(getattr(module, "STRATEGY_ID", metadata.strategy_id)),
            name=str(metadata.name),
            version=str(metadata.version),
            family=str(parameters.get("classification") or module_name.rsplit(".", 2)[-2]).upper(),
            description=(str(getattr(module, "__doc__", "") or metadata.name).strip().splitlines()[0]),
            supported_instruments=tuple(str(item) for item in metadata.supported_markets),
            supported_timeframes=tuple(str(item) for item in metadata.supported_timeframes),
            required_inputs=("COMPLETED_CANDLES", "MARKET_SESSION", "STRATEGY_CONTEXT"),
            optional_inputs=tuple(optional_inputs),
            parameter_schema=schema,
            default_configuration=parameters,
            signal_logic=f"{adapter_path}.evaluate",
            direction_logic=f"{adapter_path}.evaluate",
            invalidation_logic=f"{adapter_path}.evaluate",
            target_logic=f"{adapter_path}.evaluate",
            execution_compatibility=tuple(item.value for item in DeploymentPath),
            guardian_compatibility=True,
            source_module=module_name,
        )

    def save_draft(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        configuration: Mapping[str, Any] | None = None,
        deployment_instance_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            contract = self._version(state, strategy_id, strategy_version)
            current = (
                state["deployments"].get(deployment_instance_id)
                if deployment_instance_id
                else None
            )
            base = (
                deepcopy(current["configuration"])
                if current is not None
                else default_configuration(StrategyContract(
                    **{key: _freeze_contract_value(key, value) for key, value in contract.items() if key in StrategyContract.__dataclass_fields__}
                ))
            )
            merged = _deep_merge(base, configuration or {})
            merged["strategy_id"] = strategy_id
            merged["strategy_version"] = strategy_version
            config = validate_configuration(merged)
            config_hash = canonical_configuration_hash(config)
            instance_id = deployment_instance_id or f"dep_{config_hash[:20]}"
            current = state["deployments"].get(instance_id)
            if current and (
                current["strategy_id"] != strategy_id
                or current["strategy_version"] != strategy_version
            ):
                raise ValueError("DEPLOYMENT_INSTANCE_ID_CONFLICT")
            previous_configuration = current.get("configuration") if current else None
            previous_active = None
            if current:
                if current.get("previous_active"):
                    previous_active = deepcopy(current["previous_active"])
                elif (
                    current.get("active_version") is not None
                    and current.get("runtime_configuration_hash")
                    == current.get("configuration_hash")
                ):
                    previous_active = deepcopy(current)
                    previous_active.pop("previous_active", None)
            material_changes = _material_changes(previous_configuration, config)
            row = {
                "deployment_instance_id": instance_id,
                "name": name or current.get("name") if current else name or contract["name"],
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "configuration": config,
                "configuration_hash": config_hash,
                "state": RuntimeState.DRAFT.value,
                "reason": "AWAITING_EXPLICIT_DEPLOYMENT",
                "enabled": False,
                "runtime_configuration_hash": None,
                "runtime_loaded_at": None,
                "created_at": current.get("created_at") if current else self._now(),
                "updated_at": self._now(),
                "active_version": current.get("active_version") if current else None,
                "deployment_history": list(current.get("deployment_history") or []) if current else [],
                "material_changes": material_changes,
                "previous_active": previous_active,
            }
            state["deployments"][instance_id] = row
            state["updated_at"] = self._now()
            self._write_state(state)
            self._audit("CONFIGURATION_SAVED_AS_DRAFT", _audit_payload(row, old=previous_configuration, new=config), f"draft:{instance_id}:{config_hash}")
            return deepcopy(row)

    def duplicate(self, instance_id: str, *, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            source = self._deployment(self._read_state(), instance_id)
            configuration = _deep_merge(source["configuration"], overrides or {})
            fingerprint = canonical_configuration_hash({
                "source": instance_id,
                "configuration": configuration,
                "at": self._now(),
            })
            return self.save_draft(
                strategy_id=source["strategy_id"],
                strategy_version=source["strategy_version"],
                configuration=configuration,
                deployment_instance_id=f"dep_{fingerprint[:20]}",
                name=f"{source['name']} COPY",
            )

    def deploy(self, instance_id: str, *, expected_configuration_hash: str) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            deployment = self._deployment(state, instance_id)
            if deployment["configuration_hash"] != expected_configuration_hash:
                raise ValueError("CONFIGURATION_HASH_MISMATCH")
            previous = deepcopy(deployment)
            rollback = deepcopy(deployment.get("previous_active") or previous)
            rollback.pop("previous_active", None)
            failed_stage = "VALIDATING"
            receipt: dict[str, Any] | None = None
            try:
                self._deployment_stage(state, deployment, "VALIDATING")
                validate_configuration(deployment["configuration"])
                failed_stage = "SAVING_CONFIGURATION"
                self._deployment_stage(state, deployment, failed_stage)
                history = list(deployment.get("deployment_history") or [])
                version_number = len(history) + 1
                persisted = {
                    "deployment_version": version_number,
                    "configuration_hash": expected_configuration_hash,
                    "configuration": deepcopy(deployment["configuration"]),
                    "activated_at": self._now(),
                }
                history.append(persisted)
                deployment["deployment_history"] = history
                deployment["active_version"] = version_number
                failed_stage = "SYNCHRONIZING_RUNTIME"
                self._deployment_stage(state, deployment, failed_stage)
                runtime = self._load_runtime(deployment)
                loaded_hash = runtime["configuration_hash"]
                failed_stage = "HASH_VERIFICATION"
                self._inject_failure(failed_stage, deployment)
                if loaded_hash != expected_configuration_hash:
                    raise RuntimeError("RUNTIME_HASH_MISMATCH")
                deployment["runtime_configuration_hash"] = loaded_hash
                deployment["runtime_loaded_at"] = runtime["loaded_at"]
                failed_stage = "ACTIVATING"
                self._deployment_stage(state, deployment, failed_stage)
                deployment["state"] = runtime["state"]
                deployment["reason"] = runtime["reason"]
                deployment["enabled"] = deployment["configuration"]["execution"]["enabled"]
                deployment["previous_active"] = None
                deployment["updated_at"] = self._now()
                self._write_state(state)
                receipt = self._receipt(deployment)
                receipt_record = self.receipts.append(
                    "DEPLOYMENT_RECEIPT",
                    receipt,
                    idempotency_key=f"receipt:{instance_id}:{expected_configuration_hash}",
                )
                receipt["deployment_receipt_id"] = receipt_record["record_id"]
            except Exception as error:
                state["deployments"][instance_id] = rollback
                state["updated_at"] = self._now()
                self._write_state(state)
                self._audit(
                    "DEPLOYMENT_FAILED_ROLLED_BACK",
                    {
                        **_audit_payload(rollback),
                        "failed_stage": failed_stage,
                        "error": f"{type(error).__name__}:{error}",
                        "rollback_configuration_hash": rollback.get("configuration_hash"),
                        "retry_available": True,
                    },
                    f"deploy:{instance_id}:{expected_configuration_hash}:failed",
                )
                self._notify(
                    "CRITICAL",
                    f"Deployment failed and rolled back at {failed_stage}",
                    strategy_id=rollback["strategy_id"],
                    strategy_version=rollback["strategy_version"],
                    instance_id=instance_id,
                    destination=rollback["configuration"]["execution"]["path"],
                    key=f"notify:deploy-failed:{instance_id}:{expected_configuration_hash}",
                )
                raise
            if receipt is None:
                raise RuntimeError("DEPLOYMENT_RECEIPT_UNAVAILABLE")
            self._audit("DEPLOYMENT_ACTIVATED", _audit_payload(deployment, stage="ACTIVE", deployment_receipt_id=receipt["deployment_receipt_id"]), f"deploy:{instance_id}:{expected_configuration_hash}:active")
            self._notify(
                "SUCCESS",
                "Strategy deployed successfully; runtime hash verified",
                strategy_id=deployment["strategy_id"],
                strategy_version=deployment["strategy_version"],
                instance_id=instance_id,
                destination=deployment["configuration"]["execution"]["path"],
                key=f"notify:deploy:{instance_id}:{expected_configuration_hash}",
            )
            self._notify(
                "SUCCESS",
                "Strategy runtime activated",
                strategy_id=deployment["strategy_id"],
                strategy_version=deployment["strategy_version"],
                instance_id=instance_id,
                destination=deployment["configuration"]["execution"]["path"],
                key=f"notify:activated:{instance_id}:{expected_configuration_hash}",
            )
            return receipt

    def pause(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            deployment = self._deployment(state, instance_id)
            deployment["state"] = RuntimeState.PAUSED.value
            deployment["reason"] = "PAUSED_BY_OPERATOR"
            deployment["enabled"] = False
            deployment["updated_at"] = self._now()
            self._write_state(state)
            self._audit("STRATEGY_PAUSED", _audit_payload(deployment), f"pause:{instance_id}:{deployment['updated_at']}")
            self._notify(
                "WARNING", "Strategy paused by operator",
                strategy_id=deployment["strategy_id"],
                strategy_version=deployment["strategy_version"],
                instance_id=instance_id,
                destination=deployment["configuration"]["execution"]["path"],
                key=f"notify:pause:{instance_id}:{deployment['updated_at']}",
            )
            return deepcopy(deployment)

    def resume(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            deployment = self._deployment(state, instance_id)
            if deployment["state"] != RuntimeState.PAUSED.value:
                raise ValueError("DEPLOYMENT_NOT_PAUSED")
            if deployment["configuration"]["execution"]["enabled"] is not True:
                raise ValueError("DEPLOYMENT_CONFIGURATION_DISABLED")
            runtime = self._load_runtime(deployment)
            if runtime["configuration_hash"] != deployment["configuration_hash"]:
                raise RuntimeError("RUNTIME_HASH_MISMATCH")
            deployment["runtime_configuration_hash"] = runtime["configuration_hash"]
            deployment["runtime_loaded_at"] = runtime["loaded_at"]
            deployment["state"] = runtime["state"]
            deployment["reason"] = runtime["reason"]
            deployment["enabled"] = True
            deployment["updated_at"] = self._now()
            self._write_state(state)
            self._audit("STRATEGY_RESUMED", _audit_payload(deployment), f"resume:{instance_id}:{deployment['updated_at']}")
            self._notify(
                "SUCCESS", "Strategy resumed by operator",
                strategy_id=deployment["strategy_id"],
                strategy_version=deployment["strategy_version"],
                instance_id=instance_id,
                destination=deployment["configuration"]["execution"]["path"],
                key=f"notify:resume:{instance_id}:{deployment['updated_at']}",
            )
            return deepcopy(deployment)

    def rollback(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            deployment = self._deployment(state, instance_id)
            history = list(deployment.get("deployment_history") or [])
            if len(history) < 2:
                raise ValueError("ROLLBACK_VERSION_UNAVAILABLE")
            target = history[-2]
            deployment["configuration"] = deepcopy(target["configuration"])
            deployment["configuration_hash"] = target["configuration_hash"]
            deployment["deployment_history"] = history[:-1]
            deployment["active_version"] = target["deployment_version"]
            runtime = self._load_runtime(deployment)
            if runtime["configuration_hash"] != target["configuration_hash"]:
                raise RuntimeError("ROLLBACK_RUNTIME_HASH_MISMATCH")
            deployment["runtime_configuration_hash"] = runtime["configuration_hash"]
            deployment["runtime_loaded_at"] = runtime["loaded_at"]
            deployment["state"] = runtime["state"]
            deployment["reason"] = "ROLLBACK_ACTIVE"
            deployment["updated_at"] = self._now()
            self._write_state(state)
            self._audit("DEPLOYMENT_ROLLED_BACK", _audit_payload(deployment), f"rollback:{instance_id}:{target['configuration_hash']}")
            self._notify(
                "WARNING", "Deployment rolled back",
                strategy_id=deployment["strategy_id"],
                strategy_version=deployment["strategy_version"],
                instance_id=instance_id,
                destination=deployment["configuration"]["execution"]["path"],
                key=f"notify:rollback:{instance_id}:{target['configuration_hash']}",
            )
            return self._receipt(deployment)

    def projection(self) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
        runtime_rows = [
            row for row in (self._runtime_provider().get("strategies") or [])
            if isinstance(row, Mapping)
        ]
        runtime_by_instance = {
            str(instance_id): row
            for row in runtime_rows
            for instance_id in (
                row.get("deployment_instance_id"),
                row.get("deployment_id"),
                row.get("instance_id"),
            )
            if instance_id
        }
        runtime_by_strategy: dict[str, list[Mapping[str, Any]]] = {}
        for row in runtime_rows:
            runtime_by_strategy.setdefault(str(row.get("strategy_id")), []).append(row)
        instance_counts: dict[str, int] = {}
        for row in state["deployments"].values():
            strategy_id = str(row["strategy_id"])
            instance_counts[strategy_id] = instance_counts.get(strategy_id, 0) + 1
        receipt_rows = [
            {
                **deepcopy(item.get("payload") or {}),
                "deployment_receipt_id": item.get("record_id"),
            }
            for item in self.receipts.read()
            if item.get("event_type") == "DEPLOYMENT_RECEIPT"
        ]
        deployments = []
        for row in sorted(state["deployments"].values(), key=lambda item: item["created_at"]):
            projected = deepcopy(row)
            source = runtime_by_instance.get(row["deployment_instance_id"])
            if source is None and instance_counts[row["strategy_id"]] == 1:
                candidates = runtime_by_strategy.get(row["strategy_id"]) or []
                source = candidates[0] if len(candidates) == 1 else None
            projected["runtime"] = self._runtime_projection(row, source)
            projected["analytics"] = self._analytics_projection(source, row)
            projected["decision"] = self._decision_projection(source)
            projected["deployment_receipts"] = [
                item for item in receipt_rows
                if item.get("deployment_instance_id") == row["deployment_instance_id"]
            ]
            deployments.append(projected)
        notification_rows = self.notifications.read()
        acknowledged = {
            str((item.get("payload") or {}).get("notification_id"))
            for item in notification_rows
            if item.get("event_type") == "STRATEGY_NOTIFICATION_ACKNOWLEDGED"
        }
        notices = []
        for item in notification_rows:
            if item.get("event_type") != "STRATEGY_NOTIFICATION":
                continue
            payload = deepcopy(item.get("payload") or {})
            payload["acknowledged"] = payload.get("notification_id") in acknowledged
            notices.append(payload)
        notices = notices[-50:]
        audit = self.audit.read(limit=50)
        active = [row for row in deployments if row["state"] not in {RuntimeState.DRAFT.value, RuntimeState.PAUSED.value, RuntimeState.ERROR.value, RuntimeState.OFFLINE.value}]
        return {
            "status": "AVAILABLE",
            "health": "HEALTHY" if not state["registration_errors"] else "DEGRADED",
            "readiness": "READY",
            "generated_at": self._now(),
            "schema_version": SCHEMA_VERSION,
            "definitions": sorted(state["definitions"].values(), key=lambda item: item["name"]),
            "versions": sorted(state["versions"].values(), key=lambda item: (item["name"], item["version"])),
            "deployments": deployments,
            "active_deployments": active,
            "oracle_instances": active,
            "registration_errors": deepcopy(state["registration_errors"]),
            "notifications": notices,
            "receipts": receipt_rows,
            "audit": audit,
            "execution_paths": [item.value for item in DeploymentPath],
            "aggregation_modes": [item.value for item in AggregationMode],
            "configuration_schema": _configuration_schema(),
            "decision_policy": {
                "default_weights": {"price_action": 50, "vob": 25, "strategy_trigger": 25},
                "score_is_probability": False,
                "intelligence_default": "DISPLAY_ONLY",
            },
            "price_action_reuse": {
                "original_source": SOURCE,
                "runtime_dependency_on_oracle_development": False,
                "parity_scope": PARITY_SCOPE,
                "status": "PARITY_TESTED_PORT",
            },
            "safety": {
                "paper_only": True,
                "live_trading_enabled": False,
                "broker_submission": False,
                "new_strategies_auto_deployed": False,
                "oracle_development_mutated": False,
            },
        }

    def deployments(self) -> list[dict[str, Any]]:
        """Return canonical deployment rows for the runtime bridge."""

        with self._lock:
            state = self._read_state()
        return [
            deepcopy(row)
            for row in sorted(
                state["deployments"].values(),
                key=lambda item: item["created_at"],
            )
        ]

    def deployment(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._deployment(self._read_state(), instance_id))

    def version(self, strategy_id: str, strategy_version: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(
                self._version(self._read_state(), strategy_id, strategy_version)
            )

    def acknowledge_notification(self, notification_id: str) -> dict[str, Any]:
        rows = self.notifications.read()
        existing = next((
            item.get("payload") or {}
            for item in rows
            if item.get("event_type") == "STRATEGY_NOTIFICATION"
            and (item.get("payload") or {}).get("notification_id") == notification_id
        ), None)
        if existing is None:
            raise ValueError("STRATEGY_NOTIFICATION_NOT_FOUND")
        self.notifications.append(
            "STRATEGY_NOTIFICATION_ACKNOWLEDGED",
            {
                "notification_id": notification_id,
                "acknowledged": True,
                "acknowledged_at": self._now(),
            },
            idempotency_key=f"ack:{notification_id}",
        )
        return {"notification_id": notification_id, "acknowledged": True}

    def record_runtime_event(
        self,
        instance_id: str,
        event_type: str,
        *,
        details: Mapping[str, Any] | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        severity_by_event = {
            "STALE_DATA": "WARNING",
            "SIGNAL_GENERATED": "SUCCESS",
            "DAILY_RISK_LIMIT_REACHED": "CRITICAL",
            "RUNTIME_HASH_MISMATCH": "CRITICAL",
        }
        normalized = str(event_type).upper()
        if normalized not in severity_by_event:
            raise ValueError("STRATEGY_RUNTIME_EVENT_INVALID")
        with self._lock:
            deployment = deepcopy(self._deployment(self._read_state(), instance_id))
        key = event_id or self._stable_key({
            "instance_id": instance_id,
            "event_type": normalized,
            "details": dict(details or {}),
        })
        self._audit(
            f"STRATEGY_{normalized}",
            {**_audit_payload(deployment), "details": deepcopy(dict(details or {}))},
            f"runtime-event:{key}",
        )
        self._notify(
            severity_by_event[normalized],
            normalized.replace("_", " ").title(),
            strategy_id=deployment["strategy_id"],
            strategy_version=deployment["strategy_version"],
            instance_id=instance_id,
            destination=deployment["configuration"]["execution"]["path"],
            key=f"notify:runtime-event:{key}",
        )
        return {"event_type": normalized, "recorded": True}

    def observe_domain_event(self, event: Any) -> None:
        """Persist operator notifications from real paper lifecycle events."""

        event_type = str(getattr(event, "event_type", "") or "")
        payload = deepcopy(dict(getattr(event, "payload", {}) or {}))
        signal = str(payload.get("signal") or "").upper()
        if event_type == "SignalCreated" and signal != "BUY":
            return
        messages = {
            "SignalCreated": ("SUCCESS", "Strategy signal ready"),
            "MissionCreated": ("SUCCESS", "Paper mission created"),
            "RiskRejected": ("CRITICAL", "Paper risk rejected"),
            "OrderCreated": ("SUCCESS", "Paper order created"),
            "OrderFilled": ("SUCCESS", "Paper fill recorded"),
            "PositionRiskInitialized": ("SUCCESS", "Guardian monitoring active"),
            "PositionRiskUpdated": ("WARNING", "Guardian risk state updated"),
            "PositionClosed": ("SUCCESS", "Paper position exited"),
            "TradeCompleted": ("SUCCESS", "Paper trade completed"),
        }
        selected = messages.get(event_type)
        if selected is None:
            return
        subject = next(
            (
                value
                for key in ("mission", "order", "fill", "position", "trade")
                for value in (payload.get(key),)
                if isinstance(value, Mapping)
            ),
            payload,
        )
        instance_id = (
            subject.get("deployment_instance_id")
            or subject.get("strategy_id")
            or payload.get("strategy_id")
        )
        strategy_id = (
            subject.get("canonical_strategy_id")
            or subject.get("strategy_id")
            or payload.get("strategy_id")
        )
        self._notify(
            selected[0],
            selected[1],
            strategy_id=str(strategy_id) if strategy_id else None,
            strategy_version=(
                str(subject.get("strategy_version"))
                if subject.get("strategy_version")
                else None
            ),
            instance_id=str(instance_id) if instance_id else None,
            destination=(
                str(subject.get("execution_path"))
                if subject.get("execution_path")
                else None
            ),
            key=f"notify:domain:{getattr(event, 'event_id', event_type)}",
        )

    @staticmethod
    def consensus(votes: Mapping[str, str], mode: str, **options: Any) -> dict[str, Any]:
        return aggregate_timeframe_votes(votes, AggregationMode(mode), **options)

    def _deployment_stage(
        self,
        state: dict[str, Any],
        deployment: dict[str, Any],
        stage: str,
    ) -> None:
        deployment["state"] = RuntimeState.DEPLOYING.value
        deployment["reason"] = stage
        deployment["updated_at"] = self._now()
        self._inject_failure(stage, deployment)
        state["updated_at"] = deployment["updated_at"]
        self._write_state(state)
        self._audit(
            "DEPLOYMENT_STAGE",
            _audit_payload(deployment, stage=stage),
            f"deploy:{deployment['deployment_instance_id']}:{deployment['configuration_hash']}:{stage.lower()}",
        )

    def _inject_failure(self, stage: str, deployment: Mapping[str, Any]) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage, deepcopy(dict(deployment)))

    def _load_runtime(self, deployment: Mapping[str, Any]) -> dict[str, Any]:
        path = DeploymentPath(deployment["configuration"]["execution"]["path"])
        enabled = deployment["configuration"]["execution"]["enabled"]
        if path is DeploymentPath.LIVE_DISABLED:
            return {
                "configuration_hash": deployment["configuration_hash"],
                "loaded_at": self._now(),
                "state": RuntimeState.PAUSED.value,
                "reason": "LIVE_EXECUTION_DISABLED",
            }
        state = RuntimeState.OBSERVING
        reason = "CONFIGURATION_HASH_SYNCHRONIZED"
        if path in {DeploymentPath.SIMPLE_SIGNAL_ONLY, DeploymentPath.REPLAY, DeploymentPath.BACKTEST}:
            state = RuntimeState.WAITING_FOR_TRIGGER
            reason = "WAITING_FOR_STRATEGY_TRIGGER"
        elif path in {DeploymentPath.SIMPLE_PAPER, DeploymentPath.ORACLE_PAPER}:
            state = RuntimeState.WAITING_FOR_DATA
            reason = "PAPER_RUNTIME_CONFIGURATION_LOADED"
        elif not enabled:
            state = RuntimeState.PAUSED
            reason = "DEPLOYMENT_DISABLED"
        return {
            "configuration_hash": deployment["configuration_hash"],
            "loaded_at": self._now(),
            "state": state.value,
            "reason": reason,
        }

    @staticmethod
    def _runtime_projection(deployment: Mapping[str, Any], source: Mapping[str, Any] | None) -> dict[str, Any]:
        if source is None:
            return {
                "state": deployment["state"],
                "reason": deployment["reason"],
                "source": "STRATEGY_COMMAND_RUNTIME",
                "configuration_hash_verified": deployment.get("runtime_configuration_hash") == deployment.get("configuration_hash"),
            }
        lifecycle = source.get("lifecycle")
        runtime_state = (
            lifecycle.get("runtime_state")
            if isinstance(lifecycle, Mapping)
            else None
        )
        return {
            "state": runtime_state or source.get("state") or deployment["state"],
            "reason": (
                lifecycle.get("runtime_reason")
                if isinstance(lifecycle, Mapping)
                else None
            )
            or source.get("not_ready_reason")
            or source.get("reason")
            or deployment["reason"],
            "health": source.get("health"),
            "readiness": source.get("readiness"),
            "scheduler": source.get("scheduler"),
            "lifecycle": deepcopy(dict(lifecycle)) if isinstance(lifecycle, Mapping) else None,
            "configuration_hash_verified": deployment.get("runtime_configuration_hash") == deployment.get("configuration_hash"),
            "source": "STRATEGY_LAB_RUNTIME",
        }

    @staticmethod
    def _decision_projection(source: Mapping[str, Any] | None) -> dict[str, Any]:
        decision = source.get("current_decision") if source else None
        if not isinstance(decision, Mapping):
            return {
                "price_action_score": None,
                "vob_score": None,
                "strategy_trigger_score": None,
                "total_score": None,
                "confidence_modifiers": [],
                "blockers": [],
                "warnings": [],
                "why": [],
                "why_not": ["NO_CURRENT_RUNTIME_DECISION"],
                "next_required_condition": "AWAITING COMPLETED CANDLE",
            }
        return {
            "price_action_score": decision.get("price_action_score"),
            "vob_score": decision.get("vob_score"),
            "strategy_trigger_score": decision.get("strategy_score"),
            "total_score": decision.get("total_score"),
            "confidence_modifiers": list(decision.get("confidence_modifiers") or []),
            "blockers": list(decision.get("blockers") or []),
            "warnings": list(decision.get("warnings") or []),
            "why": list(decision.get("why") or []),
            "why_not": list(decision.get("why_not") or []),
            "next_required_condition": decision.get("next_required_condition"),
            "contract_selection": deepcopy(dict(decision.get("contract_selection") or {})),
            "selected_contract": deepcopy(dict(decision.get("option_contract") or {})),
            "evaluated_at": decision.get("evaluated_at"),
        }

    @staticmethod
    def _analytics_projection(source: Mapping[str, Any] | None, deployment: Mapping[str, Any]) -> dict[str, Any]:
        attribution = {
            "strategy_id": deployment["strategy_id"],
            "strategy_version": deployment["strategy_version"],
            "deployment_instance_id": deployment["deployment_instance_id"],
            "instrument": deployment["configuration"]["market"]["instrument"],
            "timeframes": deepcopy(deployment["configuration"]["timeframes"]["roles"]),
            "execution_path": deployment["configuration"]["execution"]["path"],
            "configuration_hash": deployment["configuration_hash"],
        }
        if source is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "NO_INSTANCE_ATTRIBUTED_RUNTIME_RECORDS",
                "sample_size": 0,
                "attribution": attribution,
            }
        lifecycle = source.get("lifecycle")
        stats = (
            lifecycle.get("analytics")
            if isinstance(lifecycle, Mapping)
            and isinstance(lifecycle.get("analytics"), Mapping)
            else source.get("statistics")
        )
        if not isinstance(stats, Mapping):
            return {
                "status": "UNAVAILABLE",
                "reason": "STATISTICS_NOT_REPORTED",
                "sample_size": 0,
                "attribution": attribution,
            }
        return {**deepcopy(dict(stats)), "attribution": attribution}

    @staticmethod
    def _receipt(deployment: Mapping[str, Any]) -> dict[str, Any]:
        config = deployment["configuration"]
        return {
            "status": "STRATEGY_DEPLOYED_SUCCESSFULLY",
            "strategy": deployment["name"],
            "strategy_id": deployment["strategy_id"],
            "strategy_version": deployment["strategy_version"],
            "deployment_instance_id": deployment["deployment_instance_id"],
            "destination": config["execution"]["path"],
            "instrument": config["market"]["instrument"],
            "timeframes": deepcopy(config["timeframes"]["roles"]),
            "lots": config["position"]["fixed_lots"],
            "activation_timestamp": deployment["runtime_loaded_at"],
            "configuration_hash": deployment["configuration_hash"],
            "runtime_configuration_hash": deployment["runtime_configuration_hash"],
            "runtime_status": deployment["state"],
            "runtime_reason": deployment["reason"],
            "deployment_stages": [
                "VALIDATING",
                "SAVING_CONFIGURATION",
                "SYNCHRONIZING_RUNTIME",
                "ACTIVATING",
                "ACTIVE",
            ],
            "hash_verified": deployment["runtime_configuration_hash"] == deployment["configuration_hash"],
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    def _notify(self, severity: str, message: str, *, strategy_id: str | None, strategy_version: str | None, instance_id: str | None, destination: str | None, key: str) -> None:
        notification_id = f"notification_{self._stable_key({'key': key})}"
        self.notifications.append(
            "STRATEGY_NOTIFICATION",
            {
                "notification_id": notification_id,
                "severity": severity,
                "timestamp": self._now(),
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "deployment_instance_id": instance_id,
                "destination": destination,
                "message": message,
                "evidence_link": f"/strategies?instance={instance_id}" if instance_id else "/strategies",
                "acknowledged": False,
            },
            idempotency_key=key,
        )

    def _audit(self, event_type: str, payload: Mapping[str, Any], key: str) -> None:
        self.audit.append(event_type, payload, idempotency_key=key)

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("STRATEGY_COMMAND_STATE_UNAVAILABLE") from error
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("STRATEGY_COMMAND_STATE_INVALID")
        return value

    def _write_state(self, state: Mapping[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.state_path)

    @staticmethod
    def _version(state: Mapping[str, Any], strategy_id: str, version: str) -> dict[str, Any]:
        row = state["versions"].get(f"{strategy_id}@{version}")
        if row is None:
            raise ValueError("STRATEGY_VERSION_NOT_FOUND")
        return row

    @staticmethod
    def _deployment(state: Mapping[str, Any], instance_id: str) -> dict[str, Any]:
        row = state["deployments"].get(instance_id)
        if row is None:
            raise ValueError("DEPLOYMENT_INSTANCE_NOT_FOUND")
        return row

    @staticmethod
    def _contract_fingerprint(row: Mapping[str, Any]) -> str:
        excluded = {"registered_at", "registration_state", "enabled"}
        return canonical_configuration_hash({key: value for key, value in row.items() if key not in excluded})

    def _now(self) -> str:
        return self._clock().isoformat()

    @staticmethod
    def _stable_key(value: Mapping[str, Any]) -> str:
        return canonical_configuration_hash(value)[:24]


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _freeze_contract_value(key: str, value: Any) -> Any:
    if key in {
        "supported_instruments", "supported_timeframes", "required_inputs",
        "optional_inputs", "execution_compatibility",
    }:
        return tuple(value)
    return value


def _deep_merge(base: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _material_changes(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> list[str]:
    if old is None:
        return ["INITIAL_CONFIGURATION"]
    keys = ("execution", "market", "timeframes", "position", "entry", "exit", "guardian")
    return [key.upper() for key in keys if old.get(key) != new.get(key)]


def _audit_payload(row: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "strategy_id": row.get("strategy_id"),
        "strategy_version": row.get("strategy_version"),
        "deployment_instance_id": row.get("deployment_instance_id"),
        "configuration_hash": row.get("configuration_hash"),
        "old_value": extra.pop("old", None),
        "new_value": extra.pop("new", None),
        "timestamp": row.get("updated_at"),
        **extra,
    }


def _configuration_schema() -> dict[str, Any]:
    return {
        "modes": ["SIMPLE", "ADVANCED"],
        "sections": {
            "market": ["instrument", "segment", "expiry_type", "expiry_date", "dte", "option_sides", "moneyness", "strike_offset", "delta_range", "premium_range", "minimum_oi", "minimum_volume", "maximum_spread", "liquidity_rules"],
            "timeframes": ["roles", "aggregation", "weights", "stale_data_threshold_seconds"],
            "position": ["fixed_lots", "maximum_lots", "capital", "fixed_rupee_risk", "capital_percentage_risk", "premium_budget", "maximum_open_positions", "maximum_concurrent_instances"],
            "session": ["first_entry_time", "last_entry_time", "square_off_time", "cooldown_seconds", "re_entry", "maximum_trades_per_day", "daily_loss_limit", "daily_profit_lock", "expiry_day_restrictions", "opening_volatility_restrictions", "custom_no_trade_windows"],
            "entry": ["strategy_trigger", "price_action_requirement", "vob_requirement", "breakout", "retest", "rejection", "candle_close_confirmation", "momentum_requirement", "pullback_depth", "minimum_score", "minimum_rr", "conflict_behaviour"],
            "exit": ["structural_invalidation", "premium_stop_loss", "percentage_stop_loss", "target", "trailing_stop", "breakeven", "partial_exit", "opposite_signal_exit", "vob_failure_exit", "time_exit", "session_exit", "maximum_holding_duration_seconds"],
            "guardian": ["enabled", "timeframe", "breakeven_trigger", "trailing_policy", "partial_exit_policy", "risk_reduction", "invalidation_response", "time_based_protection", "emergency_exit", "advisory_mode", "execution_mode"],
        },
    }
