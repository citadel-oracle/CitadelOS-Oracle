"""Paper-only market-day decision ledger and bounded soak recorder.

This module observes the existing Oracle projection.  It owns neither market
analysis, risk authorization, execution, nor Guardian state.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Mapping

from src.strategy_lab.storage import ImmutableStream, _atomic_write


SCHEMA_VERSION = "oracle-market-day-ledger-1.0.0"
BLOCKER_POLICY_VERSION = "oracle-blocker-classification-1.0.0"
PAYOFF_POLICY_VERSION = "oracle-payoff-diagnostic-1.0.0"
SOAK_POLICY_VERSION = "oracle-paper-soak-1.0.0"
SAFETY = {
    "paper_only": True,
    "live_trading_enabled": False,
    "broker_submission": False,
    "advisory_only": True,
    "execution_influence": "ZERO",
    "execution_authority": False,
}


class MarketDayError(RuntimeError):
    pass


class BlockerClassification(str, Enum):
    MARKET_REJECTED = "MARKET_REJECTED"
    CONTRACT_REJECTED = "CONTRACT_REJECTED"
    RISK_REJECTED = "RISK_REJECTED"
    DISCIPLINE_REJECTED = "DISCIPLINE_REJECTED"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    STALE_CRITICAL_SOURCE = "STALE_CRITICAL_SOURCE"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    POSITION_ALREADY_OPEN = "POSITION_ALREADY_OPEN"


class PayoffQuality(str, Enum):
    GOOD = "GOOD"
    MARGINAL = "MARGINAL"
    POOR = "POOR"
    NOT_REPORTED = "NOT REPORTED"


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, default=str).encode()).hexdigest()


def _now(clock) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MarketDayError("VERIFIED_TIME_UNAVAILABLE")
    return value.astimezone(timezone.utc).isoformat()


def _numbers(values: Any) -> list[float]:
    result = []
    for value in values or ():
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            continue
    return result


def classify_blocker(decision: Mapping[str, Any], projection: Mapping[str, Any], *, duplicate: bool = False) -> str | None:
    """Return one deterministic primary non-action classification."""
    if _effective_action(decision, projection) in {"BUY", "MANAGE", "EXIT"}:
        return None
    if duplicate:
        return BlockerClassification.DUPLICATE_SUPPRESSED.value
    phase5 = dict(projection.get("phase5") or {})
    if phase5.get("position_id"):
        return BlockerClassification.POSITION_ALREADY_OPEN.value
    reason_codes = {str(item).upper() for item in decision.get("reason_codes") or ()}
    risk_text = " ".join((str(decision.get("risk_conflict") or ""), *sorted(reason_codes))).upper()
    discipline = dict(((projection.get("personal_oracle") or {}).get("second_brain") or {}).get("discipline") or {})
    recommendation = str(discipline.get("recommendation") or "").upper()
    if any(token in risk_text for token in ("RISK_REJECT", "KILL_SWITCH", "DAILY_LOSS", "RISK_LIMIT")):
        return BlockerClassification.RISK_REJECTED.value
    if recommendation in {"NO_TRADE", "COOLDOWN"} and discipline.get("warnings"):
        return BlockerClassification.DISCIPLINE_REJECTED.value
    if "STALE_CRITICAL_SOURCE" in reason_codes or str(decision.get("freshness") or "").upper() == "STALE":
        return BlockerClassification.STALE_CRITICAL_SOURCE.value
    contract_tokens = ("CONTRACT", "OPTION", "SPREAD", "LIQUIDITY", "DELTA", "THETA", "IV_", "OSE_")
    if decision.get("current_contract_rejected") or any(any(token in code for token in contract_tokens) for code in reason_codes):
        return BlockerClassification.CONTRACT_REJECTED.value
    if decision.get("missing_evidence") or any("UNAVAILABLE" in code for code in reason_codes):
        return BlockerClassification.EVIDENCE_UNAVAILABLE.value
    return BlockerClassification.MARKET_REJECTED.value


def _effective_action(decision: Mapping[str, Any], projection: Mapping[str, Any]) -> str:
    center = str(projection.get("sync_state") or "").upper()
    if center == "MANAGE":
        return "MANAGE"
    if center in {"EXIT", "EXITED"}:
        return "EXIT"
    return str(decision.get("action") or "UNAVAILABLE").upper()


def payoff_diagnostic(decision: Mapping[str, Any], *, minimum_rr: float) -> dict[str, Any]:
    entry_band = _numbers(decision.get("entry_band"))
    entry = max(entry_band) if entry_band else None
    stop = decision.get("premium_stop")
    targets = _numbers(decision.get("targets"))
    rr = _numbers(decision.get("resulting_rr"))
    costs = decision.get("costs")
    try:
        stop = float(stop) if stop is not None else None
        costs = float(costs) if costs is not None else None
    except (TypeError, ValueError):
        stop, costs = None, None
    missing = []
    if entry is None: missing.append("EXECUTABLE_ENTRY_UNAVAILABLE")
    if stop is None: missing.append("PREMIUM_STOP_MAPPING_UNAVAILABLE")
    if not targets: missing.append("NATURAL_TARGET_PREMIUM_UNAVAILABLE")
    if costs is None: missing.append("COST_ESTIMATE_UNAVAILABLE")
    if not rr: missing.append("RESULTING_RR_UNAVAILABLE")
    if missing:
        return {"quality": PayoffQuality.NOT_REPORTED.value, "risk_distance": None,
                "nearest_natural_reward_distance": None, "resulting_rr_after_costs": None,
                "reason": ";".join(missing), "minimum_rr_policy_boundary": minimum_rr,
                "policy_version": PAYOFF_POLICY_VERSION, "decision_influence": "ZERO"}
    risk_distance = round(entry - stop, 4)
    rewards = [round(target - entry, 4) for target in targets]
    nearest_reward = min((value for value in rewards if value >= 0), default=max(rewards))
    best_rr = max(rr)
    if risk_distance <= 0 or nearest_reward <= 0 or best_rr <= 0:
        quality, reason = PayoffQuality.POOR.value, "NON_POSITIVE_AUTHORITATIVE_PAYOFF_GEOMETRY"
    elif best_rr >= minimum_rr:
        quality, reason = PayoffQuality.GOOD.value, "MEETS_EXISTING_MINIMUM_RR_POLICY"
    else:
        quality, reason = PayoffQuality.MARGINAL.value, "BELOW_EXISTING_MINIMUM_RR_POLICY"
    return {"quality": quality, "risk_distance": risk_distance,
            "nearest_natural_reward_distance": nearest_reward,
            "resulting_rr_after_costs": best_rr, "reason": reason,
            "minimum_rr_policy_boundary": minimum_rr, "policy_version": PAYOFF_POLICY_VERSION,
            "decision_influence": "ZERO"}


class DecisionLedgerStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.decisions = ImmutableStream(self.root / "decisions.jsonl", max_bytes=1024 * 1024 * 1024, max_files=1)
        self.outcomes = ImmutableStream(self.root / "outcomes.jsonl", max_bytes=1024 * 1024 * 1024, max_files=1)
        self.soaks = ImmutableStream(self.root / "soaks.jsonl", max_bytes=1024 * 1024 * 1024, max_files=1)
        self.providers = ImmutableStream(self.root / "provider_transitions.jsonl", max_bytes=1024 * 1024 * 1024, max_files=1)

    def decision_rows(self) -> list[dict[str, Any]]:
        return self.decisions.read()

    def outcome_rows(self) -> list[dict[str, Any]]:
        return self.outcomes.read()

    def decision(self, decision_id: str) -> dict[str, Any] | None:
        return next((row["payload"] for row in reversed(self.decision_rows())
                     if row["payload"].get("decision_id") == decision_id), None)

    def append_outcome(self, decision_id: str, payload: Mapping[str, Any], *, idempotency_key: str,
                       expected_prior_outcome_hash: str = "GENESIS", recorded_at: str | None = None) -> dict[str, Any]:
        if self.decision(decision_id) is None:
            raise MarketDayError("DECISION_LEDGER_RECORD_UNAVAILABLE")
        allowed = {"outcome_status", "mfe", "mae", "exit_timestamp", "exit_reason",
                   "gross_premium_points", "net_premium_points", "r_multiple", "holding_time_seconds",
                   "capture_efficiency", "source_record_ids", "measured_through"}
        body = {key: _plain(value) for key, value in payload.items() if key in allowed}
        duplicate = next((row for row in self.outcome_rows() if row.get("idempotency_key") == idempotency_key), None)
        if duplicate is not None:
            existing = {key: duplicate["payload"].get(key) for key in allowed if key in duplicate["payload"]}
            if duplicate["payload"].get("decision_id") != decision_id or existing != body:
                raise MarketDayError("OUTCOME_IDEMPOTENCY_CONFLICT")
            return duplicate
        prior = [row for row in self.outcome_rows() if row["payload"].get("decision_id") == decision_id]
        prior_hash = prior[-1]["record_hash"] if prior else "GENESIS"
        if expected_prior_outcome_hash != prior_hash:
            raise MarketDayError("OUTCOME_PRIOR_HASH_CONFLICT")
        body.update({"decision_id": decision_id, "outcome_version": len(prior) + 1,
                     "expected_prior_outcome_hash": expected_prior_outcome_hash,
                     "original_decision_unchanged": True, "schema_version": SCHEMA_VERSION})
        return self.outcomes.append("DECISION_OUTCOME_LINKED", body, recorded_at=recorded_at,
                                    idempotency_key=idempotency_key)

    def verify(self) -> dict[str, Any]:
        return {"decisions": self.decisions.verify(), "outcomes": self.outcomes.verify(),
                "soaks": self.soaks.verify(), "providers": self.providers.verify()}


class MarketDayReadinessService:
    """Read-only observer plus append-only research recorder; no execution dependencies."""

    def __init__(self, root: str | Path, *, minimum_rr: float, clock=None):
        self.root = Path(root)
        self.store = DecisionLedgerStore(self.root / "ledger")
        self.minimum_rr = float(minimum_rr)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.state_path = self.root / "soak_state.json"
        self._lock = RLock()
        self._state = self._restore()
        if self._state.get("active"):
            self._state["restart_recovered"] = True
            _atomic_write(self.state_path, self._state)
        self._latest_compact: dict[str, Any] = {}

    def _restore(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"active": False, "soak_id": None, "started_at": None,
                    "last_provider_hashes": {}, "restart_recovered": False}

    def observe(self, projection: Mapping[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        projection = _plain(projection)
        safety = dict(projection.get("safety") or {})
        if safety != SAFETY:
            raise MarketDayError("SAFETY_STATE_CONFLICT")
        decision = dict(projection.get("decision") or {})
        chart = dict(projection.get("chart_state") or {})
        candle_timestamp = decision.get("candle_timestamp")
        if not decision.get("completed_candle") or not candle_timestamp or not decision.get("decision_id") or not decision.get("content_hash"):
            return {"recorded": False, "reason": "COMPLETED_CANDLE_DECISION_UNAVAILABLE"}
        material = {"decision_id": decision["decision_id"], "decision_hash": decision["content_hash"],
                    "candle_timestamp": candle_timestamp, "instrument": chart.get("instrument"),
                    "timeframe": chart.get("timeframe")}
        material_hash = _hash(material)
        duplicate = any(row["payload"].get("material_hash") == material_hash for row in self.store.decision_rows())
        primary = classify_blocker(decision, projection, duplicate=duplicate)
        payoff = payoff_diagnostic(decision, minimum_rr=self.minimum_rr)
        compact = self._compact(projection, primary, payoff)
        self._latest_compact = compact
        if duplicate:
            return {"recorded": False, "reason": BlockerClassification.DUPLICATE_SUPPRESSED.value,
                    "material_hash": material_hash, "compact": compact}
        option = dict(chart.get("option") or {})
        evidence = dict(decision.get("evidence") or {})
        brain = dict((projection.get("personal_oracle") or {}).get("second_brain") or {})
        record = {
            "schema_version": SCHEMA_VERSION, "decision_id": decision["decision_id"],
            "decision_hash": decision["content_hash"], "material_hash": material_hash,
            "source_hashes": decision.get("source_hashes") or {},
            "decision_timestamp": decision.get("decision_timestamp") or projection.get("generated_timestamp"),
            "instrument": {"symbol": chart.get("instrument", {}).get("underlying"),
                           "security_id": option.get("security_id") or chart.get("instrument", {}).get("security_id"),
                           "underlying_security_id": chart.get("instrument", {}).get("security_id"),
                           "expiry": option.get("expiry"), "strike": option.get("strike"),
                           "side": option.get("option_side"), "timeframe": chart.get("timeframe"),
                           "displayed_contract": option.get("trading_symbol"),
                           "selected_contract": decision.get("exact_contract")},
            "candle_timestamp": candle_timestamp, "candle_freshness": decision.get("freshness"),
            "completed_candle": True, "action": _effective_action(decision, projection),
            "setup_family": decision.get("setup_family"), "trigger": decision.get("trigger"),
            "entry_band": decision.get("entry_band"), "structural_stop": decision.get("structural_stop"),
            "premium_stop": decision.get("premium_stop"), "natural_targets": decision.get("natural_targets"),
            "target_premiums": decision.get("targets") or [], "costs": decision.get("costs"),
            "resulting_rr": decision.get("resulting_rr") or [], "market_thesis": decision.get("market_thesis"),
            "providers": decision.get("provider_lineage") or {},
            "risk_state": {"summary": decision.get("risk_conflict"), "authority": "RiskAuthorizationService"},
            "discipline_state": brain.get("discipline") or {}, "position_guardian_state": projection.get("phase5") or {},
            "knowledge_card_ids": decision.get("knowledge_card_ids") or [],
            "supporting_evidence": evidence.get("supporting") or [],
            "conflicting_evidence": evidence.get("conflicting") or [],
            "missing_evidence": evidence.get("missing") or decision.get("missing_evidence") or [],
            "reason_codes": decision.get("reason_codes") or [], "primary_blocker": primary,
            "payoff_quality": payoff, "execution_authority": False,
            "safety": dict(SAFETY), "original_snapshot_immutable": True,
            "outcomes_append_only": True, "soak_id": self._state.get("soak_id") if self._state.get("active") else None,
        }
        row = self.store.decisions.append("ORACLE_DECISION_RECORDED", record,
                                          recorded_at=str(record["decision_timestamp"]),
                                          idempotency_key=f"decision:{material_hash}")
        if self._state.get("active"):
            self._record_provider_transitions(record, projection)
        return {"recorded": True, "ledger_record_id": row["record_id"], "record_hash": row["record_hash"],
                "material_hash": material_hash, "primary_blocker": primary, "payoff_quality": payoff,
                "latency_ms": round((perf_counter() - started) * 1000, 3), "compact": compact}

    def _record_provider_transitions(self, record: Mapping[str, Any], projection: Mapping[str, Any]) -> None:
        previous = dict(self._state.get("last_provider_hashes") or {})
        telemetry = ((projection.get("health") or {}).get("telemetry") or {})
        for name, provider in dict(record.get("providers") or {}).items():
            digest = _hash(provider)
            if previous.get(name) == digest:
                continue
            self.store.providers.append("PROVIDER_TRANSITION", {
                "soak_id": self._state.get("soak_id"), "provider": name, "state": provider,
                "decision_id": record.get("decision_id"), "candle_timestamp": record.get("candle_timestamp"),
                "latency": telemetry.get(f"{name.lower()}_retrieval") or {},
            }, idempotency_key=f"provider:{self._state.get('soak_id')}:{name}:{digest}")
            previous[name] = digest
        self._state["last_provider_hashes"] = previous
        _atomic_write(self.state_path, self._state)

    def _compact(self, projection: Mapping[str, Any], primary: str | None, payoff: Mapping[str, Any]) -> dict[str, Any]:
        decision = dict(projection.get("decision") or {})
        chart = dict(projection.get("chart_state") or {})
        providers = dict(decision.get("provider_lineage") or {})
        discipline = dict(((projection.get("personal_oracle") or {}).get("second_brain") or {}).get("discipline") or {})
        blockers = [primary] if primary else []
        blockers += [str(item) for item in decision.get("reason_codes") or () if str(item) not in blockers]
        entry = _numbers(decision.get("entry_band"))
        targets = _numbers(decision.get("targets"))
        rr = _numbers(decision.get("resulting_rr"))
        return {
            "market": decision.get("market_state") or "NOT REPORTED", "freshness": decision.get("freshness") or "NOT REPORTED",
            "authority": "ORACLE_DECISION_ENVELOPE", "decision": _effective_action(decision, projection),
            "contract": decision.get("exact_contract") or decision.get("displayed_option") or "NOT REPORTED",
            "security_id": decision.get("current_security_id") or (chart.get("instrument") or {}).get("security_id"),
            "timeframe": chart.get("timeframe") or "NOT REPORTED", "trigger": decision.get("trigger") or "NOT REPORTED",
            "entry": max(entry) if entry else None, "sl": decision.get("premium_stop"),
            "t1": targets[0] if targets else None, "t2": targets[1] if len(targets) > 1 else None,
            "rr_after_costs": max(rr) if rr else None,
            "states": {"PA": decision.get("market_thesis", {}).get("direction") if isinstance(decision.get("market_thesis"), dict) else "NOT REPORTED",
                       "ARGUS": (providers.get("ARGUS") or {}).get("state", "NOT REPORTED"),
                       "VOB": (providers.get("VOB") or {}).get("state", "NOT REPORTED"),
                       "OSE": (providers.get("OSE") or {}).get("state", "NOT REPORTED"),
                       "Risk": "REJECTED" if primary == BlockerClassification.RISK_REJECTED.value else "ADVISORY",
                       "Discipline": discipline.get("recommendation") or "NOT REPORTED"},
            "payoff_quality": dict(payoff), "blockers": blockers[:3],
            "decision_change_event": self._change_event(primary, decision),
            "expand": ["WHY", "DETAILS", "PROOF"], "execution_authority": False,
        }

    @staticmethod
    def _change_event(primary: str | None, decision: Mapping[str, Any]) -> str:
        mapping = {
            BlockerClassification.STALE_CRITICAL_SOURCE.value: "A fresh completed candle and all critical provider timestamps become FRESH",
            BlockerClassification.EVIDENCE_UNAVAILABLE.value: "All listed mandatory missing evidence becomes available",
            BlockerClassification.CONTRACT_REJECTED.value: "An exact fresh liquid option contract passes OSE/ARGUS capture gates",
            BlockerClassification.RISK_REJECTED.value: "A new deterministic risk state permits a fresh request",
            BlockerClassification.DISCIPLINE_REJECTED.value: "Objective cooldown/discipline evidence clears",
            BlockerClassification.POSITION_ALREADY_OPEN.value: "The authoritative paper position exits and reconciles",
            BlockerClassification.MARKET_REJECTED.value: str(decision.get("trigger") or "The exact structural trigger completes"),
        }
        return mapping.get(primary, "A materially changed completed-candle Decision Envelope is published")

    def scan(self, projection: Mapping[str, Any]) -> dict[str, Any]:
        decision = dict(projection.get("decision") or {})
        primary = classify_blocker(decision, projection)
        payoff = payoff_diagnostic(decision, minimum_rr=self.minimum_rr)
        return self._compact(projection, primary, payoff)

    def command(self, command: str, projection: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        normalized = str(command or "").strip().upper()
        if normalized in {"", ".", "NOW", "SCAN"}:
            return {"command": normalized or "SCAN", "output": self.scan(projection), "side_effect_free": True}
        if normalized == "SOAK START":
            return self.start_soak(projection, idempotency_key=idempotency_key)
        if normalized == "SOAK STATUS":
            return self.soak_status()
        if normalized == "SOAK STOP":
            return self.stop_soak(projection, idempotency_key=idempotency_key)
        if normalized in {"WHY", "DETAILS", "PROOF"}:
            decision = dict(projection.get("decision") or {})
            key = "why_proof" if normalized == "PROOF" else "why" if normalized == "WHY" else None
            return {"command": normalized, "decision_id": decision.get("decision_id"),
                    "output": decision if key is None else decision.get(key), "side_effect_free": True}
        raise MarketDayError("UNSUPPORTED_MARKET_DESK_COMMAND")

    def start_soak(self, projection: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if self._state.get("active"):
                return self.soak_status()
            now = _now(self.clock)
            soak_id = "soak_" + _hash({"at": now, "idempotency_key": idempotency_key})[:24]
            protected_hash = self._protected_state_hash(projection)
            self._state = {"active": True, "soak_id": soak_id, "started_at": now, "stopped_at": None,
                           "start_decision_count": len(self.store.decision_rows()), "last_provider_hashes": {},
                           "protected_state_hash_before": protected_hash, "restart_recovered": False}
            _atomic_write(self.state_path, self._state)
            row = self.store.soaks.append("SOAK_STARTED", {**self._state, "policy_version": SOAK_POLICY_VERSION,
                "completed_candles_only": True, "risk_authorization_calls": 0, "order_submission_calls": 0,
                "safety": SAFETY}, recorded_at=now, idempotency_key=idempotency_key)
            return {"command": "SOAK START", "status": "ACTIVE", "soak_id": soak_id,
                    "event_hash": row["record_hash"], "safety": SAFETY}

    def soak_status(self) -> dict[str, Any]:
        soak_id = self._state.get("soak_id")
        decisions = [row for row in self.store.decision_rows() if row["payload"].get("soak_id") == soak_id]
        return {"command": "SOAK STATUS", "status": "ACTIVE" if self._state.get("active") else "STOPPED",
                "soak_id": soak_id, "started_at": self._state.get("started_at"),
                "decisions_recorded": len(decisions), "restart_recovered": self._state.get("restart_recovered", False),
                "completed_candles_only": True, "risk_authorization_calls": 0, "order_submission_calls": 0,
                "bounded_waits": True, "safety": SAFETY}

    def stop_soak(self, projection: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {"command": "SOAK STOP", "status": "NOT_ACTIVE", "report": self.report(self._state.get("soak_id"))}
            stopped = _now(self.clock)
            after = self._protected_state_hash(projection)
            self._state.update({"active": False, "stopped_at": stopped, "protected_state_hash_after": after})
            _atomic_write(self.state_path, self._state)
            report = self.report(self._state.get("soak_id"))
            report["safety_no_mutation"] = {
                "before_hash": self._state.get("protected_state_hash_before"), "after_hash": after,
                "unchanged": self._state.get("protected_state_hash_before") == after,
                "risk_authorization_calls": 0, "order_submission_calls": 0,
            }
            row = self.store.soaks.append("SOAK_STOPPED", {"soak_id": self._state.get("soak_id"),
                "stopped_at": stopped, "report_hash": _hash(report), "safety_no_mutation": report["safety_no_mutation"]},
                recorded_at=stopped, idempotency_key=idempotency_key)
            return {"command": "SOAK STOP", "status": "STOPPED", "event_hash": row["record_hash"], "report": report}

    def report(self, soak_id: str | None) -> dict[str, Any]:
        rows = [row for row in self.store.decision_rows() if row["payload"].get("soak_id") == soak_id]
        decisions = [row["payload"] for row in rows]
        outcome_rows = self.store.outcome_rows()
        outcomes = [row["payload"] for row in outcome_rows
                    if any(item.get("decision_id") == row["payload"].get("decision_id") for item in decisions)]
        outcome_by_id = {item["decision_id"]: item for item in outcomes}
        missed = [item["decision_id"] for item in decisions if item.get("action") != "BUY"
                  and (outcome_by_id.get(item["decision_id"]) or {}).get("outcome_status") == "TARGET_BEFORE_STOP"]
        avoided = [item["decision_id"] for item in decisions if item.get("action") != "BUY"
                   and (outcome_by_id.get(item["decision_id"]) or {}).get("outcome_status") == "STOP_BEFORE_TARGET"]
        latencies = [row["payload"].get("latency") or {} for row in self.store.providers.read()
                     if row["payload"].get("soak_id") == soak_id]
        return {"soak_id": soak_id, "complete_decision_ledger": decisions,
                "accepted_paper_candidates": [item["decision_id"] for item in decisions if item.get("action") == "BUY"],
                "blocked_decisions_by_reason": dict(Counter(item.get("primary_blocker") for item in decisions if item.get("primary_blocker"))),
                "later_outcomes": outcomes, "mfe": [item.get("mfe") for item in outcomes if item.get("mfe") is not None],
                "mae": [item.get("mae") for item in outcomes if item.get("mae") is not None],
                "winners_missed": missed, "losers_avoided": avoided,
                "payoff_quality_distribution": dict(Counter((item.get("payoff_quality") or {}).get("quality") for item in decisions)),
                "provider_freshness_transitions": [row["payload"] for row in self.store.providers.read()
                    if row["payload"].get("soak_id") == soak_id], "latency_breakdown": latencies,
                "ledger_integrity": self.store.verify(), "safety": SAFETY}

    @staticmethod
    def _protected_state_hash(projection: Mapping[str, Any]) -> str:
        phase5 = dict(projection.get("phase5") or {})
        durable = {key: phase5.get(key) for key in (
            "condition_id", "condition_state", "condition_version", "trigger_id", "revalidation_id",
            "authorization_id", "order", "paper_order_state", "position_id", "protection",
            "guardian_action", "latest_event_hash", "paper_only", "live_trading_enabled", "broker_submission",
        )}
        return _hash({"phase5_durable": durable, "safety": projection.get("safety") or {}})

    def readiness(self, projection: Mapping[str, Any], *, env_path: str | Path,
                  dhan_authentication: Mapping[str, Any] | None = None) -> dict[str, Any]:
        decision = dict(projection.get("decision") or {})
        providers = dict(decision.get("provider_lineage") or {})
        health = dict(projection.get("health") or {})
        personal = dict(projection.get("personal_oracle") or {})
        checks = {
            "canonical_env": {"status": "AVAILABLE" if Path(env_path).is_file() else "UNAVAILABLE", "credentials_exposed": False},
            "dhan_authentication": {**dict(dhan_authentication or {"status": "NOT_CHECKED",
                                    "proof": "STARTUP_READ_ONLY_PROBE_NOT_RUN"}), "credentials_exposed": False},
            "tradingview_context": {"status": (projection.get("chart_state") or {}).get("availability", "UNAVAILABLE")},
            "oracle_runtime": {"status": "AVAILABLE" if health.get("worker_alive") else "UNAVAILABLE"},
            "sse_transport": {"status": "AVAILABLE" if health.get("push_transport") == "SSE_PRIMARY_POLLING_FALLBACK" else "UNAVAILABLE"},
            "providers": {name: {"status": value.get("state"), "freshness": value.get("freshness")} for name, value in providers.items()},
            "risk_discipline": {"risk": "AVAILABLE", "discipline": personal.get("cooldown_status") or "UNAVAILABLE"},
            "position_guardian": {"position": (projection.get("phase5") or {}).get("position_id") or "NONE",
                                  "guardian": (projection.get("phase5") or {}).get("guardian_health") or "UNAVAILABLE"},
            "knowledge_personal_obsidian": {"knowledge": (projection.get("knowledge") or {}).get("status", "UNAVAILABLE"),
                "personal_oracle": "AVAILABLE" if personal.get("available") else "UNAVAILABLE",
                "obsidian": personal.get("obsidian_sync_status") or "UNAVAILABLE"},
        }
        critical = (checks["canonical_env"]["status"], checks["dhan_authentication"]["status"],
                    checks["tradingview_context"]["status"],
                    checks["oracle_runtime"]["status"], checks["sse_transport"]["status"])
        startup_ready = all(item == "AVAILABLE" for item in critical)
        provider_rows = list(checks["providers"].values())
        market_data_ready = bool(provider_rows) and all(item.get("freshness") == "FRESH" for item in provider_rows)
        status = ("READY" if startup_ready and market_data_ready else
                  "MARKET_HOURS_GATE_PENDING" if startup_ready else "DEGRADED")
        return {"status": status, "startup_status": "READY" if startup_ready else "DEGRADED",
                "market_hours_data_status": "READY" if market_data_ready else "WAITING_FOR_FRESH_CRITICAL_PROVIDERS",
                "soak_recorder_may_start": startup_ready,
                "paper_candidate_acceptance": "PERMITTED_ONLY_AFTER_FRESH_GATES" if startup_ready else "BLOCKED",
                "checks": checks, "safety": SAFETY, "secrets_exposed": False,
                "policy_version": SOAK_POLICY_VERSION}
