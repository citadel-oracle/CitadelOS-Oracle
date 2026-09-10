"""Deterministic, paper-only Oracle trade planning and risk governance."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
import hashlib
import math
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


class TradePlanError(ValueError):
    """A truthful planning rejection with stable machine-readable reasons."""

    def __init__(self, *reasons: str):
        self.reasons = tuple(sorted(set(reasons or ("PLAN_UNAVAILABLE",))))
        super().__init__(", ".join(self.reasons))


class OracleTradePlanner:
    """Creates one advisory plan from persisted evaluation and cached facts."""

    OPTION_MAX_LOTS = 1
    MAX_SPREAD_PERCENT = 1.0
    ENTRY_CUTOFF = time(15, 0)
    TIME_EXIT = "15:20:00 Asia/Kolkata"
    TRAIL_RULE = "AFTER_TARGET_1_MOVE_STOP_TO_ENTRY; TRAIL_BY_INITIAL_RISK"
    DEMO_MAX_LOTS = 5
    DEMO_MAX_HOLD_SECONDS = 90

    @classmethod
    def create(
        cls,
        *,
        mission_id: str,
        evaluation: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        reserved_risk: float,
        reserved_capital: float,
        now: datetime,
        requested_quantity: Optional[int] = None,
    ) -> dict[str, Any]:
        if not isinstance(evaluation, Mapping) or not isinstance(snapshot, Mapping):
            raise TradePlanError("PLANNING_INPUT_UNAVAILABLE")
        gate = evaluation.get("gate_result")
        if not isinstance(gate, Mapping):
            raise TradePlanError("GATE_RESULT_UNAVAILABLE")
        decision = gate.get("decision")
        if decision == "NO_TRADE":
            raise TradePlanError("GATE_NO_TRADE")
        if decision not in {"CALL", "PUT", "EQUITY"}:
            raise TradePlanError("GATE_DECISION_UNSUPPORTED")
        if (
            gate.get("execution_allowed") is not False
            or gate.get("probability") is not None
        ):
            raise TradePlanError("GATE_SAFETY_BOUNDARY_INVALID")

        now_ist = cls._aware(now).astimezone(IST)
        if now_ist.time() >= cls.ENTRY_CUTOFF:
            raise TradePlanError("ENTRY_CUTOFF_REACHED")
        cls._require_fresh(snapshot)
        risk, limits, paper = cls._risk_context(snapshot)
        cls._risk_blocks(risk, limits, paper)

        if decision in {"CALL", "PUT"}:
            instrument = cls._option_instrument(snapshot, decision, now_ist.date())
            policy = "INDEX_OPTION"
            maximum_units = instrument["lot_size"] * cls.OPTION_MAX_LOTS
        else:
            instrument = cls._equity_instrument(snapshot, now_ist.date())
            policy = "EQUITY"
            maximum_units = cls._positive_int(
                limits.get("max_position_quantity")
                or limits.get("max_raw_quantity"),
                "MAX_POSITION_QUANTITY_UNAVAILABLE",
            )
        cls._validate_quote_age(
            instrument["quote_timestamp"],
            now_ist,
            limits,
        )

        structural = cls._structural_risk(
            instrument=instrument,
            snapshot=snapshot,
            decision=decision,
        )
        budget = cls._risk_budget(
            limits=limits,
            paper=paper,
            reserved_risk=reserved_risk,
        )
        risk_per_unit = structural["maximum_entry"] - structural["final_stop"]
        if risk_per_unit <= 0:
            raise TradePlanError("NON_POSITIVE_RISK_DISTANCE")
        risk_per_lot = risk_per_unit * instrument["lot_size"]
        affordable_lots = math.floor(budget / risk_per_lot)
        approved_lots = min(
            affordable_lots,
            maximum_units // instrument["lot_size"],
        )
        approved_quantity = approved_lots * instrument["lot_size"]
        if requested_quantity is not None:
            if (
                isinstance(requested_quantity, bool)
                or not isinstance(requested_quantity, int)
                or requested_quantity <= 0
                or requested_quantity % instrument["lot_size"] != 0
            ):
                raise TradePlanError("REQUESTED_QUANTITY_INVALID")
            approved_quantity = min(approved_quantity, requested_quantity)
        if approved_quantity <= 0:
            raise TradePlanError("INSUFFICIENT_RISK_BUDGET", "ZERO_APPROVED_QUANTITY")

        capital_required = structural["maximum_entry"] * approved_quantity
        available_capital = cls._available_capital(paper) - reserved_capital
        if available_capital < capital_required:
            raise TradePlanError("INSUFFICIENT_AVAILABLE_CAPITAL")
        total_risk = risk_per_unit * approved_quantity
        target_1 = structural["maximum_entry"] + risk_per_unit
        target_2 = structural["maximum_entry"] + 2.0 * risk_per_unit

        return {
            "schema_version": 1,
            "plan_id": "oracle_plan_"
            + hashlib.sha256(
                f"{mission_id}:{evaluation['snapshot_hash']}".encode("utf-8")
            ).hexdigest()[:24],
            "mission_id": mission_id,
            "evaluation_snapshot_hash": evaluation["snapshot_hash"],
            "status": "APPROVED",
            "underlying": instrument["underlying"],
            "instrument_type": instrument["instrument_type"],
            "policy": policy,
            "contract": instrument["contract"],
            "security_id": instrument["security_id"],
            "expiry": instrument["expiry"],
            "dte": instrument["dte"],
            "strike": instrument["strike"],
            "option_type": instrument["option_type"],
            "lot_size": instrument["lot_size"],
            "ltp": cls._money(instrument["ltp"]),
            "entry_zone": {
                "low": cls._money(instrument["bid"]),
                "high": cls._money(instrument["ask"]),
                "source": "CACHED_AUTHORITATIVE_BID_ASK",
            },
            "maximum_entry": cls._money(structural["maximum_entry"]),
            "structural_invalidation": cls._money(
                structural["structural_invalidation"]
            ),
            "mapped_premium_sl": cls._optional_money(
                structural["mapped_premium_stop"]
            ),
            "noise_allowance": cls._money(structural["noise_allowance"]),
            "risk_cap_sl": cls._money(
                structural["maximum_entry"]
                - budget / instrument["lot_size"]
            ),
            "final_sl": cls._money(structural["final_stop"]),
            "stop_selection_rule": "STRUCTURAL_STOP_ONLY; RISK_CAP_REDUCES_QUANTITY_OR_REJECTS; NO_AVERAGING",
            "target_1": cls._money(target_1),
            "target_2": cls._money(target_2),
            "trail_start": cls._money(target_1),
            "trail_rule": cls.TRAIL_RULE,
            "time_exit": cls.TIME_EXIT,
            "risk_per_lot": cls._money(risk_per_lot),
            "approved_quantity": approved_quantity,
            "approved_lots": approved_quantity // instrument["lot_size"],
            "maximum_approved_quantity": approved_lots
            * instrument["lot_size"],
            "total_maximum_risk": cls._money(total_risk),
            "capital_reserved": cls._money(capital_required),
            "risk_budget": cls._money(budget),
            "reward_risk": 2.0,
            "rejection_reasons": [],
            "planning_timestamp": now_ist.isoformat(),
            "quote_timestamp": instrument["quote_timestamp"],
            "contract_locked": True,
            "averaging_down_allowed": False,
            "execution_allowed": False,
            "execution_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    @classmethod
    def create_demo(
        cls,
        *,
        mission_id: str,
        snapshot: Mapping[str, Any],
        option_type: str,
        lots: int,
        now: datetime,
    ) -> dict[str, Any]:
        side = str(option_type).upper()
        if side not in {"CE", "PE"}:
            raise TradePlanError("DEMO_OPTION_TYPE_INVALID")
        if isinstance(lots, bool) or not isinstance(lots, int) or not 1 <= lots <= cls.DEMO_MAX_LOTS:
            raise TradePlanError("DEMO_LOTS_INVALID")
        now_ist = cls._aware(now).astimezone(IST)
        if now_ist.time() >= cls.ENTRY_CUTOFF:
            raise TradePlanError("ENTRY_CUTOFF_REACHED")
        cls._require_fresh(snapshot)
        risk, limits, paper = cls._risk_context(snapshot)
        if risk.get("risk_state_available") is not True:
            raise TradePlanError("RISK_STATE_UNAVAILABLE")
        if risk.get("kill_switch_active") is not False:
            raise TradePlanError("KILL_SWITCH_BLOCKED")
        if paper.get("state_health") != "HEALTHY":
            raise TradePlanError("PAPER_STATE_UNAVAILABLE")
        if cls._nonnegative_int(
            paper.get("open_position_count"), "OPEN_POSITION_COUNT_UNAVAILABLE"
        ) > 0:
            raise TradePlanError("POSITION_ALREADY_OPEN")
        decision = "CALL" if side == "CE" else "PUT"
        instrument = cls._option_instrument(snapshot, decision, now_ist.date())
        cls._validate_quote_age(instrument["quote_timestamp"], now_ist, limits)
        structural = cls._structural_risk(
            instrument=instrument, snapshot=snapshot, decision=decision
        )
        risk_per_unit = structural["maximum_entry"] - structural["final_stop"]
        if risk_per_unit <= 0:
            raise TradePlanError("NON_POSITIVE_RISK_DISTANCE")
        quantity = int(instrument["lot_size"]) * lots
        risk_per_lot = risk_per_unit * int(instrument["lot_size"])
        total_risk = risk_per_unit * quantity
        target_1 = structural["maximum_entry"] + risk_per_unit
        target_2 = structural["maximum_entry"] + 2 * risk_per_unit
        snapshot_hash = hashlib.sha256(
            repr(sorted(snapshot.keys())).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": 1,
            "plan_id": "oracle_demo_" + hashlib.sha256(
                f"{mission_id}:{side}:{lots}:{snapshot_hash}".encode()
            ).hexdigest()[:24],
            "mission_id": mission_id,
            "evaluation_snapshot_hash": snapshot_hash,
            "status": "APPROVED",
            "underlying": instrument["underlying"],
            "instrument_type": "OPTION",
            "policy": "DEMO_INDEX_OPTION",
            "contract": instrument["contract"],
            "security_id": instrument["security_id"],
            "expiry": instrument["expiry"],
            "dte": instrument["dte"],
            "strike": instrument["strike"],
            "option_type": side,
            "lot_size": instrument["lot_size"],
            "ltp": cls._money(instrument["ltp"]),
            "entry_zone": {"low": cls._money(instrument["bid"]), "high": cls._money(instrument["ask"]), "source": "CACHED_AUTHORITATIVE_BID_ASK"},
            "maximum_entry": cls._money(structural["maximum_entry"]),
            "structural_invalidation": cls._money(structural["structural_invalidation"]),
            "mapped_premium_sl": cls._optional_money(structural["mapped_premium_stop"]),
            "noise_allowance": cls._money(structural["noise_allowance"]),
            "risk_cap_sl": None,
            "final_sl": cls._money(structural["final_stop"]),
            "stop_selection_rule": "STRUCTURAL_STOP_ONLY; DEMO_RISK_DISPLAY_ONLY",
            "target_1": cls._money(target_1),
            "target_2": cls._money(target_2),
            "trail_start": cls._money(target_1),
            "trail_rule": cls.TRAIL_RULE,
            "time_exit": "90_SECONDS_AFTER_VERIFIED_FILL",
            "max_hold_seconds": cls.DEMO_MAX_HOLD_SECONDS,
            "risk_per_lot": cls._money(risk_per_lot),
            "approved_quantity": quantity,
            "approved_lots": lots,
            "maximum_approved_quantity": quantity,
            "total_maximum_risk": cls._money(total_risk),
            "simulated_risk": cls._money(total_risk),
            "capital_reserved": 0.0,
            "risk_budget": None,
            "reward_risk": 2.0,
            "rejection_reasons": [],
            "planning_timestamp": now_ist.isoformat(),
            "quote_timestamp": instrument["quote_timestamp"],
            "contract_locked": True,
            "averaging_down_allowed": False,
            "execution_origin": "DEMO_PAPER",
            "directional_edge": "NOT_CLAIMED",
            "exclude_from_strategy_stats": True,
            "exclude_from_backtests": True,
            "exclude_from_performance_metrics": True,
            "production_capital_reservation": False,
            "execution_allowed": False,
            "execution_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }

    @classmethod
    def _option_instrument(
        cls,
        snapshot: Mapping[str, Any],
        decision: str,
        today: date,
    ) -> dict[str, Any]:
        execution = cls._execution(snapshot)
        ose = cls._mapping(
            execution.get("options_structure"), "OSE_UNAVAILABLE"
        )
        if ose.get("status") != "LIVE" or ose.get("source_freshness") not in {
            "LIVE",
            "AVAILABLE",
        }:
            raise TradePlanError("OSE_NOT_LIVE")
        side = "CE" if decision == "CALL" else "PE"
        envelope = cls._mapping(
            cls._mapping(ose.get("contracts"), "OSE_CONTRACTS_UNAVAILABLE").get(
                side
            ),
            f"OSE_{side}_UNAVAILABLE",
        )
        contract = cls._mapping(
            envelope.get("contract"), f"OSE_{side}_CONTRACT_UNAVAILABLE"
        )
        if contract.get("option_type") != side:
            raise TradePlanError("CONTRACT_SIDE_MISMATCH")
        security_id = cls._text(
            contract.get("security_id"), "CONTRACT_SECURITY_ID_UNAVAILABLE"
        )
        expiry = cls._expiry(contract.get("expiry"), today)
        lot_size = cls._positive_int(
            contract.get("lot_size"), "CONTRACT_LOT_SIZE_UNAVAILABLE"
        )
        strike = cls._positive(
            contract.get("strike"), "CONTRACT_STRIKE_UNAVAILABLE"
        )
        candidate = cls._candidate(snapshot, security_id, side)
        ltp = cls._positive(candidate.get("premium"), "CONTRACT_LTP_UNAVAILABLE")
        bid = cls._positive(candidate.get("bid"), "CONTRACT_BID_UNAVAILABLE")
        ask = cls._positive(candidate.get("ask"), "CONTRACT_ASK_UNAVAILABLE")
        cls._liquidity(candidate, bid, ask)
        cls._quote_freshness(snapshot, candidate)
        return {
            "instrument_type": "OPTION",
            "underlying": cls._text(
                contract.get("underlying"), "CONTRACT_UNDERLYING_UNAVAILABLE"
            ).upper(),
            "contract": contract.get("trading_symbol"),
            "security_id": security_id,
            "expiry": expiry.isoformat(),
            "dte": (expiry - today).days,
            "strike": strike,
            "option_type": side,
            "lot_size": lot_size,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "delta": cls._signed(candidate.get("delta"), "DELTA_UNAVAILABLE"),
            "quote_timestamp": cls._quote_timestamp(snapshot, candidate),
        }

    @classmethod
    def _equity_instrument(
        cls, snapshot: Mapping[str, Any], today: date
    ) -> dict[str, Any]:
        argus = cls._argus_data(snapshot)
        underlying = cls._mapping(
            argus.get("underlying"), "EQUITY_QUOTE_UNAVAILABLE"
        )
        if underlying.get("segment") not in {"NSE_EQ", "NSE_CASH", "EQUITY"}:
            raise TradePlanError("EQUITY_POLICY_SCOPE_MISMATCH")
        bid = cls._positive(
            underlying.get("top_bid_price"), "EQUITY_BID_UNAVAILABLE"
        )
        ask = cls._positive(
            underlying.get("top_ask_price"), "EQUITY_ASK_UNAVAILABLE"
        )
        if ask < bid:
            raise TradePlanError("EQUITY_QUOTE_CROSSED")
        spread_pct = (ask - bid) / ask * 100.0
        if spread_pct > cls.MAX_SPREAD_PERCENT:
            raise TradePlanError("EQUITY_SPREAD_TOO_WIDE")
        timestamp = cls._text(
            underlying.get("fetched_at")
            or underlying.get("source_timestamp"),
            "EQUITY_QUOTE_TIMESTAMP_UNAVAILABLE",
        )
        return {
            "instrument_type": "EQUITY",
            "underlying": cls._text(
                snapshot.get("symbol"), "EQUITY_SYMBOL_UNAVAILABLE"
            ).upper(),
            "contract": underlying.get("trading_symbol")
            or snapshot.get("symbol"),
            "security_id": cls._text(
                underlying.get("security_id"),
                "EQUITY_SECURITY_ID_UNAVAILABLE",
            ),
            "expiry": None,
            "dte": None,
            "strike": None,
            "option_type": None,
            "lot_size": cls._positive_int(
                underlying.get("lot_size") or 1,
                "EQUITY_LOT_SIZE_UNAVAILABLE",
            ),
            "ltp": cls._positive(
                underlying.get("ltp"), "EQUITY_LTP_UNAVAILABLE"
            ),
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "delta": None,
            "quote_timestamp": timestamp,
        }

    @classmethod
    def _structural_risk(
        cls,
        *,
        instrument: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        decision: str,
    ) -> dict[str, Any]:
        tactical = cls._tactical(snapshot)
        decision_data = cls._mapping(
            tactical.get("decision"), "ARGUS_DECISION_UNAVAILABLE"
        )
        invalidation = cls._positive(
            decision_data.get("invalidation_level"),
            "STRUCTURAL_INVALIDATION_UNAVAILABLE",
        )
        maximum_entry = float(instrument["ask"])
        noise = float(instrument["spread"])
        if instrument["instrument_type"] == "OPTION":
            spot = cls._positive(
                cls._argus_data(snapshot)
                .get("underlying", {})
                .get("ltp"),
                "UNDERLYING_SPOT_UNAVAILABLE",
            )
            if decision == "CALL" and invalidation >= spot:
                raise TradePlanError("CALL_INVALIDATION_NOT_BELOW_SPOT")
            if decision == "PUT" and invalidation <= spot:
                raise TradePlanError("PUT_INVALIDATION_NOT_ABOVE_SPOT")
            mapped = float(instrument["ltp"]) - abs(spot - invalidation) * abs(
                float(instrument["delta"])
            )
            final_stop = mapped - noise
        else:
            if invalidation >= maximum_entry:
                raise TradePlanError("EQUITY_INVALIDATION_NOT_BELOW_ENTRY")
            mapped = None
            final_stop = invalidation - noise
        if final_stop <= 0:
            raise TradePlanError("STRUCTURAL_STOP_NON_POSITIVE")
        return {
            "maximum_entry": maximum_entry,
            "structural_invalidation": invalidation,
            "mapped_premium_stop": mapped,
            "noise_allowance": noise,
            "final_stop": final_stop,
        }

    @classmethod
    def _risk_budget(
        cls,
        *,
        limits: Mapping[str, Any],
        paper: Mapping[str, Any],
        reserved_risk: float,
    ) -> float:
        per_trade = cls._positive(
            limits.get("max_risk_per_trade"),
            "MAX_TRADE_RISK_UNAVAILABLE",
        )
        daily_limit = cls._positive(
            limits.get("max_daily_loss"), "MAX_DAILY_LOSS_UNAVAILABLE"
        )
        pnl = cls._number(
            paper.get("total_daily_pnl"), "DAILY_PNL_UNAVAILABLE"
        )
        remaining_daily = max(0.0, daily_limit - max(0.0, -pnl))
        strategy_available = cls._positive(
            limits.get("strategy_risk_available") or per_trade,
            "STRATEGY_RISK_UNAVAILABLE",
        )
        budget = min(per_trade, remaining_daily, strategy_available)
        return max(0.0, budget - max(0.0, float(reserved_risk)))

    @classmethod
    def _risk_context(
        cls, snapshot: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        feeds = cls._mapping(snapshot.get("feeds"), "V2_FEEDS_UNAVAILABLE")
        risk = cls._mapping(
            cls._mapping(feeds.get("risk_status"), "RISK_FEED_UNAVAILABLE").get(
                "data"
            ),
            "RISK_STATE_UNAVAILABLE",
        )
        limits = cls._mapping(risk.get("limits"), "RISK_LIMITS_UNAVAILABLE")
        paper = cls._mapping(
            cls._mapping(
                feeds.get("paper_status"), "PAPER_FEED_UNAVAILABLE"
            ).get("data"),
            "PAPER_STATE_UNAVAILABLE",
        )
        return risk, limits, paper

    @classmethod
    def _risk_blocks(
        cls,
        risk: Mapping[str, Any],
        limits: Mapping[str, Any],
        paper: Mapping[str, Any],
    ) -> None:
        reasons: list[str] = []
        if risk.get("risk_state_available") is not True:
            reasons.append("RISK_STATE_UNAVAILABLE")
        if risk.get("kill_switch_active") is not False:
            reasons.append("KILL_SWITCH_BLOCKED")
        if paper.get("state_health") != "HEALTHY":
            reasons.append("PAPER_STATE_UNAVAILABLE")
        if cls._number(
            paper.get("total_daily_pnl"), "DAILY_PNL_UNAVAILABLE"
        ) <= -cls._positive(
            limits.get("max_daily_loss"), "MAX_DAILY_LOSS_UNAVAILABLE"
        ):
            reasons.append("DAILY_LOSS_LIMIT_REACHED")
        if cls._nonnegative_int(
            paper.get("consecutive_losses"),
            "CONSECUTIVE_LOSSES_UNAVAILABLE",
        ) >= cls._positive_int(
            limits.get("max_consecutive_losses"),
            "MAX_CONSECUTIVE_LOSSES_UNAVAILABLE",
        ):
            reasons.append("CONSECUTIVE_LOSS_STOP")
        if cls._nonnegative_int(
            paper.get("open_position_count"),
            "OPEN_POSITION_COUNT_UNAVAILABLE",
        ) > 0:
            reasons.append("POSITION_ALREADY_OPEN")
        if cls._nonnegative_int(
            paper.get("trades_taken_today"),
            "TRADES_TAKEN_TODAY_UNAVAILABLE",
        ) >= cls._positive_int(
            limits.get("max_trades_per_day"),
            "MAX_TRADES_PER_DAY_UNAVAILABLE",
        ):
            reasons.append("MAX_TRADES_PER_DAY_REACHED")
        if reasons:
            raise TradePlanError(*reasons)

    @classmethod
    def _require_fresh(cls, snapshot: Mapping[str, Any]) -> None:
        polling = cls._mapping(
            snapshot.get("polling"), "V2_FRESHNESS_UNAVAILABLE"
        )
        if polling.get("snapshot_status") != "FRESH":
            raise TradePlanError("V2_SNAPSHOT_STALE")

    @classmethod
    def _candidate(
        cls, snapshot: Mapping[str, Any], security_id: str, side: str
    ) -> Mapping[str, Any]:
        decision = cls._mapping(
            cls._tactical(snapshot).get("decision"),
            "ARGUS_DECISION_UNAVAILABLE",
        )
        rows = decision.get("all_candidate_ranks")
        if not isinstance(rows, list):
            raise TradePlanError("ARGUS_CANDIDATES_UNAVAILABLE")
        matches = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("security_id")) == security_id
            and row.get("side") == side
        ]
        if len(matches) != 1:
            raise TradePlanError("EXACT_CONTRACT_QUOTE_UNAVAILABLE")
        return matches[0]

    @classmethod
    def _liquidity(
        cls, candidate: Mapping[str, Any], bid: float, ask: float
    ) -> None:
        if candidate.get("status") != "CANDIDATE":
            raise TradePlanError("CONTRACT_NOT_LIQUID")
        if ask < bid:
            raise TradePlanError("CONTRACT_QUOTE_CROSSED")
        spread_pct = cls._positive(
            candidate.get("spread_pct"), "SPREAD_UNAVAILABLE"
        )
        if spread_pct > cls.MAX_SPREAD_PERCENT:
            raise TradePlanError("SPREAD_CAP_EXCEEDED")
        if cls._positive(candidate.get("volume"), "VOLUME_UNAVAILABLE") <= 0:
            raise TradePlanError("CONTRACT_NOT_LIQUID")

    @classmethod
    def _quote_freshness(
        cls, snapshot: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> None:
        tactical = cls._tactical(snapshot)
        if tactical.get("freshness") != "LIVE":
            raise TradePlanError("ARGUS_QUOTE_STALE")
        cls._quote_timestamp(snapshot, candidate)

    @classmethod
    def _quote_timestamp(
        cls, snapshot: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> str:
        tactical = cls._tactical(snapshot)
        value = (
            candidate.get("source_timestamp")
            or tactical.get("option_chain_source_timestamp")
            or tactical.get("source_timestamp")
        )
        return cls._text(value, "QUOTE_TIMESTAMP_UNAVAILABLE")

    @classmethod
    def _validate_quote_age(
        cls,
        value: Any,
        now: datetime,
        limits: Mapping[str, Any],
    ) -> None:
        timestamp = cls._text(value, "QUOTE_TIMESTAMP_UNAVAILABLE")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise TradePlanError("QUOTE_TIMESTAMP_INVALID") from error
        if parsed.tzinfo is None:
            raise TradePlanError("QUOTE_TIMESTAMP_INVALID")
        age = (
            now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)
        ).total_seconds()
        maximum_age = cls._positive(
            limits.get("max_market_data_age_seconds"),
            "MAX_MARKET_DATA_AGE_UNAVAILABLE",
        )
        if age < 0:
            raise TradePlanError("QUOTE_TIMESTAMP_FUTURE")
        if age > maximum_age:
            raise TradePlanError("QUOTE_STALE")

    @classmethod
    def _available_capital(cls, paper: Mapping[str, Any]) -> float:
        return cls._positive(
            paper.get("cash_balance")
            or paper.get("available_capital")
            or paper.get("available_margin"),
            "AVAILABLE_CAPITAL_UNAVAILABLE",
        )

    @classmethod
    def _execution(cls, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        feeds = cls._mapping(snapshot.get("feeds"), "V2_FEEDS_UNAVAILABLE")
        strategy = cls._mapping(
            cls._mapping(
                feeds.get("strategy_lab"), "STRATEGY_LAB_FEED_UNAVAILABLE"
            ).get("data"),
            "STRATEGY_LAB_STATE_UNAVAILABLE",
        )
        return cls._mapping(
            strategy.get("execution"), "EXECUTION_PROJECTION_UNAVAILABLE"
        )

    @classmethod
    def _argus_data(cls, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        feeds = cls._mapping(snapshot.get("feeds"), "V2_FEEDS_UNAVAILABLE")
        envelope = cls._mapping(
            cls._mapping(feeds.get("argus"), "ARGUS_FEED_UNAVAILABLE").get(
                "data"
            ),
            "ARGUS_ENVELOPE_UNAVAILABLE",
        )
        return cls._mapping(envelope.get("data"), "ARGUS_DATA_UNAVAILABLE")

    @classmethod
    def _tactical(cls, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        return cls._mapping(
            cls._argus_data(snapshot).get("tactical_edge"),
            "ARGUS_TACTICAL_UNAVAILABLE",
        )

    @staticmethod
    def _mapping(value: Any, reason: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TradePlanError(reason)
        return value

    @staticmethod
    def _text(value: Any, reason: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TradePlanError(reason)
        return value.strip()

    @staticmethod
    def _number(value: Any, reason: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise TradePlanError(reason)
        return float(value)

    @classmethod
    def _positive(cls, value: Any, reason: str) -> float:
        number = cls._number(value, reason)
        if number <= 0:
            raise TradePlanError(reason)
        return number

    @staticmethod
    def _signed(value: Any, reason: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or abs(float(value)) > 1
            or float(value) == 0
        ):
            raise TradePlanError(reason)
        return float(value)

    @staticmethod
    def _positive_int(value: Any, reason: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TradePlanError(reason)
        return value

    @staticmethod
    def _nonnegative_int(value: Any, reason: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TradePlanError(reason)
        return value

    @staticmethod
    def _expiry(value: Any, today: date) -> date:
        if not isinstance(value, str):
            raise TradePlanError("CONTRACT_EXPIRY_UNAVAILABLE")
        try:
            expiry = date.fromisoformat(value[:10])
        except ValueError as error:
            raise TradePlanError("CONTRACT_EXPIRY_INVALID") from error
        if expiry < today:
            raise TradePlanError("CONTRACT_EXPIRY_EXPIRED")
        return expiry

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TradePlanError("PLANNING_CLOCK_INVALID")
        return value

    @staticmethod
    def _money(value: float) -> float:
        return round(float(value), 2)

    @classmethod
    def _optional_money(cls, value: Optional[float]) -> Optional[float]:
        return None if value is None else cls._money(value)
