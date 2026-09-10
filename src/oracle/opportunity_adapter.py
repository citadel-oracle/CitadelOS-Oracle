"""Fail-closed adapter from the cached V2 dashboard to Opportunity Gate V1."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping, TypeVar

from src.oracle.opportunity_gate import (
    Direction,
    GateDecision,
    Freshness,
    InstrumentType,
    LiquidityState,
    OpportunityGate,
    OpportunityGateResult,
    OpportunitySnapshot,
    RiskEligibility,
    TriggerSource,
    VolatilityState,
)
from src.oracle.strategy_policy import StrategyTrigger, StrategyTriggeredPolicy


OpportunityGateInput = OpportunitySnapshot
_EnumValue = TypeVar("_EnumValue")


class SnapshotAdapterError(ValueError):
    """The supplied cached projection cannot satisfy the typed input contract."""


def adapt_v2_snapshot(snapshot: Mapping[str, Any]) -> OpportunityGateInput:
    """Map one already-cached V2 projection without fetching or recalculating."""

    root = _mapping(snapshot, "snapshot")
    feeds = _mapping(root.get("feeds"), "feeds")
    oracle_feed = _mapping(feeds.get("oracle"), "feeds.oracle")
    oracle_data = _mapping(oracle_feed.get("data"), "feeds.oracle.data")
    oracle_meta = _mapping(oracle_feed.get("meta"), "feeds.oracle.meta")
    input_features = _mapping_or_empty(
        oracle_data.get("input_features"),
        "feeds.oracle.data.input_features",
    )

    argus_feed = _mapping(feeds.get("argus"), "feeds.argus")
    argus_envelope = _mapping(argus_feed.get("data"), "feeds.argus.data")
    argus_data = _mapping(
        argus_envelope.get("data"), "feeds.argus.data.data"
    )
    tactical = _mapping_or_empty(
        argus_data.get("tactical_edge"),
        "feeds.argus.data.data.tactical_edge",
    )
    decision = _mapping_or_empty(
        tactical.get("decision"),
        "feeds.argus.data.data.tactical_edge.decision",
    )
    underlying = _mapping_or_empty(
        argus_data.get("underlying"),
        "feeds.argus.data.data.underlying",
    )

    strategy_feed = _mapping(
        feeds.get("strategy_lab"), "feeds.strategy_lab"
    )
    strategy_data = _mapping(
        strategy_feed.get("data"), "feeds.strategy_lab.data"
    )
    execution = _mapping_or_empty(
        strategy_data.get("execution"),
        "feeds.strategy_lab.data.execution",
    )
    vob = _mapping_or_empty(
        execution.get("nifty_vob"),
        "feeds.strategy_lab.data.execution.nifty_vob",
    )
    ose = _mapping_or_empty(
        execution.get("options_structure"),
        "feeds.strategy_lab.data.execution.options_structure",
    )

    risk_feed = _mapping(feeds.get("risk_status"), "feeds.risk_status")
    risk = _mapping(risk_feed.get("data"), "feeds.risk_status.data")

    symbol = root.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise SnapshotAdapterError("symbol is missing or invalid")

    evaluation_timestamp = _timestamp(
        oracle_meta.get("calculation_timestamp"),
        "feeds.oracle.meta.calculation_timestamp",
        required=True,
    )
    snapshot_timestamp = _timestamp(
        oracle_data.get("market_data_as_of"),
        "feeds.oracle.data.market_data_as_of",
        required=False,
    )

    reasons: list[str] = []
    instrument_type = _instrument_type(ose, underlying)
    market_regime = _market_regime(
        oracle_data.get("regime"),
        input_features.get("timeframe_bias"),
        reasons,
    )
    price_structure = _direction(
        input_features.get("price_trend"),
        "PRICE_STRUCTURE",
        reasons,
        {
            "BULLISH": Direction.BULLISH,
            "BEARISH": Direction.BEARISH,
            "MIXED": Direction.NEUTRAL,
            "NEUTRAL": Direction.NEUTRAL,
        },
    )

    vob_context = _vob_direction(vob, reasons)
    argus_metrics = _direction(
        decision.get("market_direction"),
        "ARGUS_DIRECTION",
        reasons,
        {
            "CALL": Direction.BULLISH,
            "PUT": Direction.BEARISH,
            "BALANCED": Direction.NEUTRAL,
        },
    )
    ose_context = _direction(
        _mapping_or_empty(
            ose.get("duel"),
            "feeds.strategy_lab.data.execution.options_structure.duel",
        ).get("state"),
        "OSE_DIRECTION",
        reasons,
        {
            "CLEAR CALL ADVANTAGE": Direction.BULLISH,
            "CLEAR PUT ADVANTAGE": Direction.BEARISH,
            "BALANCED": Direction.NEUTRAL,
        },
    )
    volatility = _volatility(tactical, reasons)
    liquidity = _liquidity_spread(decision, argus_metrics, reasons)
    risk_eligibility = _risk_eligibility(risk, reasons)
    freshness = _freshness(
        root,
        oracle_data,
        tactical,
        vob,
        ose,
        instrument_type,
        reasons,
    )
    _extend_source_reasons(reasons, oracle_data)
    _extend_source_reasons(reasons, tactical)
    if symbol.strip().upper() == "NIFTY":
        reasons = [
            reason
            for reason in reasons
            if reason
            not in {
                "SPOT_VOLUME_UNAVAILABLE",
                "VOLUME_DATA_UNAVAILABLE",
                "VWAP_UNAVAILABLE",
            }
        ]

    return OpportunitySnapshot(
        symbol=symbol.strip().upper(),
        instrument_type=instrument_type,
        snapshot_timestamp=snapshot_timestamp,
        evaluation_timestamp=evaluation_timestamp,
        freshness=freshness,
        market_regime=market_regime,
        price_structure=price_structure,
        vob_context=vob_context,
        argus_metrics=argus_metrics,
        ose_context=ose_context,
        volatility=volatility,
        liquidity_spread=liquidity,
        risk_eligibility=risk_eligibility,
        unavailable_reasons=tuple(sorted(set(reasons))),
    )


def evaluate_v2_snapshot(
    snapshot: Mapping[str, Any],
) -> OpportunityGateResult:
    """Evaluate one supplied cached snapshot; never refresh external state."""

    gate_input = adapt_v2_snapshot(snapshot)
    triggers = strategy_triggers_from_v2(snapshot)
    if triggers:
        return StrategyTriggeredPolicy.choose(snapshot, gate_input, triggers)
    return OpportunityGate.evaluate(gate_input)


def strategy_triggers_from_v2(
    snapshot: Mapping[str, Any],
) -> tuple[StrategyTrigger, ...]:
    """Thinly adapt canonical strategy/lifecycle events; never recreate signals."""

    root = _mapping(snapshot, "snapshot")
    boundary_node = _mapping_or_empty(
        root.get("intelligence_boundary"), "intelligence_boundary"
    )
    if (
        boundary_node.get("status") != "COHERENT"
        or boundary_node.get("timeframe") != "5m"
    ):
        return ()
    boundary = _timestamp(
        boundary_node.get("completed_boundary"),
        "intelligence_boundary.completed_boundary",
        required=True,
    )
    feeds = _mapping(root.get("feeds"), "feeds")
    strategy = _mapping(
        feeds.get("strategy_lab"), "feeds.strategy_lab"
    )
    strategy_data = _mapping(
        strategy.get("data"), "feeds.strategy_lab.data"
    )
    execution = _mapping_or_empty(
        strategy_data.get("execution"), "feeds.strategy_lab.data.execution"
    )
    vob = _mapping_or_empty(
        execution.get("nifty_vob"), "execution.nifty_vob"
    )
    timeframes = _mapping_or_empty(
        vob.get("timeframes"), "execution.nifty_vob.timeframes"
    )
    five = _mapping_or_empty(timeframes.get("5m"), "nifty_vob.timeframes.5m")
    triggers: list[StrategyTrigger] = []
    broken = five.get("recently_broken")
    if broken is not None and not isinstance(broken, list):
        raise SnapshotAdapterError("5m VOB recently_broken is malformed")
    for zone in broken or ():
        if not isinstance(zone, Mapping):
            raise SnapshotAdapterError("5m VOB lifecycle zone is malformed")
        if zone.get("status") != "BROKEN":
            continue
        broken_at = _timestamp(
            zone.get("broken_at"), "5m VOB broken_at", required=False
        )
        source_at = _timestamp(
            zone.get("source_candle_timestamp"),
            "5m VOB source_candle_timestamp",
            required=False,
        )
        if source_at != boundary:
            continue
        direction = (
            GateDecision.CALL
            if zone.get("role") == "RESISTANCE"
            else GateDecision.PUT
            if zone.get("role") == "SUPPORT"
            else None
        )
        if direction is not None and broken_at == boundary:
            triggers.append(
                StrategyTrigger(
                    source=TriggerSource.VOB_BREAKOUT,
                    direction=direction,
                    candle_timestamp=boundary,
                    acceptance_confirmed=True,
                    identity=str(zone.get("zone_id") or ""),
                )
            )
        last_tested = _timestamp(
            zone.get("last_tested_time"),
            "5m VOB last_tested_time",
            required=False,
        )
        if (
            direction is not None
            and last_tested == boundary
            and broken_at is not None
            and broken_at < boundary
        ):
            triggers.append(
                StrategyTrigger(
                    source=TriggerSource.VOB_RETEST,
                    direction=direction,
                    candle_timestamp=boundary,
                    acceptance_confirmed=False,
                    identity=str(zone.get("zone_id") or ""),
                )
            )

    matrix = feeds.get("matrix")
    matrix_data = matrix.get("data") if isinstance(matrix, Mapping) else None
    if matrix_data is not None and not isinstance(matrix_data, list):
        raise SnapshotAdapterError("feeds.matrix.data is malformed")
    for row in matrix_data or ():
        if (
            not isinstance(row, Mapping)
            or str(row.get("symbol")).upper() != root.get("symbol")
        ):
            continue
        signal = str(row.get("pullback_signal") or "").upper()
        if signal not in {"BUY", "SELL"}:
            continue
        readiness = row.get("technical_readiness")
        if not isinstance(readiness, Mapping) or readiness.get("status") != "READY":
            continue
        candle = _timestamp(
            readiness.get("latest_candle"),
            "matrix.technical_readiness.latest_candle",
            required=True,
        )
        strategy_name = str(row.get("strategy") or "").upper()
        source = (
            TriggerSource.BREAKOUT
            if "BREAKOUT" in strategy_name
            else TriggerSource.PULLBACK
        )
        triggers.append(
            StrategyTrigger(
                source=source,
                direction=(
                    GateDecision.CALL
                    if signal == "BUY"
                    else GateDecision.PUT
                ),
                candle_timestamp=candle,
                acceptance_confirmed=row.get("entry") is not None,
                current_entry=_positive_optional(row.get("entry")),
                identity=f"{row.get('symbol')}:{strategy_name}:{candle.isoformat()}",
            )
        )
    unique = {
        (
            trigger.source,
            trigger.direction,
            trigger.candle_timestamp,
            trigger.identity,
        ): trigger
        for trigger in triggers
    }
    return tuple(unique[key] for key in sorted(unique, key=str))


def _positive_optional(value: Any) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise SnapshotAdapterError("strategy entry is malformed")
    return float(value)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotAdapterError(f"{path} is missing or malformed")
    return value


def _mapping_or_empty(value: Any, path: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SnapshotAdapterError(f"{path} is malformed")
    return value


def _timestamp(
    value: Any, path: str, *, required: bool
) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SnapshotAdapterError(f"{path} is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotAdapterError(f"{path} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotAdapterError(f"{path} must be timezone-aware")
    return parsed


def _instrument_type(
    ose: Mapping[str, Any], underlying: Mapping[str, Any]
) -> InstrumentType:
    contracts = _mapping_or_empty(
        ose.get("contracts"),
        "feeds.strategy_lab.data.execution.options_structure.contracts",
    )
    if contracts:
        ce_envelope = _mapping_or_empty(
            contracts.get("CE"), "options_structure.contracts.CE"
        )
        pe_envelope = _mapping_or_empty(
            contracts.get("PE"), "options_structure.contracts.PE"
        )
        ce = _mapping_or_empty(
            ce_envelope.get("contract"),
            "options_structure.contracts.CE.contract",
        )
        pe = _mapping_or_empty(
            pe_envelope.get("contract"),
            "options_structure.contracts.PE.contract",
        )
        _validate_option_pair(ce, pe)
        return InstrumentType.OPTION
    if underlying.get("segment") in {"NSE_EQ", "NSE_CASH", "EQUITY"}:
        return InstrumentType.EQUITY
    raise SnapshotAdapterError("instrument type is unavailable or unsupported")


def _validate_option_pair(
    ce: Mapping[str, Any], pe: Mapping[str, Any]
) -> None:
    required = (
        "security_id",
        "option_type",
        "exchange_segment",
        "underlying",
        "expiry",
    )
    if any(
        not isinstance(contract.get(field), str)
        or not contract.get(field).strip()
        for contract in (ce, pe)
        for field in required
    ):
        raise SnapshotAdapterError("option contract pair is incomplete")
    if (
        ce["option_type"] != "CE"
        or pe["option_type"] != "PE"
        or ce["exchange_segment"] != "NSE_FNO"
        or pe["exchange_segment"] != "NSE_FNO"
        or ce["security_id"] == pe["security_id"]
    ):
        raise SnapshotAdapterError("option contract pair is conflicting")
    for field in ("underlying", "expiry"):
        if ce[field] != pe[field]:
            raise SnapshotAdapterError("option contract pair is conflicting")


def _market_regime(
    regime: Any, timeframe_bias: Any, reasons: list[str]
) -> Direction:
    if regime in {"RANGING", "SIDEWAYS", "MIXED"}:
        return Direction.NEUTRAL
    if regime == "TRENDING":
        return _direction(
            timeframe_bias,
            "MARKET_REGIME_DIRECTION",
            reasons,
            {
                "BULLISH": Direction.BULLISH,
                "BEARISH": Direction.BEARISH,
            },
        )
    reason = (
        "MARKET_REGIME_NOT_REPORTED"
        if regime in {None, "", "UNKNOWN", "UNAVAILABLE"}
        else "MARKET_REGIME_UNSUPPORTED"
    )
    reasons.append(reason)
    return Direction.UNAVAILABLE


def _vob_direction(
    vob: Mapping[str, Any], reasons: list[str]
) -> Direction:
    confluence = _mapping_or_empty(
        vob.get("strongest_confluence"),
        "nifty_vob.strongest_confluence",
    )
    bullish = _mapping_or_empty(
        confluence.get("bullish"),
        "nifty_vob.strongest_confluence.bullish",
    )
    bearish = _mapping_or_empty(
        confluence.get("bearish"),
        "nifty_vob.strongest_confluence.bearish",
    )
    present = [node for node in (bullish, bearish) if node]
    if len(present) != 1:
        reasons.append(
            "VOB_DIRECTION_AMBIGUOUS"
            if len(present) == 2
            else "VOB_DIRECTION_NOT_REPORTED"
        )
        return Direction.UNAVAILABLE
    side = present[0].get("side")
    if side == "BULLISH":
        return Direction.BULLISH
    if side == "BEARISH":
        return Direction.BEARISH
    reasons.append("VOB_DIRECTION_UNSUPPORTED")
    return Direction.UNAVAILABLE


def _volatility(
    tactical: Mapping[str, Any], reasons: list[str]
) -> VolatilityState:
    iv = _mapping_or_empty(
        tactical.get("iv_intelligence"),
        "feeds.argus.data.data.tactical_edge.iv_intelligence",
    )
    status = iv.get("status")
    direction = iv.get("direction")
    if status == "AVAILABLE" and direction == "STABLE":
        return VolatilityState.NEUTRAL
    if status == "AVAILABLE" and direction in {"RISING", "FALLING"}:
        reasons.append("VOLATILITY_DIRECTION_CONTEXT_REQUIRED")
        return VolatilityState.UNAVAILABLE
    reasons.append(
        "VOLATILITY_NOT_REPORTED"
        if status in {None, "UNAVAILABLE"} or direction in {None, "UNAVAILABLE"}
        else "VOLATILITY_UNSUPPORTED"
    )
    return VolatilityState.UNAVAILABLE


def _liquidity_spread(
    decision: Mapping[str, Any],
    argus_direction: Direction,
    reasons: list[str],
) -> LiquidityState:
    ranks = decision.get("all_candidate_ranks")
    if not isinstance(ranks, list):
        reasons.append("LIQUIDITY_SPREAD_NOT_REPORTED")
        return LiquidityState.UNAVAILABLE
    target_side = (
        "CE"
        if argus_direction is Direction.BULLISH
        else "PE"
        if argus_direction is Direction.BEARISH
        else None
    )
    if target_side is None:
        reasons.append("LIQUIDITY_SPREAD_DIRECTION_UNAVAILABLE")
        return LiquidityState.UNAVAILABLE
    rank_one: Mapping[str, Any] | None = None
    for value in ranks:
        if not isinstance(value, Mapping):
            raise SnapshotAdapterError("ARGUS candidate rank is malformed")
        if (
            type(value.get("rank")) is int
            and value.get("rank") == 1
            and value.get("side") == target_side
        ):
            rank_one = value
            break
    if rank_one is None:
        reasons.append("LIQUIDITY_SPREAD_CANDIDATE_NOT_REPORTED")
        return LiquidityState.UNAVAILABLE
    for field in ("spread_abs", "spread_pct"):
        value = rank_one.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            reasons.append("LIQUIDITY_SPREAD_MALFORMED")
            return LiquidityState.UNAVAILABLE
    status = rank_one.get("status")
    rejection = rank_one.get("rejection_reason")
    if status == "CANDIDATE" and rejection is None:
        return LiquidityState.ACCEPTABLE
    if status == "BLOCKED" and isinstance(rejection, str) and any(
        token in rejection for token in ("SPREAD", "LIQUIDITY")
    ):
        return LiquidityState.POOR
    reasons.append("LIQUIDITY_SPREAD_STATUS_UNAVAILABLE")
    return LiquidityState.UNAVAILABLE


def _direction(
    value: Any,
    name: str,
    reasons: list[str],
    mapping: Mapping[str, Direction],
) -> Direction:
    return _mapped_enum(
        value, name, reasons, mapping, Direction.UNAVAILABLE
    )


def _mapped_enum(
    value: Any,
    name: str,
    reasons: list[str],
    mapping: Mapping[str, _EnumValue],
    unavailable: _EnumValue,
) -> _EnumValue:
    if isinstance(value, str) and value in mapping:
        return mapping[value]
    reason = (
        f"{name}_NOT_REPORTED"
        if value is None or value in {"", "UNAVAILABLE", "UNKNOWN"}
        else f"{name}_UNSUPPORTED"
    )
    reasons.append(reason)
    return unavailable


def _risk_eligibility(
    risk: Mapping[str, Any], reasons: list[str]
) -> RiskEligibility:
    kill_switch = risk.get("kill_switch_active")
    available = risk.get("risk_state_available")
    if kill_switch is True:
        return RiskEligibility.BLOCKED
    if available is True and kill_switch is False:
        return RiskEligibility.ELIGIBLE
    reasons.append("RISK_ELIGIBILITY_NOT_REPORTED")
    return RiskEligibility.UNAVAILABLE


def _freshness(
    root: Mapping[str, Any],
    oracle: Mapping[str, Any],
    tactical: Mapping[str, Any],
    vob: Mapping[str, Any],
    ose: Mapping[str, Any],
    instrument_type: InstrumentType,
    reasons: list[str],
) -> Freshness:
    polling = _mapping_or_empty(root.get("polling"), "polling")
    vob_sync = _mapping_or_empty(
        vob.get("source_1m_sync"), "nifty_vob.source_1m_sync"
    )
    vob_runtime = vob_sync.get("runtime_status")
    vob_backlog = vob_sync.get("backlog_count")
    if vob_runtime == "LIVE":
        if type(vob_backlog) is int and vob_backlog == 0:
            vob_state = "LIVE"
        elif type(vob_backlog) is int and vob_backlog > 0:
            vob_state = "STALE"
        else:
            vob_state = "MALFORMED"
    else:
        vob_state = vob_runtime
    states = (
        ("V2", polling.get("snapshot_status")),
        ("ORACLE", oracle.get("data_status")),
        ("ARGUS", tactical.get("freshness")),
        ("VOB", vob_state),
    )
    if instrument_type is InstrumentType.OPTION:
        states += (("OSE", ose.get("source_freshness")),)
    normalized: list[Freshness] = []
    for name, value in states:
        if value in {"FRESH", "LIVE", "AVAILABLE"}:
            normalized.append(Freshness.FRESH)
        elif value in {"STALE", "CACHED"}:
            normalized.append(Freshness.STALE)
            reasons.append(f"{name}_STALE")
        else:
            normalized.append(Freshness.UNAVAILABLE)
            reasons.append(
                f"{name}_FRESHNESS_NOT_REPORTED"
                if value in {None, "", "UNAVAILABLE", "UNKNOWN"}
                else f"{name}_FRESHNESS_UNSUPPORTED"
            )
    if Freshness.UNAVAILABLE in normalized:
        return Freshness.UNAVAILABLE
    if Freshness.STALE in normalized:
        return Freshness.STALE
    return Freshness.FRESH


def _extend_source_reasons(
    target: list[str], source: Mapping[str, Any]
) -> None:
    for key in ("unavailable_reasons", "reason_codes", "warnings"):
        values = source.get(key)
        if isinstance(values, (list, tuple)):
            target.extend(
                value for value in values if isinstance(value, str) and value
            )
