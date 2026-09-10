"""Deterministic numerical verification for Phase-2 visual claim candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.oracle.contracts.perception import (
    Availability, CanonicalCandleRef, CompletionStatus, FreshnessState,
    VerifiedVisualClaim, VisualClaimCandidate, seal,
)


class VisualClaimVerifier:
    VERSION = "visual-verifier-1.0.1"

    def __init__(self, *, clock=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def verify(self, candidate: VisualClaimCandidate, candles: Sequence[CanonicalCandleRef], *, allow_historical: bool = False) -> VerifiedVisualClaim:
        now = self.clock()
        if not candidate.verify_hash():
            return self._result(candidate, now, "UNVERIFIABLE", (), (), {}, (), (), ("VALID_CANDIDATE_HASH",))
        valid = [c for c in candles if c.symbol == candidate.symbol and c.timeframe == candidate.timeframe and c.verify_hash()]
        cross = [c for c in candles if c.symbol != candidate.symbol or c.timeframe != candidate.timeframe]
        missing, conflicts = [], []
        if cross:
            conflicts.append("CROSS_SYMBOL_OR_TIMEFRAME_INPUT_REJECTED")
        if not valid:
            missing.append("CANONICAL_CANDLES")
            return self._result(candidate, now, "UNVERIFIABLE", (), (), {}, (), conflicts, missing)
        if any(c.freshness_state is FreshnessState.STALE for c in valid) and not allow_historical:
            missing.append("FRESH_CANONICAL_CANDLES")
            return self._result(candidate, now, "UNVERIFIABLE", (), valid, {}, (), conflicts, missing)
        p = dict(candidate.predicates)
        claim_type = candidate.claim_type
        if claim_type == "TREND":
            result = self._trend(candidate.direction, valid, p)
        elif claim_type == "STRUCTURE_BREAK":
            result = self._break(candidate.direction, valid, p, candidate.declared_tolerance)
        elif claim_type == "LEVEL_ACCEPTANCE":
            result = self._accept(candidate.direction, valid, p, candidate.declared_tolerance)
        elif claim_type == "LEVEL_REJECTION":
            result = self._reject(candidate.direction, valid, p, candidate.declared_tolerance)
        elif claim_type == "LIQUIDITY_SWEEP":
            result = self._sweep(candidate.direction, valid, p, candidate.declared_tolerance)
        else:
            result = ("UNVERIFIABLE", (), {}, (), (), ("CLAIM_TYPE_NOT_IMPLEMENTED",))
        status, predicates, values, support, conflict_more, missing_more = result
        return self._result(candidate, now, status, predicates, valid, values, support, conflicts + list(conflict_more), missing + list(missing_more))

    @staticmethod
    def _trend(direction, candles, p):
        count = max(2, int(p.get("lookback", 3)))
        closes = [c.close for c in candles[-count:]]
        if len(closes) < count:
            return "UNVERIFIABLE", (), {"closes": closes}, (), (), ("LOOKBACK",)
        bullish = all(b > a for a, b in zip(closes, closes[1:]))
        bearish = all(b < a for a, b in zip(closes, closes[1:]))
        passed = bullish if direction in {"BULLISH", "UP", "ABOVE"} else bearish
        predicate = ({"name": "monotonic_completed_closes", "passed": passed, "count": count},)
        return ("VERIFIED" if passed else "REJECTED"), predicate, {"closes": closes}, (("MONOTONIC_CLOSES",) if passed else ()), (("NON_MONOTONIC_CLOSES",) if not passed else ()), ()

    @staticmethod
    def _break(direction, candles, p, tolerance):
        if "level" not in p:
            return "UNVERIFIABLE", (), {}, (), (), ("LEVEL",)
        level, close = float(p["level"]), candles[-1].close
        passed = close > level + tolerance if direction in {"BULLISH", "UP", "ABOVE"} else close < level - tolerance
        pred = ({"name": "completed_close_beyond_level", "passed": passed, "level": level, "close": close},)
        return ("VERIFIED" if passed else "REJECTED"), pred, {"level": level, "close": close}, (("CLOSE_BREAK",) if passed else ()), (("NO_COMPLETED_CLOSE_BREAK",) if not passed else ()), ()

    @staticmethod
    def _accept(direction, candles, p, tolerance):
        if "level" not in p:
            return "UNVERIFIABLE", (), {}, (), (), ("LEVEL",)
        level, required = float(p["level"]), max(1, int(p.get("min_closes", 2)))
        closes = [c.close for c in candles[-required:]]
        passed = len(closes) == required and all(c > level + tolerance for c in closes) if direction in {"ABOVE", "BULLISH", "UP"} else len(closes) == required and all(c < level - tolerance for c in closes)
        pred = ({"name": "consecutive_closes_accepted", "passed": passed, "required": required},)
        return ("VERIFIED" if passed else "REJECTED"), pred, {"level": level, "closes": closes}, (("ACCEPTANCE_CONFIRMED",) if passed else ()), (("ACCEPTANCE_NOT_CONFIRMED",) if not passed else ()), ()

    @staticmethod
    def _reject(direction, candles, p, tolerance):
        if "level" not in p:
            return "UNVERIFIABLE", (), {}, (), (), ("LEVEL",)
        level, candle = float(p["level"]), candles[-1]
        reject_above = direction in {"BEARISH", "DOWN", "BELOW"}
        breached = candle.high > level + tolerance if reject_above else candle.low < level - tolerance
        closed_back = candle.close < level if reject_above else candle.close > level
        passed = breached and closed_back
        preds = ({"name": "level_breached", "passed": breached}, {"name": "completed_close_back_inside", "passed": closed_back})
        return ("VERIFIED" if passed else "REJECTED"), preds, {"level": level, "high": candle.high, "low": candle.low, "close": candle.close}, (("REJECTION_CONFIRMED",) if passed else ()), (("REJECTION_NOT_CONFIRMED",) if not passed else ()), ()

    @staticmethod
    def _sweep(direction, candles, p, tolerance):
        required = ("level", "prior_level_candle_id", "window")
        missing = tuple(key.upper() for key in required if p.get(key) in (None, ""))
        if missing:
            return "UNVERIFIABLE", (), {}, (), (), missing
        level, window = float(p["level"]), max(1, int(p["window"]))
        sample = candles[-window:]
        if not sample:
            return "UNVERIFIABLE", (), {}, (), (), ("WINDOW_CANDLES",)
        sweep_below = direction in {"BULLISH", "UP", "ABOVE"}
        breached = any(c.low < level - tolerance for c in sample) if sweep_below else any(c.high > level + tolerance for c in sample)
        reclaimed = sample[-1].close > level if sweep_below else sample[-1].close < level
        level_identified = any(c.candle_id == str(p["prior_level_candle_id"]) for c in candles)
        passed = level_identified and breached and reclaimed
        preds = ({"name": "identified_prior_level", "passed": level_identified},
                 {"name": "breach_beyond_tolerance", "passed": breached},
                 {"name": "completed_close_reclaim", "passed": reclaimed})
        conflict = () if passed else (("WICK_ONLY_NO_RECLAIM",) if breached and not reclaimed else ("SWEEP_PREDICATES_FAILED",))
        return ("VERIFIED" if passed else "REJECTED"), preds, {"level": level, "last_close": sample[-1].close,
                "window_high": max(c.high for c in sample), "window_low": min(c.low for c in sample)}, (("SWEEP_RECLAIM_CONFIRMED",) if passed else ()), conflict, ()

    def _result(self, candidate, now, status, predicates, candles, values, support, conflicts, missing):
        source = max((c.source_timestamp for c in candles), default=candidate.source_timestamp)
        historical = any(c.freshness_state is FreshnessState.STALE for c in candles)
        return seal(VerifiedVisualClaim(
            correlation_id=candidate.correlation_id, instrument_id=candidate.instrument_id, symbol=candidate.symbol,
            timeframe=candidate.timeframe, source_timestamp=source, generated_at=now.isoformat(), as_of=source,
            availability=(Availability.HISTORICAL if historical else Availability.AVAILABLE) if status in {"VERIFIED", "REJECTED", "PARTIALLY_VERIFIED"} else Availability.UNAVAILABLE,
            freshness_state=FreshnessState.STALE if historical else (FreshnessState.FRESH if status != "UNVERIFIABLE" else FreshnessState.UNKNOWN),
            source_ids={"candidate": candidate.claim_id, **{f"candle_{i}": c.candle_id for i, c in enumerate(candles)}},
            dependency_versions={"candidate_hash": candidate.content_hash, "verifier": self.VERSION},
            completion_status=CompletionStatus.COMPLETE,
            provenance={"service": "VisualClaimVerifier", "numerical_authority": "CITADEL_CANONICAL_CANDLES",
                        "historical_proof": historical, "execution_influence": "ZERO"},
            claim_id=candidate.claim_id, observation_id=candidate.observation_id, claim_type=candidate.claim_type,
            status=status, predicates_evaluated=tuple(predicates), input_record_ids=tuple(c.candle_id for c in candles),
            numerical_values=values, tolerances={"declared": candidate.declared_tolerance},
            supporting_evidence=tuple(support), conflicting_evidence=tuple(conflicts), missing_evidence=tuple(missing),
            verifier_version=self.VERSION, actionable_evidence_weight=0.0,
        ))
