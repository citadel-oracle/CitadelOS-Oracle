"""Advisory exact-option-premium-first composition over existing authorities."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Mapping

from src.oracle.contracts.analysis import Availability, FreshnessState
from src.oracle.contracts.tradingview import TradingViewChartState
from src.oracle.tradingview_sync import PerformanceTelemetry


class ExactOptionAnalysisError(RuntimeError):
    pass


class ExactOptionPremiumAnalysisService:
    """Compose OSE premium technicals with Phase-3 quotes; calculate nothing."""

    REQUIRED_QUOTE_FIELDS = (
        "bid", "ask", "spread_abs", "spread_pct", "bid_depth", "ask_depth",
        "volume", "oi", "iv", "delta", "gamma", "theta", "vega",
    )

    def __init__(
        self,
        technical_provider: Callable[[Mapping[str, Any], Any], Mapping[str, Any]],
        *,
        telemetry: PerformanceTelemetry | None = None,
    ) -> None:
        self.technical_provider = technical_provider
        self.telemetry = telemetry or PerformanceTelemetry()

    def analyze(self, chart: TradingViewChartState, result: Any,
                *, technical_override: Mapping[str, Any] | None = None) -> dict[str, Any]:
        option = chart.option
        if option is None or not option.security_id:
            raise ExactOptionAnalysisError("EXACT_OPTION_SECURITY_ID_UNAVAILABLE")
        if option.underlying != result.snapshot.symbol:
            return self._insufficient(chart, "UNDERLYING_IDENTITY_MISMATCH")

        current = next((row for row in result.snapshot.candidate_contracts
                        if str(row.contract_id) == str(option.security_id)), None)
        quote = current.to_dict() if current is not None else None
        observed_at = (result.snapshot.source_timestamps.get("argus")
                       or result.snapshot.source_timestamp)
        contract = {
            "security_id": option.security_id, "side": option.option_side,
            "option_type": option.option_side, "expiry": option.expiry,
            "strike": option.strike, "trading_symbol": option.trading_symbol,
            "premium": quote.get("ltp") if quote else None,
        }

        technical_started = perf_counter()
        if technical_override is not None:
            technical = dict(technical_override)
        else:
            try:
                technical = dict(self.technical_provider(contract, observed_at))
            except Exception as error:
                self.telemetry.record("exact_premium_candle_retrieval",
                                      (perf_counter() - technical_started) * 1000, error=True)
                technical = {"status": "UNAVAILABLE", "reason": f"{type(error).__name__}:{error}"}
        self._record_technical_performance(technical, technical_started)

        missing: list[str] = []
        if current is None:
            missing.append("EXACT_OPTION_QUOTE_NOT_IN_CANONICAL_CANDIDATES")
        technical_available = str(technical.get("status")) == "AVAILABLE"
        candle_fields = ("completed_1m_count", "completed_3m_count", "completed_5m_count")
        candles_available = technical_available and all(technical.get(name) for name in candle_fields)
        features_available = (technical_available and isinstance(technical.get("trend"), Mapping)
                              and bool(technical.get("trend"))
                              and isinstance(technical.get("vob_3m"), Mapping)
                              and bool(technical.get("vob_3m")))
        if not technical_available:
            reason = str(technical.get("reason") or "EXACT_PREMIUM_FEATURES_UNAVAILABLE")
            missing.extend(["EXACT_PREMIUM_CANDLES_UNAVAILABLE", "EXACT_PREMIUM_FEATURES_UNAVAILABLE", reason])
        else:
            if not candles_available:
                missing.append("EXACT_PREMIUM_CANDLES_UNAVAILABLE")
            if not features_available:
                missing.append("EXACT_PREMIUM_FEATURES_UNAVAILABLE")
        if current is not None:
            if current.availability is not Availability.AVAILABLE or current.freshness_state is not FreshnessState.FRESH:
                missing.append("STALE_OPTION_QUOTE")
            for field in self.REQUIRED_QUOTE_FIELDS:
                if getattr(current, field) is None:
                    missing.append(f"{field.upper()}_UNAVAILABLE")

        records = dict(result.snapshot.source_records)
        for authority in ("argus_tactical", "ose", "vob"):
            if not isinstance(records.get(authority), Mapping) or not records.get(authority):
                missing.append(f"{authority.upper()}_UNAVAILABLE")

        trend = dict(technical.get("trend") or {})
        premium_vob = dict(technical.get("vob_3m") or {})
        trigger_level = premium_vob.get("breakout_trigger")
        if trigger_level is None:
            trigger_level = (trend.get("ema_21_zone") or {}).get("high") if isinstance(trend.get("ema_21_zone"), Mapping) else None
        support = premium_vob.get("support")
        invalidation_level = support.get("zone_low") if isinstance(support, Mapping) else trend.get("supertrend_value")

        rejected = dict(result.option_capture.rejected_contracts)
        material_reasons = list(rejected.get(str(option.security_id)) or ())
        eligible_ids = {str(value) for value in result.option_capture.eligible_contract_ids}
        if missing:
            verdict = "INSUFFICIENT_EVIDENCE"
            alternative = None
        elif str(option.security_id) in eligible_ids:
            verdict = "KEEP_CURRENT_CONTRACT"
            alternative = None
        else:
            verdict = "REJECT_CURRENT_CONTRACT"
            alternative = self._verified_alternative(result, current, observed_at)
            if not material_reasons:
                material_reasons = ["CURRENT_CONTRACT_FAILED_EXISTING_PHASE3_ELIGIBILITY"]

        confirmations = self._confirmations(result, option.option_side, current)
        spread_quality = "UNAVAILABLE"
        if current is not None and current.spread_pct is not None:
            spread_quality = "UNACCEPTABLE" if "SPREAD_UNACCEPTABLE" in material_reasons else "ACCEPTABLE"
        hostile = {"DELTA_UNSUITABLE_OR_MISSING", "IV_HOSTILITY", "THETA_DECAY_HOSTILITY"}
        greeks_condition = "HOSTILE" if hostile.intersection(material_reasons) else "VERIFIED" if current else "UNAVAILABLE"
        entry_band = None
        if current is not None and current.ask is not None and current.spread_abs is not None:
            entry_band = [round(current.ask, 4), round(current.ask + current.spread_abs * 0.5, 4)]

        return {
            "status": "AVAILABLE" if verdict != "INSUFFICIENT_EVIDENCE" else "INSUFFICIENT_EVIDENCE",
            "verdict": verdict,
            "current_contract_analyzed_first": True,
            "comparison_sequence": [str(option.security_id), "ALTERNATIVES_AFTER_CURRENT"],
            "exact_contract": {
                "trading_symbol": option.trading_symbol, "security_id": option.security_id,
                "underlying": option.underlying, "expiry": option.expiry,
                "strike": option.strike, "option_side": option.option_side,
            },
            "premium_candles": {
                "status": "AVAILABLE" if candles_available else "UNAVAILABLE", "source": technical.get("source"),
                "completed_1m_count": technical.get("completed_1m_count"),
                "completed_3m_count": technical.get("completed_3m_count"),
                "completed_5m_count": technical.get("completed_5m_count") or technical.get("candle_count"),
                "forming_candle_excluded": technical.get("forming_candle_excluded"),
                "evaluated_through": technical.get("completed_5m_close_timestamp"),
            },
            "premium_features": {
                "authority": "OPTIONS_STRUCTURE_ENGINE",
                "status": "AVAILABLE" if features_available else "UNAVAILABLE", "trend": trend,
                "structure": premium_vob, "pullback_state": technical.get("pullback_state"),
                "ema_21": trend.get("ema_21"), "ema_50": trend.get("ema_50"),
                "atr": trend.get("atr"), "volume": technical.get("latest_completed_5m_volume"),
                "vwap": None, "vwap_status": "EXISTING_AUTHORITY_UNAVAILABLE",
            },
            "premium_trigger": {"predicate": "COMPLETED_PREMIUM_CLOSE_ABOVE", "level": trigger_level},
            "premium_invalidation": {"predicate": "PREMIUM_STRUCTURE_FAILURE", "level": invalidation_level},
            "executable_entry_band": entry_band,
            "quote": quote,
            "spread_quality": spread_quality,
            "greeks_iv_condition": greeks_condition,
            "confirmations": confirmations,
            "current_contract_suitability": verdict,
            "material_rejection_reasons": material_reasons,
            "alternative_contract": alternative,
            "missing_evidence": sorted(set(missing)),
            "optional_unavailable": ["PREMIUM_VWAP_AUTHORITY_UNAVAILABLE"],
            "freshness": quote.get("freshness_state") if quote else "UNAVAILABLE",
            "source_timestamp": quote.get("source_timestamp") if quote else observed_at,
            "execution_influence": "ZERO", "execution_authority": False,
        }

    def _record_technical_performance(self, technical: Mapping[str, Any], started: float) -> None:
        performance = dict(technical.get("performance") or {})
        fallback = (perf_counter() - started) * 1000
        for stage, key in (
            ("refresh_1m", "refresh_1m_ms"), ("refresh_3m", "refresh_3m_ms"),
            ("refresh_5m", "refresh_5m_ms"),
            ("exact_premium_candle_retrieval", "candle_retrieval_ms"),
            ("exact_premium_feature_retrieval", "feature_retrieval_ms"),
        ):
            self.telemetry.record(stage, performance.get(key, fallback if stage == "exact_premium_candle_retrieval" else 0.0),
                                  error=str(technical.get("status")) != "AVAILABLE")

    @staticmethod
    def _confirmations(result: Any, side: str, current: Any) -> dict[str, Any]:
        records = dict(result.snapshot.source_records)
        ose = dict(records.get("ose") or {})
        duel = str(dict(ose.get("duel") or {}).get("state") or "UNAVAILABLE")
        aligned = (side == "CE" and "CALL ADVANTAGE" in duel) or (side == "PE" and "PUT ADVANTAGE" in duel)
        vob = dict(records.get("vob") or {})
        return {
            "underlying": {"posture": result.underlying.directional_posture,
                           "confirmed": (side == "CE" and result.underlying.directional_posture == "BULLISH")
                           or (side == "PE" and result.underlying.directional_posture == "BEARISH")},
            "argus": {"status": getattr(current, "authority_status", None),
                      "rank": getattr(current, "authority_rank", None),
                      "score": getattr(current, "authority_score", None)},
            "ose": {"duel": duel, "confirmed": aligned},
            "vob": {"status": vob.get("status") or vob.get("decision_boundary_5m") or "AVAILABLE",
                    "confirmed": bool(vob)},
        }

    def _verified_alternative(self, result: Any, current: Any, observed_at: Any) -> dict[str, Any] | None:
        selected_id = result.option_capture.selected_contract_id
        if not selected_id or (current is not None and str(selected_id) == str(current.contract_id)):
            return None
        eligible = {str(value) for value in result.option_capture.eligible_contract_ids}
        candidate = next((row for row in result.snapshot.candidate_contracts
                          if str(row.contract_id) == str(selected_id)), None)
        if candidate is None or str(candidate.contract_id) not in eligible:
            return None
        if candidate.availability is not Availability.AVAILABLE or candidate.freshness_state is not FreshnessState.FRESH:
            return None
        missing = [field for field in ExactOptionPremiumAnalysisService.REQUIRED_QUOTE_FIELDS
                   if getattr(candidate, field) is None]
        if missing:
            return None
        technical_started = perf_counter()
        try:
            technical = dict(self.technical_provider({
                "security_id": candidate.contract_id, "option_type": candidate.option_type,
                "side": candidate.option_type, "expiry": candidate.expiry,
                "strike": candidate.strike, "trading_symbol": candidate.trading_symbol,
                "premium": candidate.ltp,
            }, observed_at))
        except Exception:
            self.telemetry.record("exact_premium_candle_retrieval",
                                  (perf_counter() - technical_started) * 1000, error=True)
            return None
        self._record_technical_performance(technical, technical_started)
        if (str(technical.get("status")) != "AVAILABLE"
                or any(not technical.get(name) for name in (
                    "completed_1m_count", "completed_3m_count", "completed_5m_count"))
                or not isinstance(technical.get("trend"), Mapping)
                or not isinstance(technical.get("vob_3m"), Mapping)):
            return None
        reasons = []
        if current is not None:
            if candidate.spread_pct is not None and current.spread_pct is not None and candidate.spread_pct < current.spread_pct:
                reasons.append("TIGHTER_SPREAD")
            if candidate.authority_score is not None and current.authority_score is not None and candidate.authority_score > current.authority_score:
                reasons.append("HIGHER_AUTHORITATIVE_CONTRACT_SCORE")
            if candidate.bid_depth and current.bid_depth and candidate.bid_depth > current.bid_depth:
                reasons.append("STRONGER_BID_DEPTH")
        return {**candidate.to_dict(), "comparison_reasons": reasons or ["EXISTING_PHASE3_ELIGIBLE_SELECTION"],
                "premium_verification": {
                    "status": technical.get("status"), "source": technical.get("source"),
                    "completed_1m_count": technical.get("completed_1m_count"),
                    "completed_3m_count": technical.get("completed_3m_count"),
                    "completed_5m_count": technical.get("completed_5m_count"),
                    "trend": technical.get("trend"), "structure": technical.get("vob_3m"),
                }}

    @staticmethod
    def _insufficient(chart: TradingViewChartState, reason: str) -> dict[str, Any]:
        option = chart.option
        return {
            "status": "INSUFFICIENT_EVIDENCE", "verdict": "INSUFFICIENT_EVIDENCE",
            "current_contract_analyzed_first": True,
            "exact_contract": option.to_dict() if hasattr(option, "to_dict") else {
                "trading_symbol": option.trading_symbol if option else None,
                "security_id": option.security_id if option else None,
            },
            "missing_evidence": [reason], "alternative_contract": None,
            "execution_influence": "ZERO", "execution_authority": False,
        }
