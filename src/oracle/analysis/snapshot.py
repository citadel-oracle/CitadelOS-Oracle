"""Assemble one immutable, time-aligned snapshot from cached authorities only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.oracle.contracts.analysis import AnalysisSnapshot, OptionContractQuote, seal
from src.oracle.contracts.perception import Availability, FreshnessState, MarketContextSnapshot, VerifiedVisualClaim


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SnapshotPolicy:
    version: str = "oracle-snapshot-3.0.0"
    max_age_seconds: Mapping[str, float] | None = None
    max_boundary_skew_seconds: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_age_seconds", self.max_age_seconds or {
            "dashboard": 30.0, "argus": 30.0, "vob": 900.0,
            "ose": 300.0, "canonical_features": 600.0,
        })
        object.__setattr__(self, "max_boundary_skew_seconds", self.max_boundary_skew_seconds or {
            "vob_to_context_5m": 600.0, "ose_to_context_5m": 600.0,
            "argus_to_context_5m": 900.0,
        })


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, Mapping) else {}


def _path(value: Mapping[str, Any], *parts: str, default=None):
    current: Any = value
    for part in parts:
        if not isinstance(current, Mapping):
            return default
        current = current.get(part)
    return default if current is None else current


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def _aware(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=IST)
    return result


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class AnalysisSnapshotAssembler:
    """References cached outputs and declares incompatibility; it never refreshes them."""

    def __init__(self, policy: SnapshotPolicy | None = None, *, clock=None):
        self.policy = policy or SnapshotPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def assemble(
        self, *, context: MarketContextSnapshot, dashboard: Mapping[str, Any],
        canonical_features: Any = None, visual_claims: Sequence[VerifiedVisualClaim] = (),
        correlation_id: str,
    ) -> AnalysisSnapshot:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        generated = now.isoformat()
        dashboard = _dict(dashboard)
        symbol = str(dashboard.get("symbol") or context.symbol).upper()
        argus = _dict(_path(dashboard, "feeds", "argus", "data", "data", default={}))
        tactical = _dict(argus.get("tactical_edge"))
        selection = _dict(tactical.get("contract_selection"))
        underlying = _dict(argus.get("underlying"))
        vob = _dict(_path(dashboard, "feeds", "strategy_lab", "data", "execution", "nifty_vob", default={}))
        ose = _dict(_path(dashboard, "feeds", "strategy_lab", "data", "execution", "options_structure", default={}))
        oracle_feed = _dict(_path(dashboard, "feeds", "oracle", "data", default={}))
        features = _dict(canonical_features)
        lanes = {lane.timeframe: {
            "record_id": lane.lane_id, "content_hash": lane.content_hash,
            "availability": lane.availability.value, "freshness": lane.freshness_state.value,
            "source_timestamp": lane.source_timestamp,
            "source_boundary": lane.candle.bar_end if lane.candle else None,
            "completion_status": lane.completion_status.value,
            "evidence_eligible": lane.evidence_eligible,
            "candle": lane.candle.to_dict() if lane.candle else None,
            "context": dict(lane.context_payload),
            "reasons": list(lane.invalidation_reasons),
        } for lane in context.lanes}

        records = {
            "context_lanes": lanes, "argus_underlying": underlying,
            "argus_tactical": tactical, "argus_atm_window": argus.get("atm_window") or [],
            "vob": vob, "ose": ose, "canonical_features": features,
            "canonical_market_assessment": oracle_feed,
            "session": {
                "market_state": underlying.get("market_state") or _path(dashboard, "feeds", "oracle", "meta", "operating_mode"),
                "trading_date": underlying.get("trading_date"),
                "dashboard_generated_at": dashboard.get("generated_at"),
                "trace_id": dashboard.get("trace_id"),
            },
        }
        source_hashes = {name: _hash(value) for name, value in records.items()}
        source_ids = {
            "context": context.snapshot_id,
            "dashboard": str(dashboard.get("trace_id") or _hash(dashboard)[:24]),
            "argus": str(tactical.get("calculation_id") or tactical.get("computed_snapshot_id") or "ARGUS_UNIDENTIFIED"),
            "vob": str(vob.get("canonical_digest") or vob.get("decision_boundary_5m") or "VOB_UNIDENTIFIED"),
            "ose": str(ose.get("canonical_digest") or ose.get("decision_boundary_5m") or "OSE_UNIDENTIFIED"),
            "canonical_features": str(features.get("feature_snapshot_id") or oracle_feed.get("decision_boundary_5m") or "CANONICAL_FEATURE_UNAVAILABLE"),
            "canonical_market_assessment": str(oracle_feed.get("decision_boundary_5m") or "CANONICAL_ASSESSMENT_UNAVAILABLE"),
            "session": str(dashboard.get("trace_id") or "SESSION_UNIDENTIFIED"),
            "visual": "PHASE2_VERIFIED_VISUAL_CLAIMS",
        }
        source_hashes["visual"] = _hash([item.content_hash for item in visual_claims])
        source_timestamps = {
            "context": context.source_timestamp,
            "dashboard": str(dashboard.get("generated_at") or generated),
            "argus": str(tactical.get("option_chain_source_timestamp") or tactical.get("source_timestamp") or underlying.get("fetched_at") or context.source_timestamp),
            "vob": str(_path(vob, "timeframes", "5m", "evaluated_through", default=vob.get("decision_boundary_5m") or context.source_timestamp)),
            "ose": str(ose.get("source_timestamp") or ose.get("decision_boundary_5m") or context.source_timestamp),
            "canonical_features": str(features.get("source_timestamp") or oracle_feed.get("market_data_as_of") or context.source_timestamp),
            "canonical_market_assessment": str(oracle_feed.get("market_data_as_of") or context.source_timestamp),
            "session": str(dashboard.get("generated_at") or generated),
            "visual": max((item.source_timestamp for item in visual_claims), default=context.source_timestamp),
        }
        market_state = str(underlying.get("market_state") or "UNKNOWN").upper()
        explicit_fixture = market_state == "NON_LIVE_FIXTURE"
        source_states = {}
        missing: list[str] = list(context.mandatory_missing)
        reasons: list[str] = []
        for name, timestamp in source_timestamps.items():
            parsed = _aware(timestamp)
            if parsed is None:
                source_states[name] = "UNAVAILABLE"
                missing.append(f"{name.upper()}_TIMESTAMP_UNAVAILABLE")
                continue
            if parsed > now:
                source_states[name] = "INCOMPATIBLE"
                reasons.append(f"{name.upper()}_TIMESTAMP_IN_FUTURE")
                continue
            age = max(0.0, (now - parsed.astimezone(now.tzinfo)).total_seconds())
            maximum = (self.policy.max_age_seconds or {}).get(name)
            source_states[name] = "FRESH" if explicit_fixture or maximum is None or age <= maximum else "STALE"
        mandatory_numeric_lanes = ("1D", "1H", "15m", "5m", "3m")
        numerical_context_fresh = all(
            str(_dict(lanes.get(tf)).get("freshness")) == "FRESH"
            and bool(_dict(lanes.get(tf)).get("evidence_eligible"))
            for tf in mandatory_numeric_lanes
        )
        if not explicit_fixture and not numerical_context_fresh:
            source_states["context"] = "STALE"
        if not argus:
            missing.append("ARGUS_UNAVAILABLE")
        if not vob:
            missing.append("VOB_UNAVAILABLE")
        if not ose:
            missing.append("OSE_UNAVAILABLE")
        if not features:
            missing.append("CANONICAL_FEATURE_SNAPSHOT_UNAVAILABLE")
        if not visual_claims:
            missing.append("VISUAL_UNAVAILABLE")
        identity_conflict = symbol != context.symbol or str(underlying.get("symbol") or symbol).upper() != symbol
        if identity_conflict:
            reasons.append("CROSS_SYMBOL_SOURCE_CONFLICT")
        self._check_boundary(reasons, "vob_to_context_5m", lanes.get("5m", {}).get("source_boundary"), source_timestamps["vob"])
        self._check_boundary(reasons, "ose_to_context_5m", lanes.get("5m", {}).get("source_boundary"), ose.get("decision_boundary_5m") or source_timestamps["ose"])
        self._check_boundary(reasons, "argus_to_context_5m", lanes.get("5m", {}).get("source_boundary"), tactical.get("spot_source_timestamp") or source_timestamps["argus"])

        expiry = str(selection.get("expiry") or underlying.get("expiry") or ose.get("expiry") or "") or None
        candidates = [] if identity_conflict else self._candidates(
            context=context, tactical=tactical, atm_window=argus.get("atm_window") or [],
            expiry=expiry, market_state=market_state, now=now, correlation_id=correlation_id,
        )
        if not candidates:
            missing.append("OPTION_CANDIDATES_UNAVAILABLE")
        if expiry and any(item.expiry != expiry for item in candidates):
            reasons.append("CROSS_EXPIRY_CONTRACT_CONFLICT")
        if len({item.contract_id for item in candidates}) != len(candidates):
            reasons.append("DUPLICATE_CONTRACT_IDENTITY")
        visual_valid = tuple(claim for claim in visual_claims if claim.symbol == symbol and claim.verify_hash())
        if len(visual_valid) != len(visual_claims):
            reasons.append("VISUAL_CLAIM_IDENTITY_OR_HASH_CONFLICT")
        market_closed = market_state not in {"OPEN", "NON_LIVE_FIXTURE"}
        stale_critical = market_closed or any(source_states.get(name) != "FRESH" for name in ("context", "argus", "vob", "ose", "canonical_features"))
        availability = Availability.AVAILABLE if not stale_critical and not reasons else Availability.HISTORICAL if not reasons else Availability.AMBIGUOUS
        freshness = FreshnessState.FRESH if not stale_critical and not reasons else FreshnessState.STALE
        required = 6
        present = sum(bool(value) for value in (context, argus, vob, ose, candidates, features or oracle_feed))
        completeness = max(0, min(100, round(present / required * 100 - min(25, len(set(missing)) * 2))))
        seed = _hash({"correlation_id": correlation_id, "context": context.content_hash,
                      "sources": source_hashes, "visual": [item.content_hash for item in visual_valid],
                      "generated_at": generated})[:24]
        analysis_id = f"analysis_{seed}"
        latest_source = max((_aware(value) for value in source_timestamps.values() if _aware(value)), default=now)
        return seal(AnalysisSnapshot(
            correlation_id=correlation_id, snapshot_id=analysis_id, decision_id=f"decision_{seed}",
            analysis_id=analysis_id, instrument_id=context.instrument_id, security_id=str(underlying.get("security_id") or "13"),
            symbol=symbol, timeframe="MULTI", source_timestamp=latest_source.isoformat(), generated_at=generated,
            as_of=latest_source.isoformat(), availability=availability, freshness_state=freshness,
            source_ids=source_ids, source_hashes=source_hashes,
            dependency_versions={"snapshot_policy": self.policy.version, "context_schema": context.schema_version,
                                 "argus": str(tactical.get("schema_version") or "existing-authority"),
                                 "vob": str(vob.get("schema_version") or "existing-authority"),
                                 "ose": str(ose.get("schema_version") or "existing-authority")},
            provenance={"service": "AnalysisSnapshotAssembler", "input_mode": "CACHED_AUTHORITIES_ONLY",
                        "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                        "advisory_only": True, "execution_influence": "ZERO"},
            missing_evidence=tuple(sorted(set(missing))), contradictory_evidence=tuple(sorted(set(reasons))),
            context_snapshot_id=context.snapshot_id, context_hash=context.content_hash,
            lane_hashes=dict(context.lane_hashes), expiry=expiry, market_state=market_state,
            time_remaining_seconds=self._time_remaining(expiry, now), source_states=source_states,
            source_timestamps=source_timestamps, source_records=records, visual_claims=visual_valid,
            candidate_contracts=tuple(candidates), compatible=not reasons,
            compatibility_reasons=tuple(sorted(set(reasons))), data_completeness=completeness,
        ))

    def _candidates(self, *, context, tactical, atm_window, expiry, market_state, now, correlation_id):
        selection = _dict(tactical.get("contract_selection"))
        ranks = selection.get("all_candidate_ranks") or _dict(tactical.get("decision")).get("all_candidate_ranks") or []
        legs = {}
        for row in atm_window:
            row = _dict(row)
            for side in ("ce", "pe"):
                leg = _dict(row.get(side))
                if leg.get("security_id") is not None:
                    legs[str(leg["security_id"])] = leg
        source_timestamp = str(tactical.get("option_chain_source_timestamp") or tactical.get("source_timestamp") or context.source_timestamp)
        quote_time = _aware(source_timestamp)
        quote_age = max(0.0, (now - quote_time.astimezone(now.tzinfo)).total_seconds()) if quote_time else None
        fresh = market_state == "NON_LIVE_FIXTURE" or (
            market_state == "OPEN" and quote_age is not None
            and quote_age <= (self.policy.max_age_seconds or {})["argus"]
        )
        result = []
        for raw in ranks:
            raw = _dict(raw)
            security_id = str(raw.get("security_id") or "")
            option_type = str(raw.get("option_type") or raw.get("side") or "").upper()
            strike = _number(raw.get("strike"))
            quote_expiry = str(raw.get("expiry") or expiry or "")
            if not security_id or option_type not in {"CE", "PE"} or strike is None or not quote_expiry:
                continue
            leg = legs.get(security_id, {})
            bid = _number(raw.get("bid"))
            ask = _number(raw.get("ask"))
            spread_abs = _number(raw.get("spread_abs"))
            spread_pct = _number(raw.get("spread_pct"))
            missing = [field.upper() + "_UNAVAILABLE" for field, value in {
                "bid": bid, "ask": ask, "delta": raw.get("delta"), "gamma": raw.get("gamma_value"),
                "theta": leg.get("theta"), "vega": leg.get("vega"), "iv": raw.get("iv"),
                "oi": raw.get("oi"), "volume": raw.get("volume"),
            }.items() if value is None]
            quote = OptionContractQuote(
                correlation_id=correlation_id, snapshot_id="pending", decision_id=None,
                instrument_id=context.instrument_id, security_id=security_id, symbol=context.symbol,
                timeframe="TICK", source_timestamp=source_timestamp, generated_at=now.isoformat(), as_of=source_timestamp,
                availability=Availability.AVAILABLE if fresh else Availability.HISTORICAL,
                freshness_state=FreshnessState.FRESH if fresh else FreshnessState.STALE,
                source_ids={"argus_contract_selection": str(tactical.get("calculation_id") or "ARGUS"), "contract": security_id},
                source_hashes={"argus_rank": _hash(raw), "canonical_quote": _hash(leg or raw)},
                dependency_versions={"authority": "ARGUS_EXISTING_RANK", "quote": "DHAN_NORMALIZED_EXISTING_AUTHORITY"},
                provenance={"service": "AnalysisSnapshotAssembler", "rank_reused": True, "spread_reused": True,
                            "executable_price_authority": "BID_ASK_NOT_LTP", "advisory_only": True,
                            "execution_influence": "ZERO"}, missing_evidence=tuple(missing),
                contract_id=security_id, trading_symbol=str(raw.get("trading_symbol") or leg.get("trading_symbol") or security_id),
                expiry=quote_expiry, strike=strike, option_type=option_type, bid=bid, ask=ask,
                mid=round((bid + ask) / 2, 4) if bid is not None and ask is not None else None,
                ltp=_number(raw.get("premium") or leg.get("ltp")), spread_abs=spread_abs, spread_pct=spread_pct,
                bid_depth=int(leg["top_bid_quantity"]) if leg.get("top_bid_quantity") is not None else None,
                ask_depth=int(leg["top_ask_quantity"]) if leg.get("top_ask_quantity") is not None else None,
                volume=int(raw["volume"]) if raw.get("volume") is not None else None,
                oi=int(raw["oi"]) if raw.get("oi") is not None else None,
                iv=_number(raw.get("iv")), delta=_number(raw.get("delta")), gamma=_number(raw.get("gamma_value")),
                theta=_number(leg.get("theta")), vega=_number(leg.get("vega")),
                distance_atm=_number(raw.get("distance_atm")),
                authority_rank=int(raw["rank"]) if raw.get("rank") is not None else None,
                authority_score=_number(raw.get("contract_score")), authority_status=str(raw.get("status") or "UNKNOWN"),
                rejection_reason=str(raw.get("rejection_reason")) if raw.get("rejection_reason") else None,
            )
            result.append(quote)
        # The parent snapshot ID is content-derived later; bind quotes to one stable precursor.
        precursor = _hash({"context": context.content_hash, "source": source_timestamp, "contracts": [row.contract_id for row in result]})[:24]
        rebound = []
        for row in result:
            value = row.to_dict()
            value["snapshot_id"] = f"analysis_contracts_{precursor}"
            value["content_hash"] = ""
            value["availability"] = row.availability
            value["freshness_state"] = row.freshness_state
            rebound.append(seal(OptionContractQuote(**value)))
        return rebound

    def _check_boundary(self, reasons, policy_name, left, right):
        a, b = _aware(left), _aware(right)
        if a is None or b is None:
            reasons.append(f"{policy_name.upper()}_BOUNDARY_UNAVAILABLE")
            return
        if abs((a - b).total_seconds()) > (self.policy.max_boundary_skew_seconds or {})[policy_name]:
            reasons.append(f"{policy_name.upper()}_INCOMPATIBLE")

    @staticmethod
    def _time_remaining(expiry: str | None, now: datetime) -> float | None:
        if not expiry:
            return None
        try:
            expires = datetime.combine(datetime.fromisoformat(expiry).date(), time(15, 30), tzinfo=IST)
        except ValueError:
            return None
        return max(0.0, (expires - now.astimezone(IST)).total_seconds())
