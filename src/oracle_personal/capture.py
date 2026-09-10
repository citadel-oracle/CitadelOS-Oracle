"""Truthful conversion of authoritative completed trades into ORACLE events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from .ledger import PersonalOracleLedger
from .models import OracleEvent, canonical_hash, event_id


IST = ZoneInfo("Asia/Kolkata")


class PersonalOracleCapture:
    def __init__(self, ledger: PersonalOracleLedger):
        self.ledger = ledger

    def capture_closed_trade(
        self,
        raw: Mapping[str, Any],
        *,
        historical: bool = False,
        entry_context: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        source_id = str(raw.get("close_event_id") or "").strip()
        if not source_id or not raw.get("closed_at"):
            raise ValueError("only authoritative completed trades can be captured")
        opened = datetime.fromisoformat(str(raw["opened_at"]))
        closed = datetime.fromisoformat(str(raw["closed_at"]))
        quantity = int(raw["closed_quantity"])
        pnl = float(raw["realized_pnl"])
        direction = 1 if str(raw["side"]).upper() in {"BUY", "LONG"} else -1
        points = (float(raw["exit_price"]) - float(raw["entry_price"])) * direction
        context, context_warning = self._entry_context(entry_context, opened, historical)
        existing = sorted(self.ledger.events(), key=lambda event: (event.entry_at, event.oracle_event_id))
        same_day = [event for event in existing if event.trading_date == opened.astimezone(IST).date().isoformat()]
        previous = existing[-1].outcome if existing else None
        warnings = ["STRATEGY_VERSION_UNAVAILABLE", "COSTS_UNAVAILABLE", "R_MULTIPLE_UNAVAILABLE"]
        if context_warning:
            warnings.append(context_warning)
        if raw.get("option_type") is None:
            warnings.append("OPTION_METADATA_UNAVAILABLE")
        event = OracleEvent(
            oracle_event_id=event_id("PAPER_STATE", source_id),
            source_type="PAPER_STATE",
            source_record_id=source_id,
            immutable_source_hash=canonical_hash(raw),
            captured_at=datetime.now(IST).isoformat(),
            entry_at=opened.isoformat(),
            exit_at=closed.isoformat(),
            trading_date=opened.astimezone(IST).date().isoformat(),
            symbol=str(raw["symbol"]),
            instrument_id=raw.get("instrument_id"),
            option_side=str(raw.get("option_type") or "UNKNOWN").upper(),
            strike=raw.get("strike"), expiry=raw.get("expiry"),
            side=str(raw["side"]).upper(), quantity=quantity,
            raw_quantity=int(raw["raw_quantity"]), lot_size=raw.get("lot_size"),
            number_of_lots=raw.get("number_of_lots"),
            entry_price=float(raw["entry_price"]), exit_price=float(raw["exit_price"]),
            realized_pnl=pnl, realized_points=round(points, 6),
            holding_seconds=max(0.0, (closed - opened).total_seconds()),
            outcome="WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
            exit_reason=str(raw.get("exit_reason") or "") or None,
            r_multiple=None, brokerage=None, slippage=None,
            strategy_name=context.get("strategy_name"), strategy_version=context.get("strategy_version"),
            trade_number_of_day=len(same_day) + 1,
            weekday=opened.astimezone(IST).strftime("%A"),
            time_bucket=self._time_bucket(opened.astimezone(IST)),
            market_regime=context.get("market_regime"), technical_signal=context.get("technical_signal"),
            argus_bias=context.get("argus_bias"), kronos_direction=context.get("kronos_direction"),
            athena_risk_state=context.get("athena_risk_state"), hermes_event_risk=context.get("hermes_event_risk"),
            previous_trade_outcome=previous, historical_backfill=historical,
            context_complete=bool(context) and not context_warning,
            warnings=tuple(sorted(set(warnings))),
            signal_at=context.get("signal_at"),
            entry_reference_price=context.get("entry_reference_price"),
            planned_stop_price=context.get("planned_stop_price"),
            planned_target_price=context.get("planned_target_price"),
            recommended_quantity=context.get("recommended_quantity"),
            technical_bias=context.get("technical_bias"),
            kronos_core_quality=context.get("kronos_core_quality"),
            kronos_alpha_direction=context.get("kronos_alpha_direction"),
            kronos_alpha_uncertainty=context.get("kronos_alpha_uncertainty"),
            kronos_alpha_reversal_risk=context.get("kronos_alpha_reversal_risk"),
            athena_recommendation=context.get("athena_recommendation"),
            athena_utilization=context.get("athena_utilization"),
            setup_tag=context.get("setup_tag"),
        )
        return self.ledger.append(event)

    def backfill(self, trades: Iterable[Any]) -> dict[str, int]:
        result = {"added": 0, "duplicates": 0, "rejected": 0}
        for trade in trades:
            try:
                raw = trade.to_dict() if hasattr(trade, "to_dict") else dict(trade)
                added = self.capture_closed_trade(raw, historical=True)
                result["added" if added else "duplicates"] += 1
            except (TypeError, ValueError, KeyError):
                result["rejected"] += 1
        return result

    @staticmethod
    def _entry_context(context: Optional[Mapping[str, Any]], opened: datetime, historical: bool):
        if historical or not isinstance(context, Mapping):
            return {}, "HISTORICAL_CONTEXT_UNAVAILABLE" if historical else "ENTRY_CONTEXT_UNAVAILABLE"
        captured_at = context.get("captured_at")
        if not captured_at:
            return {}, "ENTRY_CONTEXT_TIMESTAMP_UNAVAILABLE"
        try:
            if datetime.fromisoformat(str(captured_at)) > opened:
                return {}, "FUTURE_CONTEXT_REJECTED"
        except ValueError:
            return {}, "ENTRY_CONTEXT_TIMESTAMP_INVALID"
        allowed = {key: context.get(key) for key in (
            "strategy_name", "strategy_version", "market_regime", "technical_signal",
            "argus_bias", "kronos_direction", "athena_risk_state", "hermes_event_risk"
            , "signal_at", "entry_reference_price", "planned_stop_price", "planned_target_price",
            "recommended_quantity", "technical_bias", "kronos_core_quality", "kronos_alpha_direction",
            "kronos_alpha_uncertainty", "kronos_alpha_reversal_risk", "athena_recommendation",
            "athena_utilization", "setup_tag"
        )}
        return allowed, None

    @staticmethod
    def _time_bucket(value: datetime) -> str:
        minute = value.hour * 60 + value.minute
        if minute < 615: return "OPENING"
        if minute < 720: return "MORNING"
        if minute < 840: return "MIDDAY"
        return "CLOSING"
