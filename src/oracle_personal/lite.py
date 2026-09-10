"""Registry-driven, advisory-only Personal Oracle Lite analysis."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.strategy_lab.storage import StrategyRegistryStore

from .ledger import PersonalOracleLedger
from .models import (
    OracleClassification,
    OracleEvent,
    OracleObservation,
    canonical_hash,
    event_id,
)


CLASSIFIER_VERSION = "PERSONAL_ORACLE_LITE_V1"
EXECUTION_DEFECT_REASONS = {
    "CONTRACT_IDENTITY_MISMATCH",
    "DUPLICATE_ORDER_OR_FILL",
    "REJECTED_EXIT",
    "MISSING_AUTHORITATIVE_QUOTE",
    "OPEN_POSITION_NOT_FOUND",
    "OPEN_POSITION_DISAPPEARED",
    "AUTHORITATIVE_EXIT_PRICE_REQUIRED",
}
SESSION_REASONS = {"SESSION_EXIT", "SESSION SQUARE OFF", "SESSION_SQUARE_OFF", "SQUARE OFF"}
RECONCILIATION_REASONS = {"RECONCILIATION", "RECONCILED", "MANUAL_RECONCILIATION"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except (TypeError, ValueError):
        return None


class StrategyLabOracleSource:
    """Read-only adapter over the authoritative Strategy Lab registry and states."""

    def __init__(
        self,
        root: Path | str = "logs/strategy_lab",
        max_trades_per_strategy: int = 10_000,
        max_state_bytes: int = 50_000_000,
        minimum_exit_at: Optional[str] = None,
    ):
        self.root = Path(root).resolve()
        self.max_trades_per_strategy = max_trades_per_strategy
        self.max_state_bytes = max_state_bytes
        configured_minimum = (
            minimum_exit_at
            if minimum_exit_at is not None
            else os.environ.get("CITADEL_PERSONAL_ORACLE_MIN_EXIT_AT")
        )
        self.minimum_exit_at = _iso(configured_minimum)
        self.skipped_sources = 0
        self.invalid_sources = 0

    def strategies(self) -> tuple[dict[str, Any], ...]:
        if not (self.root / "registry.json").exists():
            return ()
        registry = StrategyRegistryStore(self.root)
        return tuple(dict(row) for row in registry.load().get("deployments") or ())

    def records(self) -> Iterable[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
        self.skipped_sources = 0
        self.invalid_sources = 0
        for metadata in self.strategies():
            strategy_id = str(metadata.get("strategy_id") or "")
            path = self.root / "runtimes" / strategy_id / "paper_engine_state.json"
            if not strategy_id or not path.exists():
                continue
            try:
                if path.stat().st_size > self.max_state_bytes:
                    self.skipped_sources += 1
                    continue
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.invalid_sources += 1
                continue
            if not isinstance(state, Mapping):
                self.invalid_sources += 1
                continue
            trades = list(state.get("closed_trades") or ())
            for trade in trades[-self.max_trades_per_strategy :]:
                if isinstance(trade, Mapping):
                    if not self.eligible(trade):
                        self.skipped_sources += 1
                        continue
                    yield metadata, state, trade

    def metadata(self, strategy_id: str) -> Optional[dict[str, Any]]:
        return next((row for row in self.strategies() if str(row.get("strategy_id") or "") == strategy_id), None)

    def eligible(self, trade: Mapping[str, Any]) -> bool:
        if not self.minimum_exit_at:
            return True
        exit_at = _iso(trade.get("exit_time") or trade.get("closed_at"))
        return not exit_at or datetime.fromisoformat(exit_at) > datetime.fromisoformat(self.minimum_exit_at)


class PersonalOracleLite:
    def __init__(
        self,
        ledger: PersonalOracleLedger,
        source: Optional[StrategyLabOracleSource] = None,
        *,
        minimum_pattern_sample: int = 3,
    ):
        self.ledger = ledger
        self.source = source or StrategyLabOracleSource()
        self.minimum_pattern_sample = minimum_pattern_sample

    def discover_strategies(self) -> tuple[dict[str, Any], ...]:
        return self.source.strategies()

    def backfill(self, *, dry_run: bool = False) -> dict[str, int]:
        result = {
            "discovered": 0,
            "valid": 0,
            "inserted": 0,
            "duplicate": 0,
            "skipped": 0,
            "invalid": 0,
        }
        known = {row.oracle_event_id for row in self.ledger.events()}
        pending: list[OracleEvent] = []
        for metadata, state, trade in self.source.records():
            result["discovered"] += 1
            try:
                event = self._event(metadata, state, trade, ingestion_mode="RECONCILED")
            except (KeyError, TypeError, ValueError):
                result["invalid"] += 1
                continue
            result["valid"] += 1
            if event.oracle_event_id in known:
                result["duplicate"] += 1
                continue
            known.add(event.oracle_event_id)
            if dry_run:
                result["inserted"] += 1
            else:
                pending.append(event)
        result["skipped"] += self.source.skipped_sources
        result["invalid"] += self.source.invalid_sources
        if not dry_run:
            for event in pending:
                if self.ledger.append(event):
                    result["inserted"] += 1
                else:
                    result["duplicate"] += 1
            if pending:
                self.refresh_analysis()
        return result

    def ingest_completed_trade(
        self,
        trade: Mapping[str, Any],
        *,
        source_event_id: Optional[str] = None,
    ) -> bool:
        strategy_id = str(trade.get("strategy_id") or "").strip()
        metadata = self.source.metadata(strategy_id)
        if not strategy_id or metadata is None or not self.source.eligible(trade):
            return False
        event = self._event(
            metadata,
            {},
            trade,
            ingestion_mode="EVENT_DRIVEN",
            source_event_id=source_event_id,
        )
        return self.ledger.append(event)

    def import_legacy(self, source_path: Path | str, *, dry_run: bool = False) -> dict[str, int]:
        """Import immutable legacy Oracle events without mutating their source."""

        source = PersonalOracleLedger(Path(source_path))
        result = {
            "discovered": 0,
            "valid": 0,
            "inserted": 0,
            "duplicate": 0,
            "skipped": 0,
            "invalid": 0,
        }
        current = self.ledger.events()
        known_ids = {row.oracle_event_id for row in current}
        known_sources = {
            (row.source_type, row.source_record_id, row.immutable_source_hash)
            for row in current
        }
        pending: list[OracleEvent] = []
        for event in source.events():
            result["discovered"] += 1
            source_key = (event.source_type, event.source_record_id, event.immutable_source_hash)
            if event.oracle_event_id in known_ids or source_key in known_sources:
                result["duplicate"] += 1
                continue
            result["valid"] += 1
            known_ids.add(event.oracle_event_id)
            known_sources.add(source_key)
            if dry_run:
                result["inserted"] += 1
            else:
                pending.append(event)
        if not dry_run:
            for event in pending:
                if self.ledger.append(event):
                    result["inserted"] += 1
                else:
                    result["duplicate"] += 1
            if pending:
                self.refresh_analysis()
        return result

    def refresh_analysis(self) -> tuple[tuple[OracleClassification, ...], tuple[OracleObservation, ...]]:
        events = tuple(sorted(self.ledger.events(), key=lambda row: (row.entry_at, row.oracle_event_id)))
        classifications = self.classify(events)
        observations = self.observe(events, classifications, self.ledger.observations())
        self.ledger.replace_analysis(classifications, observations)
        return classifications, observations

    def classify(self, events: Iterable[OracleEvent]) -> tuple[OracleClassification, ...]:
        generated_at = _now()
        result: list[OracleClassification] = []
        previous_by_strategy: dict[str, OracleEvent] = {}
        for event in events:
            types: list[tuple[str, Mapping[str, Any], float, str]] = []
            reason = " ".join(
                value for value in (event.exit_reason, event.rejection_reason, event.diagnostic_reason) if value
            ).upper()
            defects = [item for item in EXECUTION_DEFECT_REASONS if item in reason]
            if "CONTRACT_IDENTITY_MISMATCH" in defects:
                types.append(("CONTRACT_IDENTITY_MISMATCH", {"reason": reason}, 1.0, "AUTHORITATIVE"))
            if "DUPLICATE_ORDER_OR_FILL" in defects:
                types.append(("DUPLICATE_ORDER_OR_FILL", {"reason": reason}, 1.0, "AUTHORITATIVE"))
            if any(item in reason for item in ("REJECTED_EXIT", "OPEN_POSITION_NOT_FOUND")):
                types.append(("REJECTED_EXIT", {"reason": reason}, 1.0, "AUTHORITATIVE"))
            if any(item in reason for item in ("MISSING_AUTHORITATIVE_QUOTE", "AUTHORITATIVE_EXIT_PRICE_REQUIRED")):
                types.append(("MISSING_AUTHORITATIVE_QUOTE", {"reason": reason}, 1.0, "AUTHORITATIVE"))
            types.append((
                "EXECUTION_DEFECT" if defects else "VALID_STRATEGY_OUTCOME",
                {"diagnostic_reason": event.diagnostic_reason, "rejection_reason": event.rejection_reason},
                1.0 if defects else 0.9,
                "AUTHORITATIVE" if defects else "HIGH",
            ))

            if any(token in reason for token in SESSION_REASONS):
                types.extend([
                    ("SESSION_SQUARE_OFF", {"exit_reason": event.exit_reason}, 1.0, "AUTHORITATIVE"),
                    ("SESSION_EXIT", {"exit_reason": event.exit_reason}, 1.0, "AUTHORITATIVE"),
                ])
            elif any(token in reason for token in RECONCILIATION_REASONS):
                types.append(("RECONCILIATION", {"exit_reason": event.exit_reason}, 1.0, "AUTHORITATIVE"))
            elif event.planned_stop_price is not None and self._price_reached(event, event.planned_stop_price, target=False):
                types.append(("PLANNED_STOP", {"exit": event.exit_price, "stop": event.planned_stop_price}, 0.95, "HIGH"))
            elif event.planned_target_price is not None and self._price_reached(event, event.planned_target_price, target=True):
                types.append(("PLANNED_TARGET", {"exit": event.exit_price, "target": event.planned_target_price}, 0.95, "HIGH"))
            elif (
                event.manual_action_source
                and event.planned_stop_price is not None
                and event.planned_target_price is not None
            ):
                types.append(("EARLY_EXIT", {
                    "exit": event.exit_price,
                    "planned_stop": event.planned_stop_price,
                    "planned_target": event.planned_target_price,
                    "manual_action_source": event.manual_action_source,
                }, 0.9, "HIGH"))
            else:
                types.append(("EXIT_DATA_INSUFFICIENT", {"exit_reason": event.exit_reason}, 0.5, "LIMITED"))
            if (
                event.mfe is not None
                and event.mfe > 0
                and event.realized_pnl < event.mfe * 0.25
            ):
                types.append(("PROFIT_SURRENDER", {
                    "mfe": event.mfe,
                    "realized_pnl": event.realized_pnl,
                }, 0.85, "HIGH"))

            if event.signal_at:
                delay = (
                    datetime.fromisoformat(event.entry_at) - datetime.fromisoformat(event.signal_at)
                ).total_seconds()
                entry_type = "EARLY_ENTRY" if delay < 0 else "LATE_ENTRY" if delay > 180 else "ON_TIME_ENTRY"
                types.append((entry_type, {"signal_to_entry_seconds": delay}, 0.95, "HIGH"))
            if event.entry_reference_price is not None:
                distance = event.entry_price - event.entry_reference_price
                chasing = distance > 0 if event.side in {"BUY", "LONG"} else distance < 0
                if chasing:
                    types.append(("CHASE_ENTRY", {"reference_distance": distance}, 0.9, "HIGH"))

            if event.recommended_quantity is not None:
                sizing = "OVERSIZED" if event.quantity > event.recommended_quantity else "NORMAL_SIZE"
                types.append((sizing, {"quantity": event.quantity, "recommended": event.recommended_quantity}, 1.0, "HIGH"))
            if event.session_compliant is not None:
                types.append((
                    "SESSION_COMPLIANT" if event.session_compliant else "SESSION_VIOLATION",
                    {"time_bucket": event.time_bucket},
                    1.0,
                    "HIGH",
                ))

            strategy_key = event.strategy_id or event.strategy_name or "UNKNOWN"
            previous = previous_by_strategy.get(strategy_key)
            if previous:
                minutes = (
                    datetime.fromisoformat(event.entry_at) - datetime.fromisoformat(previous.exit_at)
                ).total_seconds() / 60
                if 0 <= minutes < 10:
                    types.append(("RAPID_REENTRY", {"minutes_since_previous_exit": minutes}, 1.0, "HIGH"))
                    if previous.outcome == "LOSS":
                        types.append(("LOSS_SEQUENCE_REENTRY", {"previous_event_id": previous.oracle_event_id}, 1.0, "HIGH"))
                    if previous.side == event.side:
                        types.append(("SAME_DIRECTION_REPEAT", {"previous_event_id": previous.oracle_event_id}, 1.0, "HIGH"))
                    if event.setup_tag and event.setup_tag == previous.setup_tag:
                        types.append(("SAME_SETUP_REPEAT", {"previous_event_id": previous.oracle_event_id}, 1.0, "HIGH"))
                if event.cooldown_respected is not None and event.configured_cooldown_seconds is not None:
                    types.append((
                        "COOLDOWN_RESPECTED" if event.cooldown_respected else "COOLDOWN_VIOLATION",
                        {
                            "minutes_since_previous_exit": minutes,
                            "configured_cooldown_seconds": event.configured_cooldown_seconds,
                        },
                        1.0,
                        "HIGH",
                    ))
            previous_by_strategy[strategy_key] = event
            for classification_type, evidence, confidence, quality in types:
                result.append(OracleClassification(
                    classification_id=event_id(event.oracle_event_id, classification_type),
                    source_event_id=event.oracle_event_id,
                    classification_type=classification_type,
                    evidence=evidence,
                    confidence=confidence,
                    evidence_quality=quality,
                    generated_at=generated_at,
                ))
        return tuple(result)

    def observe(
        self,
        events: tuple[OracleEvent, ...],
        classifications: tuple[OracleClassification, ...],
        existing: tuple[OracleObservation, ...] = (),
    ) -> tuple[OracleObservation, ...]:
        event_map = {row.oracle_event_id: row for row in events}
        groups: dict[tuple[str, str], list[OracleClassification]] = defaultdict(list)
        for row in classifications:
            event = event_map[row.source_event_id]
            family = event.strategy_family or "UNCLASSIFIED"
            groups[(row.classification_type, family)].append(row)
        prior = {row.observation_id: row for row in existing}
        active: list[OracleObservation] = []
        now = _now()
        for (classification_type, family), rows in groups.items():
            critical = classification_type in EXECUTION_DEFECT_REASONS | {"EXECUTION_DEFECT"}
            if not critical and len(rows) < self.minimum_pattern_sample:
                continue
            event_rows = [event_map[row.source_event_id] for row in rows]
            impact = round(sum(row.realized_pnl for row in event_rows), 8)
            if not critical and abs(impact) < 1:
                continue
            observation_id = event_id("OBSERVATION", f"{classification_type}|{family}")
            previous = prior.get(observation_id)
            strategies = tuple(sorted({row.strategy_id or "UNKNOWN" for row in event_rows}))
            severity = "CRITICAL" if critical else "POSITIVE" if impact > 0 else "IMPORTANT"
            category = "EXECUTION_HEALTH" if critical else "IMPROVEMENT" if impact > 0 else "RISK"
            title = classification_type.replace("_", " ").title()
            summary = (
                f"{len(rows)} authoritative event(s) in {family}; realized impact {impact:+.2f}. "
                "Advisory only; correlation is not execution authority."
            )
            version = 1
            first_detected = now
            status = "NEW"
            if previous:
                first_detected = previous.first_detected_at
                status = previous.status
                changed = previous.sample_size != len(rows) or previous.actual_realized_impact != impact
                version = previous.version + 1 if changed else previous.version
            active.append(OracleObservation(
                observation_id=observation_id,
                version=version,
                title=title,
                summary=summary,
                category=category,
                severity=severity,
                confidence=min(row.confidence for row in rows),
                sample_size=len(rows),
                affected_strategy_count=len(strategies),
                affected_strategy_ids=strategies,
                strategy_family=family,
                actual_realized_impact=impact,
                hypothetical_impact=None,
                first_detected_at=first_detected,
                last_updated_at=now if previous is None or version != previous.version else previous.last_updated_at,
                evidence_references=tuple(row.source_event_id for row in rows[-20:]),
                status=status,
            ))
        active_ids = {row.observation_id for row in active}
        for observation in existing:
            if observation.observation_id not in active_ids and observation.status != "RESOLVED":
                active.append(replace(observation, status="RESOLVED", version=observation.version + 1, last_updated_at=now))
            elif observation.observation_id not in active_ids:
                active.append(observation)
        return tuple(sorted(active, key=lambda row: (row.status == "RESOLVED", -row.confidence, row.observation_id)))

    def _event(
        self,
        metadata: Mapping[str, Any],
        state: Mapping[str, Any],
        trade: Mapping[str, Any],
        *,
        ingestion_mode: str,
        source_event_id: Optional[str] = None,
    ) -> OracleEvent:
        strategy_id = str(metadata["strategy_id"])
        source_id = str(trade.get("trade_id") or trade.get("position_id") or "").strip()
        entry_at = _iso(trade.get("entry_time") or trade.get("opened_at"))
        exit_at = _iso(trade.get("exit_time") or trade.get("closed_at"))
        if not source_id or not entry_at or not exit_at:
            raise ValueError("completed trade identity and timestamps required")
        lineage = set(trade.get("lineage") or ())
        orders = [
            dict(row) for row in state.get("orders") or ()
            if row.get("position_id") == trade.get("position_id")
            or row.get("order_id") in lineage
            or (
                trade.get("replay_id")
                and row.get("replay_id") == trade.get("replay_id")
            )
        ]
        fills = [
            dict(row) for row in state.get("fills") or ()
            if row.get("order_id") in {order.get("order_id") for order in orders}
            or row.get("fill_id") in lineage
        ]
        opening_fills = [row for row in fills if row.get("position_effect") == "OPEN"]
        closing_fills = [row for row in fills if row.get("position_effect") == "CLOSE"]
        entry_context = dict(trade.get("oracle_entry_context") or {})
        quantity = int(
            sum(int(row.get("quantity") or 0) for row in opening_fills)
            or entry_context.get("quantity")
            or trade.get("closed_quantity")
            or trade.get("raw_quantity")
            or trade.get("quantity")
            or 0
        )
        if quantity <= 0:
            raise ValueError("authoritative quantity unavailable")
        entry = _number(
            trade.get("average_price")
            if trade.get("average_price") is not None
            else trade.get("entry_price") or trade.get("entry") or entry_context.get("entry_price")
        )
        exit_price = _number(trade.get("exit_price") if trade.get("exit_price") is not None else trade.get("exit"))
        pnl = _number(trade.get("realized_pnl"))
        if entry is None or exit_price is None or pnl is None:
            raise ValueError("authoritative prices and pnl required")
        params = dict(metadata.get("parameters") or {})
        symbol = str(entry_context.get("underlying") or entry_context.get("instrument") or params.get("chart_symbol") or (metadata.get("supported_markets") or ["NOT_RECORDED"])[0])
        option_side = str(entry_context.get("option_side") or params.get("option_type") or self._option_side(trade.get("contract"))).upper()
        if option_side not in {"CE", "PE", "NONE", "UNKNOWN"}:
            option_side = "UNKNOWN"
        side = str(trade.get("side") or "LONG").upper()
        direction = 1 if side in {"BUY", "LONG"} else -1
        opened = datetime.fromisoformat(entry_at)
        closed = datetime.fromisoformat(exit_at)
        open_order = next((row for row in orders if row.get("position_effect") == "OPEN"), {})
        close_order = next((row for row in reversed(orders) if row.get("position_effect") == "CLOSE"), {})
        rejection_reasons = sorted({
            str(row.get("rejection_reason"))
            for row in orders
            if row.get("position_effect") == "CLOSE" and row.get("rejection_reason")
        })
        duplicated = len({row.get("order_id") for row in orders}) != len(orders) or len({row.get("fill_id") for row in fills}) != len(fills)
        contracts = {str(row.get("contract")) for row in orders if row.get("contract")}
        diagnostic = "DUPLICATE_ORDER_OR_FILL" if duplicated else "CONTRACT_IDENTITY_MISMATCH" if len(contracts) > 1 else trade.get("diagnostic_reason")
        immutable = {"strategy_id": strategy_id, "trade": dict(trade), "entry_context": entry_context}
        family = str(params.get("strategy_family") or metadata.get("family") or str(metadata.get("name") or strategy_id).split()[0]).upper()
        derived_source_event_id = source_event_id or self._trade_completed_event_id(source_id, str(trade.get("position_id") or ""))
        missing_context = tuple(str(value) for value in entry_context.get("missing_context_fields") or ()) if entry_context else ("ENTRY_CONTEXT_ENVELOPE",)
        context_percentage = _number(entry_context.get("context_completeness_percentage")) or 0.0
        return OracleEvent(
            oracle_event_id=event_id("STRATEGY_LAB_CLOSED_TRADE", f"{strategy_id}|{source_id}"),
            source_type="STRATEGY_LAB_CLOSED_TRADE",
            source_record_id=source_id,
            immutable_source_hash=canonical_hash(immutable),
            captured_at=_now(),
            entry_at=entry_at,
            exit_at=exit_at,
            trading_date=opened.date().isoformat(),
            symbol=symbol,
            instrument_id=str(trade.get("contract") or "") or None,
            option_side=option_side,
            strike=_number(entry_context.get("strike")) if entry_context else _number(params.get("strike")),
            expiry=entry_context.get("expiry") if entry_context else params.get("expiry"),
            side=side,
            quantity=quantity,
            raw_quantity=quantity,
            lot_size=int(open_order["lot_size"]) if open_order.get("lot_size") else None,
            number_of_lots=quantity / int(open_order["lot_size"]) if open_order.get("lot_size") else None,
            entry_price=entry,
            exit_price=exit_price,
            realized_pnl=pnl,
            realized_points=round((exit_price - entry) * direction, 8),
            holding_seconds=max(0.0, (closed - opened).total_seconds()),
            outcome="WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
            exit_reason=str(trade.get("exit_reason") or close_order.get("exit_reason") or "") or None,
            r_multiple=_number(trade.get("rr") or trade.get("realized_r")),
            brokerage=_number(trade.get("entry_fees")) + _number(trade.get("exit_fees")) if _number(trade.get("entry_fees")) is not None and _number(trade.get("exit_fees")) is not None else None,
            slippage=None,
            strategy_name=str(metadata.get("name") or strategy_id),
            strategy_version=str(metadata.get("version") or "NOT_RECORDED"),
            trade_number_of_day=None,
            weekday=opened.strftime("%A"),
            time_bucket=self._time_bucket(opened),
            market_regime=str(entry_context.get("market_regime")) if entry_context.get("market_regime") is not None else None,
            historical_backfill=ingestion_mode != "EVENT_DRIVEN",
            context_complete=bool(entry_context) and context_percentage == 100.0,
            warnings=(),
            signal_at=_iso(trade.get("signal_at") or open_order.get("signal_at")),
            signal_price=_number(entry_context.get("signal_price")),
            entry_reference_price=_number(entry_context.get("reference_price")),
            planned_stop_price=_number(entry_context.get("stop_loss")) if entry_context else _number(trade.get("stop") or open_order.get("protective_stop")),
            planned_target_price=_number(entry_context.get("target")) if entry_context else _number(trade.get("target") or open_order.get("target_price")),
            recommended_quantity=int(open_order["requested_quantity"]) if open_order.get("requested_quantity") else None,
            setup_tag=str(entry_context.get("setup") or trade.get("setup_tag") or params.get("setup_tag") or "") or None,
            strategy_id=strategy_id,
            strategy_family=family,
            asset_class=str(params.get("asset_class") or ("OPTION" if option_side in {"CE", "PE"} else "NOT_RECORDED")),
            timeframe=str(entry_context.get("timeframe") or (metadata.get("supported_timeframes") or ["NOT_RECORDED"])[0]),
            intraday_or_positional=str(params.get("intraday_or_positional") or "NOT_RECORDED"),
            order_id=str(open_order.get("order_id") or "") or None,
            fill_id=str((opening_fills[0] if opening_fills else {}).get("fill_id") or "") or None,
            position_id=str(trade.get("position_id") or "") or None,
            contract_security_id=str(trade.get("contract") or "") or None,
            mfe=_number(trade.get("mfe")),
            mae=_number(trade.get("mae")),
            entry_reason=str(entry_context.get("entry_reason") or trade.get("entry_reason") or open_order.get("exit_reason") or "") or None,
            rejection_reason=";".join(rejection_reasons) or str(trade.get("rejection_reason") or "") or None,
            diagnostic_reason=str(diagnostic or "") or None,
            manual_action_source="PAPER_ORDER" if "MANUAL" in str(trade.get("exit_reason") or "").upper() else None,
            session_compliant=trade.get("session_compliant") if isinstance(trade.get("session_compliant"), bool) else None,
            configured_cooldown_seconds=_number(params.get("cooldown_seconds")),
            ingestion_mode=ingestion_mode,
            source_event_id=derived_source_event_id,
            context_captured=bool(entry_context.get("context_captured")),
            context_completeness_percentage=context_percentage,
            missing_context_fields=missing_context,
            entry_context=entry_context,
        )

    @staticmethod
    def _trade_completed_event_id(trade_id: str, position_id: str) -> str:
        canonical = "|".join(("TradeCompleted", trade_id, position_id or "ROOT"))
        return f"evt_{sha256(canonical.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _price_reached(event: OracleEvent, price: float, *, target: bool) -> bool:
        if event.side in {"BUY", "LONG"}:
            return event.exit_price >= price if target else event.exit_price <= price
        return event.exit_price <= price if target else event.exit_price >= price

    @staticmethod
    def _option_side(contract: Any) -> str:
        value = str(contract or "").upper()
        if " CE" in f" {value}" or value.endswith("CE"):
            return "CE"
        if " PE" in f" {value}" or value.endswith("PE"):
            return "PE"
        return "UNKNOWN"

    @staticmethod
    def _time_bucket(value: datetime) -> str:
        minute = value.hour * 60 + value.minute
        if minute < 615:
            return "OPENING"
        if minute < 720:
            return "MORNING"
        if minute < 840:
            return "MIDDAY"
        return "CLOSING"
