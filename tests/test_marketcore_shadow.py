from __future__ import annotations

from dataclasses import replace

from src.marketcore.core import MarketCoreShadow
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.features import BookPressureEngine, ResponseQualityEngine
from src.order_flow.reconciler import VolumeReconciler
from tests.order_flow.helpers import event, full_packet, identity
from tests.order_flow.test_service_replay_gateway import Clock, tick


def test_shadow_decodes_once_and_consumes_the_same_immutable_event(monkeypatch):
    shadow = MarketCoreShadow(clock_ns=Clock())
    shadow.order_flow.register_instruments((identity(),))
    decoded = []
    consumed = []
    original_decode = shadow.order_flow.decode_market_event
    original_ingest = shadow.order_flow.ingest_market_event

    def decode_once(value):
        result = original_decode(value)
        decoded.append(result)
        return result

    def consume_same(result):
        consumed.append(result)
        return original_ingest(result)

    monkeypatch.setattr(shadow.order_flow, "decode_market_event", decode_once)
    monkeypatch.setattr(shadow.order_flow, "ingest_market_event", consume_same)

    result = shadow.process_tick(tick(full_packet(), receive_ns=1_000_000_000))

    assert len(decoded) == 1
    assert consumed == decoded
    assert result is decoded[0]
    assert shadow.market_events[-1] is result
    assert shadow.events_consumed == 1


def test_book_and_response_state_restart_for_new_feed_generation():
    reconciler = VolumeReconciler()
    book = BookPressureEngine()
    response = ResponseQualityEngine()
    first = event(event_id="generation-1", generation=1)
    first_trade = reconciler.reconcile(first)
    first_book = book.update(first, first_trade)
    response.update(first, first_trade, first_book)

    rotated = event(
        event_id="generation-2",
        generation=2,
        ltp=110.0,
        bid=109.95,
        ask=110.0,
        bid_qty=900,
        ask_qty=100,
    )
    rotated_trade = reconciler.reconcile(rotated)
    rotated_book = book.update(rotated, rotated_trade)
    rotated_response = response.update(rotated, rotated_trade, rotated_book)

    assert rotated_trade.reconciliation_status == "BASELINE_ESTABLISHED"
    assert rotated_book.status == "BASELINE"
    assert rotated_response.state == "MIXED"
    assert rotated_response.confidence == 0.2


def test_new_session_and_new_contract_do_not_reuse_prior_accumulators():
    reconciler = VolumeReconciler()
    book = BookPressureEngine()
    old = event(event_id="old", security_id="101", role="ATM_CE", option_type="CE")
    old_trade = reconciler.reconcile(old)
    book.update(old, old_trade)

    new_contract = event(event_id="new-contract", security_id="202", role="ATM_CE", option_type="CE")
    new_trade = reconciler.reconcile(new_contract)
    new_book = book.update(new_contract, new_trade)
    assert new_trade.reconciliation_status == "BASELINE_ESTABLISHED"
    assert new_book.status == "BASELINE"

    new_session = replace(old, session_id="2026-08-08", event_id="new-session")
    session_trade = reconciler.reconcile(new_session)
    session_book = book.update(new_session, session_trade)
    assert session_trade.reconciliation_status == "BASELINE_ESTABLISHED"
    assert session_book.status == "BASELINE"


def test_non_nifty_event_cannot_change_nifty_session_cvd():
    shadow = MarketCoreShadow(clock_ns=Clock())
    shadow.order_flow.register_instruments(
        (
            identity(),
            InstrumentIdentity("NSE_EQ", "999", "BANKNIFTY_SPOT"),
        )
    )
    shadow.process_tick(tick(full_packet(), receive_ns=1_000_000_000))
    cvd_before = shadow.order_flow.profile.cvd

    bank = tick(full_packet(security_id=999, volume=2000), receive_ns=1_100_000_000)
    bank["exchange_segment"] = "NSE_EQ"
    shadow.process_tick(bank)

    assert shadow.order_flow.profile.cvd == cvd_before


def test_recorded_payload_uses_canonical_replay_decoder_once(monkeypatch):
    source = MarketCoreShadow(clock_ns=Clock())
    source.order_flow.register_instruments((identity(),))
    original = source.order_flow.decode_market_event(tick(full_packet()))
    from dataclasses import asdict

    payload = asdict(original)
    payload.update({
        "feed_receive_monotonic_ns": payload.pop("feed_receive_ns"),
        "decode_done_monotonic_ns": payload.pop("decode_done_ns"),
        "ltt_normalized_epoch": payload.pop("exchange_ltt"),
        "open_interest": payload.pop("oi"),
        "high_open_interest": payload.pop("high_oi"),
        "low_open_interest": payload.pop("low_oi"),
        "total_buy_quantity": payload.pop("total_buy_qty"),
        "total_sell_quantity": payload.pop("total_sell_qty"),
    })
    decoded = []
    original_decode = source.order_flow.decode_recorded_market_event

    def decode_once(value):
        event_value = original_decode(value)
        decoded.append(event_value)
        return event_value

    monkeypatch.setattr(source.order_flow, "decode_recorded_market_event", decode_once)
    result = source.process_recorded_payload(payload)
    assert decoded == [result]
    assert source.market_events[-1] is result
    assert result.ltp == payload["ltp"]
    assert result.oi == payload["open_interest"]
