import importlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.execution.paper_state import PaperStateService
from src.oracle.oracle_service import OracleService, UnsupportedOracleSymbol


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 10, 10, 0, tzinfo=IST)


class MutableClock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


class MutableProvider:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


def scanner_row(symbol="NIFTY", **changes):
    row = {
        "symbol": symbol,
        "ltp": 110,
        "quote_status": "LIVE",
        "regime": "TRENDING",
        "bias": "BULLISH",
        "confidence": 80,
        "trade": "YES",
        "pullback_signal": "BUY",
        "mtf_bias": "BULLISH",
        "liquidity": "BULLISH_SWEEP",
        "context": {
            "indicators": {
                "close": 110,
                "ema_21": 105,
                "ema_38": 100,
                "vwap": 104,
                "rsi_14": 60,
                "adx_14": 25,
                "atr_14": 3,
            },
            "timeframe": {"bias": "BULLISH", "confidence": 80},
            "liquidity": {"type": "BULLISH_SWEEP", "score": 85},
        },
    }
    row.update(changes)
    return row


def source(row=None, age=1.0, generated_at=NOW):
    return {
        "snapshot": {
            "status": {"session": {"market_open": True}},
            "scanner": [row or scanner_row()],
        },
        "generated_at": generated_at,
        "age_seconds": age,
    }


def service_for(value, clock=None):
    provider = MutableProvider(value)
    oracle = OracleService(
        snapshot_provider=provider,
        timeframe="5m",
        max_live_age_seconds=10,
        now_provider=clock or MutableClock(),
    )
    return oracle, provider


def bearish_row():
    return scanner_row(
        ltp=90,
        bias="BEARISH",
        confidence=82,
        pullback_signal="SELL",
        mtf_bias="BEARISH",
        context={
            "indicators": {
                "close": 90,
                "ema_21": 95,
                "ema_38": 100,
                "vwap": 96,
                "rsi_14": 40,
                "adx_14": 28,
                "atr_14": 3,
            },
            "timeframe": {"bias": "BEARISH", "confidence": 80},
            "liquidity": {"type": "BEARISH_SWEEP", "score": 85},
        },
    )


def test_oracle_result_contract_is_complete_and_typed():
    oracle, _ = service_for(source())

    payload = oracle.assess("NIFTY").to_dict()

    assert set(payload) == {
        "symbol",
        "timeframe",
        "generated_at",
        "market_data_as_of",
        "data_age_seconds",
        "data_status",
        "oracle_status",
        "directional_bias",
        "signal",
        "confidence",
        "confidence_label",
        "confidence_formula",
        "regime",
        "reason_codes",
        "reasoning",
        "input_features",
        "warnings",
        "maturity_label",
        "source_metadata",
    }
    assert payload["maturity_label"] == "DETERMINISTIC_RULE_BASED_V1"
    assert payload["source_metadata"]["oracle_broker_calls"] is False


def test_oracle_lineage_uses_latest_completed_candle_not_scan_time():
    completed = NOW - timedelta(minutes=1)
    row = scanner_row(
        technical_readiness={
            "status": "READY",
            "reason": "READY",
            "timeframe": "1m",
            "latest_candle": completed.isoformat(),
        }
    )
    oracle, _ = service_for(source(row, generated_at=NOW))

    payload = oracle.assess("NIFTY").to_dict()

    assert payload["timeframe"] == "1m"
    assert payload["market_data_as_of"] == completed.isoformat()


def test_oracle_uses_completed_canonical_5m_frame_without_forming_1m_data():
    boundary = NOW - timedelta(minutes=5)
    row = scanner_row(
        technical_readiness={
            "status": "READY",
            "reason": "READY",
            "timeframe": "1m",
            "latest_candle": (NOW - timedelta(minutes=1)).isoformat(),
        }
    )
    row["context"]["timeframe"]["timeframes"] = {
        "5m": {
            "candles": [
                {
                    "time": boundary.timestamp(),
                    "open": 105,
                    "high": 112,
                    "low": 104,
                    "close": 110,
                    "volume": 10_000,
                }
            ],
            "indicators": row["context"]["indicators"],
        }
    }
    oracle, _ = service_for(source(row, generated_at=NOW))

    payload = oracle.assess("NIFTY").to_dict()

    assert payload["timeframe"] == "5m"
    assert payload["market_data_as_of"] == boundary.isoformat()
    assert payload["input_features"]["close"] == 110


@pytest.mark.parametrize(
    "symbol", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
)
def test_all_supported_symbols_can_be_assessed(symbol):
    oracle, _ = service_for(source(scanner_row(symbol=symbol)))

    assessment = oracle.assess(symbol)

    assert assessment.symbol == symbol
    assert assessment.oracle_status == "READY"


def test_unsupported_symbol_is_rejected_cleanly():
    oracle, provider = service_for(source())

    with pytest.raises(UnsupportedOracleSymbol, match="does not support"):
        oracle.assess("INVALID")

    assert provider.calls == 0


def test_bullish_alignment_returns_explainable_long():
    oracle, _ = service_for(source())

    result = oracle.assess("NIFTY")

    assert result.directional_bias == "BULLISH"
    assert result.signal == "LONG"
    assert result.oracle_status == "READY"
    assert "BULLISH_ALIGNMENT" in result.reason_codes
    assert result.confidence is not None


def test_bearish_alignment_returns_explainable_short():
    oracle, _ = service_for(source(bearish_row()))

    result = oracle.assess("NIFTY")

    assert result.directional_bias == "BEARISH"
    assert result.signal == "SHORT"
    assert "BEARISH_ALIGNMENT" in result.reason_codes


def test_neutral_evidence_returns_wait():
    neutral = scanner_row(
        bias="NEUTRAL",
        confidence=50,
        trade="NO",
        regime="SIDEWAYS",
        pullback_signal="WAIT",
        context={
            "indicators": {
                "close": 100,
                "ema_21": 100,
                "ema_38": 100,
                "vwap": 100,
                "rsi_14": 50,
                "adx_14": 10,
                "atr_14": 1,
            },
            "timeframe": {"bias": "NEUTRAL"},
            "liquidity": {"type": "RANGE_LIQUIDITY"},
        },
    )
    oracle, _ = service_for(source(neutral))

    result = oracle.assess("NIFTY")

    assert result.directional_bias == "NEUTRAL"
    assert result.signal == "WAIT"
    assert result.regime == "RANGING"
    assert "NEUTRAL_EVIDENCE_DOMINANT" in result.reason_codes


def test_conflicting_evidence_reduces_confidence():
    aligned, _ = service_for(source())
    conflict_row = scanner_row(
        context={
            "indicators": {
                "close": 101,
                "ema_21": 105,
                "ema_38": 100,
                "vwap": 104,
                "rsi_14": 40,
                "adx_14": 25,
                "atr_14": 3,
            },
            "timeframe": {"bias": "BULLISH"},
            "liquidity": {"type": "BULLISH_SWEEP"},
        }
    )
    conflicting, _ = service_for(source(conflict_row))

    aligned_result = aligned.assess("NIFTY")
    conflict_result = conflicting.assess("NIFTY")

    assert conflict_result.confidence < aligned_result.confidence
    assert "CONFLICTING_DIRECTIONAL_EVIDENCE" in conflict_result.reason_codes


def test_stale_data_blocks_actionable_signal():
    oracle, _ = service_for(source(age=31))

    result = oracle.assess("NIFTY")

    assert result.data_status == "STALE"
    assert result.oracle_status == "BLOCKED"
    assert result.signal == "NO_TRADE"
    assert "STALE_DATA_BLOCK" in result.reason_codes


def test_missing_data_returns_unavailable_without_confidence():
    oracle, _ = service_for(None)

    result = oracle.assess("NIFTY")

    assert result.data_status == "UNAVAILABLE"
    assert result.oracle_status == "UNAVAILABLE"
    assert result.signal == "NO_TRADE"
    assert result.confidence is None
    assert result.reason_codes


def test_malformed_features_fail_safely():
    malformed = scanner_row(
        ltp="not-a-number",
        context={"indicators": {"close": "bad"}},
    )
    oracle, _ = service_for(source(malformed))

    result = oracle.assess("NIFTY")

    assert result.data_status == "UNAVAILABLE"
    assert result.signal == "NO_TRADE"
    assert result.confidence is None


def test_process_local_fallback_is_labeled_cached_and_non_actionable():
    clock = MutableClock()
    oracle, provider = service_for(source(), clock=clock)
    live = oracle.assess("NIFTY")
    provider.value = None
    clock.value = NOW + timedelta(seconds=15)

    cached = oracle.assess("NIFTY")

    assert live.data_status == "LIVE"
    assert cached.data_status == "CACHED"
    assert cached.signal == "WAIT"
    assert cached.source_metadata.fallback_used is True
    assert "FALLBACK_LAST_ASSESSMENT" in cached.reason_codes


@pytest.mark.parametrize("scanner_confidence", [-50, 0, 50, 100, 500])
def test_confidence_is_always_bounded(scanner_confidence):
    oracle, _ = service_for(source(scanner_row(confidence=scanner_confidence)))

    confidence = oracle.assess("NIFTY").confidence

    assert confidence is not None
    assert 0 <= confidence <= 100


def test_every_available_assessment_has_reason_codes():
    oracle, _ = service_for(source())

    result = oracle.assess("NIFTY")

    assert result.reason_codes
    assert result.reasoning.startswith("Deterministic evidence:")


def test_dhan_history_failure_is_preserved_through_oracle_projection():
    row = scanner_row(
        technical_readiness={
            "status": "NOT_READY",
            "reason": "DHAN_HISTORY_UNAVAILABLE",
        },
        context={
            "indicators": {
                "close": 110,
                "ema_21": None,
                "ema_38": None,
                "vwap": None,
                "rsi_14": None,
                "adx_14": None,
                "atr_14": None,
            },
            "timeframe": {"bias": "NEUTRAL", "confidence": 0},
            "liquidity": {"type": "RANGE_LIQUIDITY", "score": 50},
        },
    )
    oracle, _ = service_for(source(row))

    result = oracle.assess("NIFTY")

    assert result.reason_codes == ("DHAN_HISTORY_UNAVAILABLE",)
    assert result.oracle_status == "DEGRADED"
    assert result.signal == "NO_TRADE"


def test_oracle_has_no_broker_or_paper_dependency(tmp_path):
    paper = PaperStateService(tmp_path / "paper.json", now_provider=lambda: NOW)
    paper.initialize()
    before = paper.path.read_bytes()
    oracle, _ = service_for(source())

    oracle.assess("NIFTY")

    assert paper.path.read_bytes() == before
    module_source = importlib.import_module(
        "src.oracle.oracle_service"
    ).__file__
    text = open(module_source, encoding="utf-8").read()
    assert "DhanClient" not in text
    assert "PaperStateService" not in text
    assert "place_order" not in text


def test_api_output_does_not_expose_secret_source_fields():
    row = scanner_row(secret="must-not-appear", access_token="must-not-appear")
    oracle, _ = service_for(source(row))

    serialized = json.dumps(oracle.assess("NIFTY").to_dict()).lower()

    assert "must-not-appear" not in serialized
    assert "access_token" not in serialized


def test_oracle_routes_are_get_only_and_unsupported_is_404(monkeypatch):
    oracle, _ = service_for(source())
    main = importlib.import_module("app.main")
    original = main.oracle_service
    main.oracle_service = oracle
    try:
        assert main.oracle_status()["status"] == "READY"
        assert main.oracle_assessment("NIFTY")["signal"] == "LONG"
        assert main.oracle_reasoning()["maturity_label"] == oracle.MATURITY_LABEL
        with pytest.raises(Exception) as captured:
            main.oracle_assessment("INVALID")
        assert getattr(captured.value, "status_code", None) == 404
        methods = {
            route.path: route.methods
            for route in main.app.routes
            if route.path.startswith("/v1/oracle/")
        }
        assert methods["/v1/oracle/status"] == {"GET"}
        assert methods["/v1/oracle/assessment/{symbol}"] == {"GET"}
        assert methods["/v1/oracle/reasoning"] == {"GET"}
    finally:
        main.oracle_service = original
