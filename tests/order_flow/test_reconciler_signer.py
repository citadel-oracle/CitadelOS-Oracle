import pytest

from src.order_flow.contracts import AggressorSide, DataQuality
from src.order_flow.reconciler import VolumeReconciler
from src.order_flow.signer import AggressorSigner

from .helpers import event


def test_signer_ask_hit_and_bid_hit():
    signer = AggressorSigner()
    assert signer.sign(trade_price=100, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=None).side is AggressorSide.BUY
    assert signer.sign(trade_price=99.95, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=None).side is AggressorSide.SELL


def test_signer_inside_spread_tick_fallback():
    signer = AggressorSigner()
    up = signer.sign(trade_price=99.98, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=99.97)
    down = signer.sign(trade_price=99.96, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=99.97)
    assert (up.side, up.method, up.confidence) == (AggressorSide.BUY, "LAST_DISTINCT_TICK_UP", 0.65)
    assert down.side is AggressorSide.SELL


def test_signer_unknown_when_ambiguous_or_stale():
    signer = AggressorSigner()
    assert signer.sign(trade_price=99.98, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=None).side is AggressorSide.UNKNOWN
    stale = signer.sign(trade_price=100, pre_bid=99.95, pre_ask=100, last_distinct_trade_price=None, quote_fresh=False)
    assert stale.side is AggressorSide.UNKNOWN
    assert stale.method == "STALE_OR_INVALID_PRE_EVENT_QUOTE"


def test_first_packet_is_baseline_not_trade():
    row = VolumeReconciler().reconcile(event())
    assert row.delta_volume == 0
    assert row.reconciliation_status == "BASELINE_ESTABLISHED"


def test_repeated_ltq_with_zero_delta_not_counted_again():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000, ltq=20))
    row = reconciler.reconcile(event(event_id="b", volume=1000, ltq=20, ltt=1786083901))
    assert row.delta_volume == row.classified_buy_qty == row.classified_sell_qty == row.unclassified_qty == 0


def test_clean_single_trade_ask_hit():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000, ask=100.0))
    row = reconciler.reconcile(event(event_id="b", volume=1010, ltq=10, ltt=1786083901, ltp=100.0))
    assert row.classified_buy_qty == 10
    assert row.unclassified_qty == 0
    assert row.signer_method == "PRE_EVENT_ASK_TEST"


def test_clean_single_trade_bid_hit():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000, bid=99.95))
    row = reconciler.reconcile(event(event_id="b", volume=1010, ltq=10, ltt=1786083901, ltp=99.95))
    assert row.classified_sell_qty == 10
    assert row.unclassified_qty == 0


def test_cumulative_jump_larger_than_ltq_retains_unknown_residual():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000))
    row = reconciler.reconcile(event(event_id="b", volume=1100, ltq=25, ltt=1786083901, ltp=100))
    assert row.classified_buy_qty == 25
    assert row.unclassified_qty == 75
    assert row.reconciliation_status == "UNCLASSIFIED_AGGREGATE"


def test_cumulative_jump_without_ltt_advance_is_all_unknown():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000))
    row = reconciler.reconcile(event(event_id="b", volume=1030, ltq=10, ltt=1786083900))
    assert row.unclassified_qty == 30
    assert row.observed_trade_qty == 0


def test_negative_volume_rebaselines_never_becomes_sell():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000))
    row = reconciler.reconcile(event(event_id="b", volume=10, ltt=1786083901))
    assert row.delta_volume == 0
    assert row.classified_sell_qty == 0
    assert row.reconciliation_status == "SESSION_RESET_OR_VOLUME_REGRESSION"
    assert row.data_quality is DataQuality.DEGRADED


def test_new_generation_requires_new_baseline():
    reconciler = VolumeReconciler()
    reconciler.reconcile(event(event_id="a", volume=1000, generation=1))
    row = reconciler.reconcile(event(event_id="b", volume=1100, generation=2))
    assert row.reconciliation_status == "BASELINE_ESTABLISHED"
    assert row.delta_volume == 0


def test_invariant_property_over_many_deltas():
    for delta in range(1, 200):
        reconciler = VolumeReconciler()
        reconciler.reconcile(event(event_id="base", volume=10_000))
        ltq = min(delta, (delta * 17) % 53 + 1)
        row = reconciler.reconcile(
            event(event_id=f"next-{delta}", volume=10_000 + delta, ltq=ltq, ltt=1786083901)
        )
        assert row.classified_buy_qty + row.classified_sell_qty + row.unclassified_qty == row.delta_volume


def test_contract_rejects_invariant_break():
    from src.order_flow.contracts import ReconciledTradeState
    with pytest.raises(ValueError, match="FLOW_DATA_DEGRADED"):
        ReconciledTradeState("x", 10, 6, 0, 3, "x", 0.5, "x", AggressorSide.BUY, 1.0, 6, DataQuality.GOOD)
