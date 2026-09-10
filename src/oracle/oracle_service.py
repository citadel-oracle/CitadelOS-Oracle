"""Deterministic, explainable, read-only Oracle market assessment service."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from src.core.config import Config
from src.scanner.watchlist import WATCHLIST


IST = ZoneInfo("Asia/Kolkata")


class UnsupportedOracleSymbol(ValueError):
    """Raised when an assessment is requested outside the production watchlist."""


@dataclass(frozen=True)
class OracleFeatureSummary:
    close: Optional[float]
    ema_21: Optional[float]
    ema_38: Optional[float]
    vwap: Optional[float]
    rsi_14: Optional[float]
    adx_14: Optional[float]
    atr_14: Optional[float]
    price_trend: str
    vwap_relationship: str
    momentum: str
    volatility: str
    volume_status: str
    liquidity: str
    timeframe_bias: str
    scanner_bias: str
    scanner_signal: str
    session_status: str


@dataclass(frozen=True)
class OracleSourceMetadata:
    source: str
    fallback_used: bool
    fallback_type: str
    snapshot_age_seconds: Optional[float]
    timestamp_semantics: str
    oracle_broker_calls: bool


@dataclass(frozen=True)
class OracleAssessment:
    symbol: str
    timeframe: str
    generated_at: str
    market_data_as_of: Optional[str]
    data_age_seconds: Optional[float]
    data_status: str
    oracle_status: str
    directional_bias: str
    signal: str
    confidence: Optional[int]
    confidence_label: str
    confidence_formula: str
    regime: str
    reason_codes: tuple[str, ...]
    reasoning: str
    input_features: OracleFeatureSummary
    warnings: tuple[str, ...]
    maturity_label: str
    source_metadata: OracleSourceMetadata

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        value["warnings"] = list(self.warnings)
        return value


class OracleService:
    """Consumes an existing dashboard snapshot cache and never refreshes it."""

    MATURITY_LABEL = "DETERMINISTIC_RULE_BASED_V1"
    CONFIDENCE_FORMULA = (
        "75% normalized directional feature alignment + 25% existing "
        "Kronos confidence; opposing evidence is subtracted"
    )
    MAX_DIRECTIONAL_WEIGHT = (
        Config.WEIGHT_EMA
        + Config.WEIGHT_RSI
        + Config.WEIGHT_VWAP
        + Config.WEIGHT_TIMEFRAME
    )

    def __init__(
        self,
        snapshot_provider: Optional[Callable[[], Optional[Mapping[str, Any]]]] = None,
        *,
        timeframe: str = "5m",
        max_live_age_seconds: float = 10.0,
        now_provider=None,
    ):
        self.snapshot_provider = snapshot_provider or (lambda: None)
        self.timeframe = str(timeframe)
        self.max_live_age_seconds = max(0.1, float(max_live_age_seconds))
        self.max_cached_age_seconds = self.max_live_age_seconds * 3
        self.now_provider = now_provider or (lambda: datetime.now(IST))
        self._cache: dict[str, OracleAssessment] = {}
        self._lock = Lock()

    @property
    def supported_symbols(self) -> tuple[str, ...]:
        return tuple(WATCHLIST)

    def status(self) -> dict[str, Any]:
        latest = self.assess("NIFTY")
        return {
            "status": latest.oracle_status,
            "supported_symbols": list(self.supported_symbols),
            "latest_assessment": latest.to_dict(),
            "data_status": latest.data_status,
            "maturity_label": self.MATURITY_LABEL,
            "last_updated": latest.generated_at,
        }

    def assess(self, symbol: str) -> OracleAssessment:
        normalized = str(symbol).strip().upper()
        if normalized not in WATCHLIST:
            raise UnsupportedOracleSymbol(
                f"Oracle does not support symbol {normalized or '<empty>'}"
            )

        with self._lock:
            now = self._now()
            try:
                source = self.snapshot_provider()
                assessment = self._assess_source(normalized, source, now)
            except Exception:
                assessment = self._fallback_or_unavailable(
                    normalized,
                    now,
                    "MARKET_SOURCE_MALFORMED",
                    "Market snapshot could not be interpreted safely",
                )
            if assessment.data_status in {"LIVE", "CACHED"} and assessment.input_features.close is not None:
                self._cache[normalized] = assessment
            return assessment

    def _assess_source(
        self,
        symbol: str,
        source: Optional[Mapping[str, Any]],
        now: datetime,
    ) -> OracleAssessment:
        if not isinstance(source, Mapping):
            return self._fallback_or_unavailable(
                symbol,
                now,
                "MARKET_SOURCE_UNAVAILABLE",
                "No existing market snapshot is available",
            )
        snapshot = source.get("snapshot")
        generated_at = source.get("generated_at")
        explicit_age = _number(source.get("age_seconds"))
        if not isinstance(snapshot, Mapping) or not isinstance(generated_at, datetime):
            return self._fallback_or_unavailable(
                symbol,
                now,
                "MARKET_SOURCE_MALFORMED",
                "Market snapshot metadata is malformed",
            )
        if generated_at.tzinfo is None:
            return self._fallback_or_unavailable(
                symbol,
                now,
                "MARKET_TIMESTAMP_INVALID",
                "Market snapshot timestamp is not timezone-aware",
            )
        generated_at = generated_at.astimezone(IST)
        age = explicit_age
        if age is None:
            age = (now - generated_at).total_seconds()
        if not math.isfinite(age) or age < 0:
            return self._fallback_or_unavailable(
                symbol,
                now,
                "MARKET_TIMESTAMP_INVALID",
                "Market snapshot age is invalid",
            )

        rows = snapshot.get("scanner")
        if not isinstance(rows, list):
            return self._fallback_or_unavailable(
                symbol,
                now,
                "MARKET_ROWS_UNAVAILABLE",
                "Market scanner rows are unavailable",
            )
        row = next(
            (
                item
                for item in rows
                if isinstance(item, Mapping)
                and str(item.get("symbol", "")).upper() == symbol
            ),
            None,
        )
        if row is None:
            return self._fallback_or_unavailable(
                symbol,
                now,
                "SYMBOL_DATA_UNAVAILABLE",
                "No scanner row is available for the requested symbol",
            )

        context = row.get("context")
        indicators = _context_mapping(context, "indicators")
        timeframe = _context_mapping(context, "timeframe")
        liquidity = _context_mapping(context, "liquidity")
        canonical_frame = _canonical_timeframe_frame(
            timeframe, self.timeframe
        )
        canonical_indicators = (
            canonical_frame.get("indicators")
            if isinstance(canonical_frame.get("indicators"), Mapping)
            else None
        )
        canonical_candles = canonical_frame.get("candles")
        canonical_latest = (
            canonical_candles[-1].get("time")
            if isinstance(canonical_candles, list)
            and canonical_candles
            and isinstance(canonical_candles[-1], Mapping)
            else None
        )
        if canonical_indicators is not None:
            indicators = canonical_indicators
        technical_readiness = (
            row.get("technical_readiness")
            if isinstance(row.get("technical_readiness"), Mapping)
            else {}
        )
        assessment_timeframe = str(
            self.timeframe if canonical_latest is not None
            else technical_readiness.get("timeframe") or self.timeframe
        )
        market_data_as_of = _aware_timestamp(
            canonical_latest
            if canonical_latest is not None
            else technical_readiness.get("latest_candle")
        ) or generated_at
        features = self._features(row, indicators, timeframe, liquidity, snapshot)
        required = (
            features.close,
            features.ema_21,
            features.ema_38,
            features.vwap,
            features.rsi_14,
            features.adx_14,
            features.atr_14,
        )
        quote_live = str(row.get("quote_status") or "").upper() == "LIVE"
        ltp = _number(row.get("ltp"))
        if ltp is None or features.close is None:
            return self._unavailable(
                symbol,
                now,
                "MARKET_PRICE_UNAVAILABLE",
                "Market price is unavailable",
                features=features,
                market_data_as_of=market_data_as_of,
                age=age,
            )

        if age <= self.max_live_age_seconds and quote_live:
            data_status = "LIVE"
        elif age <= self.max_cached_age_seconds:
            data_status = "CACHED"
        else:
            data_status = "STALE"

        if any(value is None for value in required):
            reason_code = str(
                technical_readiness.get("reason") or "INSUFFICIENT_FEATURES"
            )
            if reason_code not in {
                "INSUFFICIENT_FEATURES",
                "DHAN_HISTORY_UNAVAILABLE",
                "VOLUME_UNAVAILABLE",
            }:
                reason_code = "INSUFFICIENT_FEATURES"
            return self._insufficient(
                symbol,
                now,
                market_data_as_of,
                age,
                data_status,
                features,
                reason_code=reason_code,
            )

        bull, bear, neutral, reason_codes = self._directional_evidence(features)
        directional_bias = (
            "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
        )
        scanner_confidence = _bounded(_number(row.get("confidence")) or 0)
        feature_strength = max(bull, bear) / self.MAX_DIRECTIONAL_WEIGHT * 100
        conflict = min(bull, bear) / self.MAX_DIRECTIONAL_WEIGHT * 100
        confidence = round(
            _bounded(0.75 * max(0.0, feature_strength - conflict) + 0.25 * scanner_confidence)
        )
        if bull > 0 and bear > 0:
            reason_codes.append("CONFLICTING_DIRECTIONAL_EVIDENCE")

        regime = _regime(row.get("regime"), features.liquidity)
        warnings = []
        if features.volume_status == "UNAVAILABLE":
            warnings.append("VOLUME_DATA_UNAVAILABLE")
        if data_status == "CACHED":
            warnings.append("CACHED_MARKET_SNAPSHOT")
        elif data_status == "STALE":
            warnings.append("STALE_MARKET_SNAPSHOT")

        scanner_bias = features.scanner_bias
        trade_allowed = str(row.get("trade") or "").upper() == "YES"
        actionable_alignment = (
            regime == "TRENDING"
            and confidence >= Config.KRONOS_MIN_SCORE
            and trade_allowed
            and scanner_bias == directional_bias
        )
        if features.liquidity == "LOW_LIQUIDITY":
            signal = "NO_TRADE"
            oracle_status = "BLOCKED"
            reason_codes.append("LOW_LIQUIDITY_BLOCK")
        elif data_status == "STALE":
            signal = "NO_TRADE"
            oracle_status = "BLOCKED"
            reason_codes.append("STALE_DATA_BLOCK")
        elif data_status == "CACHED":
            signal = "WAIT"
            oracle_status = "DEGRADED"
            reason_codes.append("CACHED_DATA_WAIT")
        elif actionable_alignment and directional_bias == "BULLISH":
            signal = "LONG"
            oracle_status = "READY"
            reason_codes.append("BULLISH_ALIGNMENT")
        elif actionable_alignment and directional_bias == "BEARISH":
            signal = "SHORT"
            oracle_status = "READY"
            reason_codes.append("BEARISH_ALIGNMENT")
        else:
            signal = "WAIT"
            oracle_status = "READY"
            reason_codes.append("NO_ACTIONABLE_ALIGNMENT")

        if neutral >= max(bull, bear):
            directional_bias = "NEUTRAL"
            signal = "WAIT" if data_status != "STALE" else "NO_TRADE"
            reason_codes.append("NEUTRAL_EVIDENCE_DOMINANT")

        reasoning = _reasoning(reason_codes)
        return OracleAssessment(
            symbol=symbol,
            timeframe=assessment_timeframe,
            generated_at=now.isoformat(),
            market_data_as_of=market_data_as_of.isoformat(),
            data_age_seconds=round(age, 3),
            data_status=data_status,
            oracle_status=oracle_status,
            directional_bias=directional_bias,
            signal=signal,
            confidence=confidence,
            confidence_label=_confidence_label(confidence),
            confidence_formula=self.CONFIDENCE_FORMULA,
            regime=regime,
            reason_codes=tuple(_dedupe(reason_codes)),
            reasoning=reasoning,
            input_features=features,
            warnings=tuple(_dedupe(warnings)),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=OracleSourceMetadata(
                source="dashboard_snapshot_cache",
                fallback_used=data_status != "LIVE",
                fallback_type=(
                    "CACHED_SNAPSHOT" if data_status == "CACHED" else "STALE_SNAPSHOT" if data_status == "STALE" else "NONE"
                ),
                snapshot_age_seconds=round(age, 3),
                timestamp_semantics="backend scan completion time, not exchange tick time",
                oracle_broker_calls=False,
            ),
        )

    def _features(self, row, indicators, timeframe, liquidity, snapshot):
        close = _number(indicators.get("close"))
        ema21 = _number(indicators.get("ema_21"))
        ema38 = _number(indicators.get("ema_38"))
        vwap = _number(indicators.get("vwap"))
        rsi = _number(indicators.get("rsi_14"))
        adx = _number(indicators.get("adx_14"))
        atr = _number(indicators.get("atr_14"))
        price_trend = (
            "BULLISH" if None not in (close, ema21, ema38) and close > ema21 > ema38
            else "BEARISH" if None not in (close, ema21, ema38) and close < ema21 < ema38
            else "MIXED" if None not in (close, ema21, ema38)
            else "UNAVAILABLE"
        )
        vwap_relationship = (
            "ABOVE" if close is not None and vwap is not None and close > vwap
            else "BELOW" if close is not None and vwap is not None and close < vwap
            else "AT" if close is not None and vwap is not None
            else "UNAVAILABLE"
        )
        momentum = (
            "BULLISH" if rsi is not None and rsi >= Config.RSI_BUY
            else "BEARISH" if rsi is not None and rsi <= Config.RSI_SELL
            else "NEUTRAL" if rsi is not None
            else "UNAVAILABLE"
        )
        session = snapshot.get("status") if isinstance(snapshot, Mapping) else None
        session_details = session.get("session") if isinstance(session, Mapping) else None
        session_status = (
            "OPEN" if isinstance(session_details, Mapping) and session_details.get("market_open") is True
            else "CLOSED" if isinstance(session_details, Mapping) and session_details.get("market_open") is False
            else "UNAVAILABLE"
        )
        raw_liquidity = str(liquidity.get("type") or row.get("liquidity") or "UNAVAILABLE").upper()
        normalized_liquidity = "LOW_LIQUIDITY" if raw_liquidity == "LOW_LIQUIDITY" else raw_liquidity
        return OracleFeatureSummary(
            close=close,
            ema_21=ema21,
            ema_38=ema38,
            vwap=vwap,
            rsi_14=rsi,
            adx_14=adx,
            atr_14=atr,
            price_trend=price_trend,
            vwap_relationship=vwap_relationship,
            momentum=momentum,
            volatility=str(row.get("regime") or "UNKNOWN").upper(),
            volume_status="UNAVAILABLE",
            liquidity=normalized_liquidity,
            timeframe_bias=str(timeframe.get("bias") or row.get("mtf_bias") or "UNKNOWN").upper(),
            scanner_bias=str(row.get("bias") or "NEUTRAL").upper(),
            scanner_signal=str(row.get("pullback_signal") or "WAIT").upper(),
            session_status=session_status,
        )

    def _directional_evidence(self, features):
        bull = bear = neutral = 0
        reasons = []
        if features.ema_21 > features.ema_38:
            bull += Config.WEIGHT_EMA
            reasons.append("EMA_BULLISH")
        elif features.ema_21 < features.ema_38:
            bear += Config.WEIGHT_EMA
            reasons.append("EMA_BEARISH")
        else:
            neutral += Config.WEIGHT_EMA
            reasons.append("EMA_FLAT")

        if features.rsi_14 >= Config.RSI_BUY:
            bull += Config.WEIGHT_RSI
            reasons.append("RSI_BULLISH")
        elif features.rsi_14 <= Config.RSI_SELL:
            bear += Config.WEIGHT_RSI
            reasons.append("RSI_BEARISH")
        else:
            neutral += Config.WEIGHT_RSI
            reasons.append("RSI_NEUTRAL")

        if features.close > features.vwap:
            bull += Config.WEIGHT_VWAP
            reasons.append("PRICE_ABOVE_VWAP")
        elif features.close < features.vwap:
            bear += Config.WEIGHT_VWAP
            reasons.append("PRICE_BELOW_VWAP")
        else:
            neutral += Config.WEIGHT_VWAP
            reasons.append("PRICE_AT_VWAP")

        if features.timeframe_bias == "BULLISH":
            bull += Config.WEIGHT_TIMEFRAME
            reasons.append("MTF_BULLISH")
        elif features.timeframe_bias == "BEARISH":
            bear += Config.WEIGHT_TIMEFRAME
            reasons.append("MTF_BEARISH")
        else:
            neutral += Config.WEIGHT_TIMEFRAME
            reasons.append("MTF_NEUTRAL")
        return bull, bear, neutral, reasons

    def _insufficient(
        self,
        symbol,
        now,
        market_time,
        age,
        data_status,
        features,
        *,
        reason_code="INSUFFICIENT_FEATURES",
    ):
        reasoning = (
            "Dhan completed-candle history is unavailable; actionable output is blocked."
            if reason_code == "DHAN_HISTORY_UNAVAILABLE"
            else "Required production indicators are incomplete; actionable output is blocked."
        )
        return OracleAssessment(
            symbol=symbol,
            timeframe=self.timeframe,
            generated_at=now.isoformat(),
            market_data_as_of=market_time.isoformat(),
            data_age_seconds=round(age, 3),
            data_status=data_status,
            oracle_status="DEGRADED",
            directional_bias="NEUTRAL",
            signal="NO_TRADE",
            confidence=None,
            confidence_label="UNAVAILABLE",
            confidence_formula=self.CONFIDENCE_FORMULA,
            regime="UNKNOWN",
            reason_codes=(reason_code,),
            reasoning=reasoning,
            input_features=features,
            warnings=("INDICATOR_DATA_INCOMPLETE",),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=self._metadata(data_status, age),
        )

    def _fallback_or_unavailable(self, symbol, now, code, reason):
        cached = self._cache.get(symbol)
        if cached is None or cached.market_data_as_of is None:
            return self._unavailable(symbol, now, code, reason)
        market_time = datetime.fromisoformat(cached.market_data_as_of)
        age = max(0.0, (now - market_time).total_seconds())
        data_status = "CACHED" if age <= self.max_cached_age_seconds else "STALE"
        return replace(
            cached,
            generated_at=now.isoformat(),
            data_age_seconds=round(age, 3),
            data_status=data_status,
            oracle_status="DEGRADED" if data_status == "CACHED" else "BLOCKED",
            signal="WAIT" if data_status == "CACHED" else "NO_TRADE",
            reason_codes=tuple(_dedupe(list(cached.reason_codes) + [code, "FALLBACK_LAST_ASSESSMENT"])),
            reasoning=reason,
            warnings=tuple(_dedupe(list(cached.warnings) + ["FALLBACK_LAST_ASSESSMENT"])),
            source_metadata=OracleSourceMetadata(
                source="process_local_oracle_cache",
                fallback_used=True,
                fallback_type="LAST_ASSESSMENT",
                snapshot_age_seconds=round(age, 3),
                timestamp_semantics="original backend scan completion time",
                oracle_broker_calls=False,
            ),
        )

    def _unavailable(
        self,
        symbol,
        now,
        code,
        reason,
        *,
        features=None,
        market_data_as_of=None,
        age=None,
    ):
        return OracleAssessment(
            symbol=symbol,
            timeframe=self.timeframe,
            generated_at=now.isoformat(),
            market_data_as_of=(market_data_as_of.isoformat() if market_data_as_of else None),
            data_age_seconds=round(age, 3) if age is not None else None,
            data_status="UNAVAILABLE",
            oracle_status="UNAVAILABLE",
            directional_bias="NEUTRAL",
            signal="NO_TRADE",
            confidence=None,
            confidence_label="UNAVAILABLE",
            confidence_formula=self.CONFIDENCE_FORMULA,
            regime="UNKNOWN",
            reason_codes=(code,),
            reasoning=reason,
            input_features=features or _empty_features(),
            warnings=(code,),
            maturity_label=self.MATURITY_LABEL,
            source_metadata=self._metadata("UNAVAILABLE", age),
        )

    @staticmethod
    def _metadata(data_status, age):
        return OracleSourceMetadata(
            source="dashboard_snapshot_cache",
            fallback_used=data_status != "LIVE",
            fallback_type=data_status,
            snapshot_age_seconds=round(age, 3) if age is not None else None,
            timestamp_semantics="backend scan completion time, not exchange tick time",
            oracle_broker_calls=False,
        )

    def _now(self):
        value = self.now_provider()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Oracle clock must be timezone-aware")
        return value.astimezone(IST)


def _context_mapping(context: Any, name: str) -> Mapping[str, Any]:
    if isinstance(context, Mapping):
        value = context.get(name)
    else:
        value = getattr(context, name, None)
    return value if isinstance(value, Mapping) else {}


def _canonical_timeframe_frame(
    timeframe: Mapping[str, Any], name: str
) -> Mapping[str, Any]:
    frames = timeframe.get("timeframes")
    if not isinstance(frames, Mapping):
        return {}
    frame = frames.get(str(name).lower())
    return frame if isinstance(frame, Mapping) else {}


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _aware_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            parsed = datetime.fromtimestamp(timestamp, tz=IST)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(IST)


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _regime(raw_regime: Any, liquidity: str) -> str:
    if liquidity == "LOW_LIQUIDITY":
        return "LOW_LIQUIDITY"
    value = str(raw_regime or "").upper()
    if value == "TRENDING":
        return "TRENDING"
    if value in {"SIDEWAYS", "RANGING", "MIXED"}:
        return "RANGING"
    if value == "VOLATILE":
        return "VOLATILE"
    return "UNKNOWN"


def _confidence_label(value: Optional[int]) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value >= 80:
        return "HIGH"
    if value >= 60:
        return "MODERATE"
    return "LOW"


def _reasoning(codes: list[str]) -> str:
    visible = [code.replace("_", " ").lower() for code in _dedupe(codes)[:4]]
    return "Deterministic evidence: " + "; ".join(visible) + "."


def _dedupe(items):
    return list(dict.fromkeys(item for item in items if item))


def _empty_features():
    return OracleFeatureSummary(
        close=None,
        ema_21=None,
        ema_38=None,
        vwap=None,
        rsi_14=None,
        adx_14=None,
        atr_14=None,
        price_trend="UNAVAILABLE",
        vwap_relationship="UNAVAILABLE",
        momentum="UNAVAILABLE",
        volatility="UNKNOWN",
        volume_status="UNAVAILABLE",
        liquidity="UNAVAILABLE",
        timeframe_bias="UNKNOWN",
        scanner_bias="NEUTRAL",
        scanner_signal="WAIT",
        session_status="UNAVAILABLE",
    )
