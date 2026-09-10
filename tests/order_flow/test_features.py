import pytest

from src.order_flow.contracts import AggressorSide, DataQuality, ReconciledTradeState
from src.order_flow.features import (
    BookPressureEngine,
    OptionConfirmationEngine,
    ResponseQualityEngine,
    SessionProfileEngine,
)

from .helpers import event


def trade(event_id="x", *, buy=0, sell=0, unknown=0, price=100.0, confidence=0.95):
    delta = buy + sell + unknown
    side = AggressorSide.BUY if buy else AggressorSide.SELL if sell else AggressorSide.UNKNOWN
    return ReconciledTradeState(
        event_id, delta, buy, sell, unknown, "TEST", confidence,
        "RECONCILED" if not unknown else "UNCLASSIFIED_AGGREGATE",
        side, price if buy or sell else None, buy + sell, DataQuality.GOOD,
    )


def test_book_ofi_and_microprice():
    engine = BookPressureEngine()
    engine.update(event(event_id="a", bid_qty=500, ask_qty=500), trade())
    metrics = engine.update(event(event_id="b", bid_qty=800, ask_qty=300), trade(buy=20))
    assert metrics.l1_ofi > 0
    assert metrics.microprice is not None
    assert metrics.microprice_edge > 0
    assert metrics.book_pressure > 0


def test_mlofi_matches_actual_prices_after_level_movement():
    engine = BookPressureEngine()
    engine.update(event(event_id="a", bid=99.95, ask=100.00), trade())
    moved = engine.update(event(event_id="b", bid=100.00, ask=100.05, bid_qty=700, ask_qty=350), trade(buy=10, price=100.05))
    assert -1 <= moved.mlofi <= 1
    assert moved.mlofi != 0


def test_depletion_and_refill_at_unchanged_levels():
    engine = BookPressureEngine()
    engine.update(event(event_id="a", bid_qty=500, ask_qty=500), trade())
    row = engine.update(event(event_id="b", bid_qty=450, ask_qty=650), trade())
    assert row.bid_depletion > 0
    assert row.ask_refill > 0


def test_crossed_book_fails_closed():
    engine = BookPressureEngine()
    row = engine.update(event(event_id="x", bid=100.0, ask=99.95), trade())
    assert row.status == "INVALID_OR_CROSSED_BOOK"
    assert row.book_confidence == 0


def test_response_clean_bullish():
    book_engine = BookPressureEngine()
    response = ResponseQualityEngine(window=8)
    state = None
    for index in range(5):
        row = event(event_id=str(index), ltp=100 + index * 0.1, bid=99.95 + index * 0.1, ask=100 + index * 0.1)
        signed = trade(str(index), buy=30, price=row.ltp)
        book = book_engine.update(row, signed)
        state = response.update(row, signed, book)
    assert state is not None
    assert state.response_quality > 0
    assert state.state in {"CLEAN_BULL", "MIXED"}


def test_buyer_absorption_detected_when_price_stalls_and_ask_refills():
    book_engine = BookPressureEngine()
    response = ResponseQualityEngine(window=8)
    state = None
    for index in range(6):
        row = event(event_id=str(index), ltp=100, ask_qty=300 + index * 200)
        signed = trade(str(index), buy=100, price=100)
        book = book_engine.update(row, signed)
        state = response.update(row, signed, book)
    assert state is not None
    assert state.buyer_absorption > 0
    assert state.state == "BUYERS_ABSORBED"


def test_seller_absorption_is_mirror_case():
    book_engine = BookPressureEngine()
    response = ResponseQualityEngine(window=8)
    state = None
    for index in range(6):
        row = event(event_id=str(index), ltp=100, bid_qty=300 + index * 200)
        signed = trade(str(index), sell=100, price=100)
        book = book_engine.update(row, signed)
        state = response.update(row, signed, book)
    assert state is not None
    assert state.seller_absorption > 0
    assert state.state == "SELLERS_ABSORBED"


def test_option_confirmation_ce_pe_symmetry_without_greeks():
    ce_engine = OptionConfirmationEngine(ttl_seconds=3)
    ce = event(event_id="ce", security_id="1", role="ATM_CE", option_type="CE", receive_ns=1_000_000_000)
    book = BookPressureEngine().update(ce, trade("ce", buy=100))
    ce_result = ce_engine.update(ce, trade("ce", buy=100), book, now_ns=1_100_000_000)
    pe_engine = OptionConfirmationEngine(ttl_seconds=3)
    pe = event(event_id="pe", security_id="2", role="ATM_PE", option_type="PE", receive_ns=1_000_000_000)
    pe_book = BookPressureEngine().update(pe, trade("pe", buy=100))
    pe_result = pe_engine.update(pe, trade("pe", buy=100), pe_book, now_ns=1_100_000_000)
    assert ce_result.value == pytest.approx(-pe_result.value)
    assert ce_result.greeks_mode == pe_result.greeks_mode == "RAW_QUOTE_AWARE"


def test_option_confirmation_stale_and_missing_greeks_are_truthful():
    engine = OptionConfirmationEngine(ttl_seconds=1)
    ce = event(event_id="ce", security_id="1", role="ATM_CE", option_type="CE", receive_ns=1_000_000_000)
    book = BookPressureEngine().update(ce, trade("ce", buy=10))
    engine.update(ce, trade("ce", buy=10), book, now_ns=1_000_000_000)
    result = engine.snapshot(2_100_000_000)
    assert result.status == "STALE_OPTIONS"
    assert result.confidence == 0


def test_fresh_canonical_greek_enables_delta_equivalent_mode():
    engine = OptionConfirmationEngine(ttl_seconds=3)
    ce = event(event_id="ce", security_id="1", role="ATM_CE", option_type="CE", receive_ns=1_000_000_000)
    engine.register_delta("1", 0.55, receive_ns=1_000_000_000)
    book = BookPressureEngine().update(ce, trade("ce", buy=100))
    result = engine.update(ce, trade("ce", buy=100), book, now_ns=1_100_000_000)
    assert result.greeks_mode == "DELTA_EQUIVALENT"
    assert result.value == pytest.approx(0.55)


def test_wide_spread_reduces_option_confirmation_confidence():
    engine = OptionConfirmationEngine(ttl_seconds=3)
    ce = event(event_id="ce", security_id="1", role="ATM_CE", option_type="CE", ltp=10, bid=9, ask=10, receive_ns=1_000_000_000)
    book = BookPressureEngine().update(ce, trade("ce", buy=100))
    result = engine.update(ce, trade("ce", buy=100), book, now_ns=1_100_000_000)
    assert result.status == "WIDE_SPREAD_DEGRADED"
    assert result.confidence < 0.25


def test_nearby_strike_disagreement_reduces_confirmation():
    engine = OptionConfirmationEngine(ttl_seconds=3)
    ce_atm = event(event_id="a", security_id="1", role="ATM_CE", option_type="CE", receive_ns=1_000_000_000)
    ce_near = event(event_id="b", security_id="2", role="ATM+1_CE", option_type="CE", receive_ns=1_000_000_000)
    book_engine = BookPressureEngine()
    first = book_engine.update(ce_atm, trade("a", buy=100))
    engine.update(ce_atm, trade("a", buy=100), first, now_ns=1_100_000_000)
    second = book_engine.update(ce_near, trade("b", sell=100))
    result = engine.update(ce_near, trade("b", sell=100), second, now_ns=1_100_000_000)
    assert result.nearby_agreement == 0
    assert result.value == 0


def test_low_signer_confidence_lowers_option_confidence():
    engine = OptionConfirmationEngine(ttl_seconds=3)
    ce = event(event_id="ce", security_id="1", role="ATM_CE", option_type="CE", receive_ns=1_000_000_000)
    book = BookPressureEngine().update(ce, trade("ce", buy=100, confidence=0.1))
    result = engine.update(ce, trade("ce", buy=100, confidence=0.1), book, now_ns=1_100_000_000)
    assert result.confidence <= 0.1


def test_profile_poc_value_area_and_location():
    engine = SessionProfileEngine(value_area_fraction=0.70, minimum_profile_coverage=0.6)
    values = [(100.0, 100), (100.05, 300), (100.10, 100)]
    result = None
    for index, (price, qty) in enumerate(values):
        result = engine.update(event(event_id=str(index), ltp=price), trade(str(index), buy=qty, price=price))
    assert result is not None
    assert result.status == "AVAILABLE"
    assert result.poc == 100.05
    assert result.val <= result.poc <= result.vah


def test_unknown_residual_never_enters_profile_or_cvd():
    engine = SessionProfileEngine(minimum_profile_coverage=0.8)
    result = engine.update(event(event_id="x"), trade("x", buy=10, unknown=90, price=100))
    assert result.coverage == pytest.approx(0.1)
    assert result.status == "PROFILE_DEGRADED"
    assert result.cvd == 10
    assert sum(engine.profile.values()) == 10


def test_known_only_cvd_and_coverage():
    engine = SessionProfileEngine(minimum_profile_coverage=0.1)
    first = engine.update(event(event_id="a"), trade("a", buy=30, sell=10, unknown=60, price=100))
    assert first.cvd == 20
    assert first.cvd_coverage == pytest.approx(0.4)


def test_cvd_price_non_response_is_explicit():
    engine = SessionProfileEngine(minimum_profile_coverage=0.1)
    result = engine.update(event(event_id="a", ltp=100), trade("a", buy=50, price=100))
    assert result.divergence_state == "PRICE_NOT_RESPONDING"


def test_diagonal_stacked_imbalance_needs_volume_and_consecutive_levels():
    engine = SessionProfileEngine(minimum_profile_coverage=0.1, imbalance_ratio=3, minimum_level_volume=10)
    result = None
    for index, price in enumerate((100.0, 100.05, 100.10, 100.15)):
        result = engine.update(event(event_id=str(index), ltp=price), trade(str(index), buy=100, sell=1, price=price))
    assert result is not None
    assert result.stacked_levels >= 2
    assert "STACKED" in result.footprint_state
    assert result.imbalance_ratio_max >= 3
    assert result.imbalance_quality > 0


def test_stacked_imbalance_labels_absorption_separately():
    engine = SessionProfileEngine(minimum_profile_coverage=0.1, imbalance_ratio=3, minimum_level_volume=10)
    result = None
    for index, price in enumerate((100.0, 100.05, 100.10)):
        result = engine.update(
            event(event_id=str(index), ltp=price),
            trade(str(index), buy=100, sell=1, price=price),
            response_state="BUYERS_ABSORBED",
        )
    assert "ABSORBED" in result.footprint_state


def test_location_requires_persistence():
    engine = SessionProfileEngine(minimum_profile_coverage=0.1)
    engine.update(event(event_id="a", ltp=100), trade("a", buy=100, price=100))
    first = engine.update(event(event_id="b", ltp=101), trade("b", buy=100, price=100))
    second = engine.update(event(event_id="c", ltp=101), trade("c", buy=100, price=100))
    assert first.location_state.endswith("_PENDING")
    assert second.location_state == "VAH_ACCEPTED"


def test_value_area_rejection_and_reclaim_are_persistent_transitions():
    upper = SessionProfileEngine(minimum_profile_coverage=0.1)
    upper.update(event(event_id="a", ltp=100), trade("a", buy=100, price=100))
    upper.update(event(event_id="b", ltp=101), trade("b", buy=10, price=100))
    assert upper.update(event(event_id="c", ltp=101), trade("c", buy=10, price=100)).location_state == "VAH_ACCEPTED"
    upper.update(event(event_id="d", ltp=100), trade("d", buy=10, price=100))
    rejected = upper.update(event(event_id="e", ltp=100), trade("e", buy=10, price=100))
    assert rejected.location_state in {"AT_POC", "VAH_REJECTED"}

    lower = SessionProfileEngine(minimum_profile_coverage=0.1)
    lower.update(event(event_id="f", ltp=100), trade("f", sell=100, price=100))
    lower.update(event(event_id="g", ltp=99), trade("g", sell=10, price=100))
    assert lower.update(event(event_id="h", ltp=99), trade("h", sell=10, price=100)).location_state == "VAL_BROKEN"
