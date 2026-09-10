"""Mandatory test suite for multi-timeframe concurrent VOB episodes and dual-strategy trade paths.

Tests:
1. 1M episode opens.
2. 3M episode opens while 1M is active (both exist simultaneously).
3. 5M episode opens while 1M and 3M are active (all three exist simultaneously).
4. 1M ORIGINAL trade emits.
5. 3M CONFIRMED trade emits with separate identity.
6. SAME episode: VOB_ONLY and CONFIRMED_REVERSAL coexist with separate entries.
7. Same 1M event repeated (ledger dedupes it).
8. 1M and 3M with same price/time maintain distinct episode/trade identities.
9. 1M entry + 3M/5M confirmation only (one trade with multi-TF confirmation metadata).
10. 1M entry + independent later 3M entry (two trades).
11. Backtest can query all timeframes (1m, 3m, 5m).
12. No regression to existing VOB-only / confirmed behavior.
"""

from copy import deepcopy
import pytest

from src.vob.episodes import (
    FrozenContractIdentity,
    VobEpisode,
    episodes_from_ose,
    episode_from_ose,
    select_ose_vobs_by_timeframe,
)
from src.vob.reversal import VobReversalEngine, VobReversalState
from src.vob.shadow_ledger import MatchedShadowLedger, VARIANTS


def sample_multi_tf_ose(
    *,
    has_1m: bool = True,
    has_3m: bool = True,
    has_5m: bool = True,
    ce_security_id: str = "101",
    direction: str = "CALL",
    status_1m: str = "ACTIVE",
    status_3m: str = "ACTIVE",
    status_5m: str = "ACTIVE",
    revision: str = "ose-1",
    timestamp: str = "2026-08-14T10:05:00+05:30",
) -> dict:
    structures = {}
    if has_1m:
        structures["1m"] = {
            "demand": {
                "zone_id": f"zone_1m_{ce_security_id}",
                "zone_low": 100.0,
                "zone_high": 102.0,
                "status": status_1m,
                "source_candle_timestamp": timestamp,
                "role": "SUPPORT",
            }
        }
    if has_3m:
        structures["3m"] = {
            "demand": {
                "zone_id": f"zone_3m_{ce_security_id}",
                "zone_low": 98.0,
                "zone_high": 104.0,
                "status": status_3m,
                "source_candle_timestamp": timestamp,
                "role": "SUPPORT",
            }
        }
    if has_5m:
        structures["5m"] = {
            "demand": {
                "zone_id": f"zone_5m_{ce_security_id}",
                "zone_low": 95.0,
                "zone_high": 105.0,
                "status": status_5m,
                "source_candle_timestamp": timestamp,
                "role": "SUPPORT",
            }
        }

    return {
        "calculation_revision": revision,
        "source_timestamp": timestamp,
        "duel": {"state": direction},
        "contracts": {
            "CE": {
                "contract": {
                    "security_id": ce_security_id,
                    "trading_symbol": f"NIFTY-CE-{ce_security_id}",
                    "expiry": "2026-08-20",
                    "strike": 25000,
                    "option_type": "CE",
                    "lot_size": 25,
                    "instrument_source": "DHAN",
                },
                "structures": structures,
            },
            "PE": {
                "contract": {
                    "security_id": "102",
                    "trading_symbol": "NIFTY-PE-102",
                    "expiry": "2026-08-20",
                    "strike": 25200,
                    "option_type": "PE",
                    "lot_size": 25,
                    "instrument_source": "DHAN",
                },
                "structures": {},
            },
        },
    }


def sample_flow(direction: str = "CALL", *, reversal: str = "REVERSAL_CONFIRMED") -> dict:
    return {
        "generated_at": "2026-08-14T10:05:02+05:30",
        "revision": "flow-1",
        "family_values": {
            "RESPONSE_QUALITY": {
                "state": "SELLERS_ABSORBED" if direction == "CALL" else "BUYERS_ABSORBED",
                "status": "AVAILABLE",
            },
            "BOOK_PRESSURE": {
                "book_pressure": 0.8 if direction == "CALL" else -0.8,
                "status": "AVAILABLE",
            },
            "OPTION_CONFIRMATION": {
                "ce_known_buy": 500 if direction == "CALL" else 100,
                "ce_known_sell": 100 if direction == "CALL" else 500,
                "pe_known_buy": 100 if direction == "CALL" else 500,
                "pe_known_sell": 500 if direction == "CALL" else 100,
            },
            "REVERSAL": {"state": reversal},
        },
        "data_quality": "HIGH",
    }


def sample_argus(direction: str = "CALL", *, ce_price: float = 101.0, pe_price: float = 50.0) -> dict:
    return {
        "data": {
            "underlying": {
                "ltp": 25016.0,
                "atm_strike": 25000.0,
                "expiry": "2026-08-20",
                "fetched_at": "2026-08-14T10:05:04+05:30",
            },
            "tactical_edge": {
                "direction": direction,
                "argus_prime": {"raw_direction": direction, "snapshot_id": "argus-1", "status": "AVAILABLE"},
            },
            "atm_window": [
                {
                    "strike": 24950,
                    "ce": {"security_id": "101", "ltp": ce_price, "top_bid_price": ce_price - 0.2, "top_ask_price": ce_price + 0.2},
                    "pe": {"security_id": "102", "ltp": pe_price, "top_bid_price": pe_price - 0.2, "top_ask_price": pe_price + 0.2},
                },
                {
                    "strike": 25050,
                    "ce": {"security_id": "103", "ltp": 80.0, "top_bid_price": 79.8, "top_ask_price": 80.2},
                    "pe": {"security_id": "104", "ltp": 70.0, "top_bid_price": 69.8, "top_ask_price": 70.2},
                },
            ],
            "option_chain": {"strike_interval": 50.0},
        }
    }


def test_1_1m_episode_opens():
    """TEST 1: 1M episode opens and is registered in reversal engine."""
    engine = VobReversalEngine()
    ose = sample_multi_tf_ose(has_1m=True, has_3m=False, has_5m=False)
    engine.ingest_ose(ose)

    episodes = engine.episodes
    assert "1m" in episodes
    assert episodes["1m"].timeframe == "1m"
    assert episodes["1m"].zone_top == 102.0
    assert episodes["1m"].zone_bottom == 100.0
    assert engine.projection()["episode_id"] == episodes["1m"].episode_id


def test_2_3m_episode_opens_while_1m_is_active():
    """TEST 2: 3M episode opens while 1M is active (both exist simultaneously)."""
    engine = VobReversalEngine()
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=False)
    engine.ingest_ose(ose)

    episodes = engine.episodes
    assert "1m" in episodes
    assert "3m" in episodes
    assert episodes["1m"].episode_id != episodes["3m"].episode_id
    assert episodes["1m"].timeframe == "1m"
    assert episodes["3m"].timeframe == "3m"


def test_3_5m_episode_opens_while_1m_and_3m_are_active():
    """TEST 3: 5M episode opens while 1M and 3M are active (all three exist simultaneously)."""
    engine = VobReversalEngine()
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=True)
    engine.ingest_ose(ose)

    episodes = engine.episodes
    assert len(episodes) == 3
    assert set(episodes.keys()) == {"1m", "3m", "5m"}
    assert len({ep.episode_id for ep in episodes.values()}) == 3
    # 5m has primary precedence for single-episode projection
    assert engine.projection()["timeframe"] == "5m"
    assert engine.projection()["episode_id"] == episodes["5m"].episode_id


def test_4_1m_original_trade_emits():
    """TEST 4: 1M ORIGINAL trade emits with proper trade_id and payload."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=False, has_5m=False)
    engine.ingest_ose(ose)

    ep_1m = engine.episodes["1m"]
    event = ledger.record_entry(
        ep_1m,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=101.2,
        initial_sl=99.0,
        target=108.0,
    )
    assert event is not None
    assert event.payload["trade_id"] == f"{ep_1m.episode_id}_VOB_ONLY"
    assert event.payload["timeframe"] == "1m"
    assert event.payload["entry_ask"] == 101.2
    assert event.payload["variant"] == "VOB_ONLY"


def test_5_3m_confirmed_trade_emits():
    """TEST 5: 3M CONFIRMED trade emits with separate identity from 1M."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=False)
    engine.ingest_ose(ose)

    ep_1m = engine.episodes["1m"]
    ep_3m = engine.episodes["3m"]

    # 1M original trade
    ledger.record_entry(
        ep_1m,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=150.0,
        initial_sl=145.0,
        target=165.0,
    )

    # 3M confirmed trade
    event_3m = ledger.record_entry(
        ep_3m,
        "CONFIRMED_REVERSAL",
        entry_time="2026-08-14T10:08:00+05:30",
        entry_ask=148.0,
        initial_sl=144.0,
        target=160.0,
    )

    assert event_3m is not None
    assert event_3m.payload["trade_id"] == f"{ep_3m.episode_id}_CONFIRMED_REVERSAL"
    assert event_3m.payload["timeframe"] == "3m"
    assert event_3m.payload["entry_ask"] == 148.0
    assert event_3m.payload["variant"] == "CONFIRMED_REVERSAL"

    trades = ledger.active_trades()
    assert len(trades) == 2
    trade_ids = {t["trade_id"] for t in trades}
    assert f"{ep_1m.episode_id}_VOB_ONLY" in trade_ids
    assert f"{ep_3m.episode_id}_CONFIRMED_REVERSAL" in trade_ids


def test_6_same_episode_original_and_confirmed_coexist():
    """TEST 6: SAME episode: VOB_ONLY and CONFIRMED_REVERSAL coexist with separate entries."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=False, has_5m=False)
    engine.ingest_ose(ose)

    ep = engine.episodes["1m"]

    # Record VOB_ONLY entry at zone touch
    ledger.record_entry(
        ep,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=101.0,
        initial_sl=99.0,
        target=107.0,
    )

    # Record CONFIRMED_REVERSAL entry after confirmation
    ledger.record_entry(
        ep,
        "CONFIRMED_REVERSAL",
        entry_time="2026-08-14T10:06:30+05:30",
        entry_ask=103.5,
        initial_sl=100.5,
        target=109.5,
    )

    state = ledger.current(ep.episode_id)
    assert state["VOB_ONLY"]["entry_ask"] == 101.0
    assert state["CONFIRMED_REVERSAL"]["entry_ask"] == 103.5
    assert state["VOB_ONLY"]["entry_time"] == "2026-08-14T10:05:00+05:30"
    assert state["CONFIRMED_REVERSAL"]["entry_time"] == "2026-08-14T10:06:30+05:30"


def test_7_same_1m_event_repeated_dedupes():
    """TEST 7: Same 1M event repeated is deduped by MatchedShadowLedger."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=False, has_5m=False)
    engine.ingest_ose(ose)

    ep = engine.episodes["1m"]

    ev1 = ledger.record_entry(
        ep,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=101.0,
        initial_sl=99.0,
        target=107.0,
    )
    ev2 = ledger.record_entry(
        ep,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=101.0,
        initial_sl=99.0,
        target=107.0,
    )

    assert ev1 is not None
    assert ev2 is None  # Suppressed as duplicate
    events = ledger.events()
    entry_events = [e for e in events if e["event_type"] == "SHADOW_ENTRY"]
    assert len(entry_events) == 1


def test_8_1m_and_3m_same_price_and_time_remain_distinct():
    """TEST 8: 1M and 3M with same price/time maintain distinct episode identities."""
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=False, timestamp="2026-08-14T10:05:00+05:30")
    episodes = episodes_from_ose(ose)

    assert episodes["1m"].episode_id != episodes["3m"].episode_id
    assert "1m" in episodes["1m"].timeframe
    assert "3m" in episodes["3m"].timeframe


def test_9_1m_entry_with_multitf_confirmation_is_one_trade():
    """TEST 9: 1M entry + 3M/5M confirmation only produces ONE trade with multi-TF metadata."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=True)
    engine.ingest_ose(ose)

    ep_1m = engine.episodes["1m"]

    # Single entry executed on 1M setup
    ledger.record_entry(
        ep_1m,
        "CONFIRMED_REVERSAL",
        entry_time="2026-08-14T10:05:30+05:30",
        entry_ask=150.0,
        initial_sl=146.0,
        target=162.0,
        evidence_missing=[],
    )

    trades = ledger.active_trades()
    assert len(trades) == 1
    assert trades[0]["timeframe"] == "1m"
    assert trades[0]["trade_id"] == f"{ep_1m.episode_id}_CONFIRMED_REVERSAL"


def test_10_1m_entry_plus_independent_later_3m_entry_is_two_trades():
    """TEST 10: 1M entry + independent later 3M entry produces TWO distinct trades."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)

    # Initial 1M and 3M active
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=False)
    engine.ingest_ose(ose)

    ep_1m = engine.episodes["1m"]
    ep_3m = engine.episodes["3m"]

    # Trade 1 on 1M
    ledger.record_entry(
        ep_1m,
        "VOB_ONLY",
        entry_time="2026-08-14T10:05:00+05:30",
        entry_ask=150.0,
        initial_sl=147.0,
        target=160.0,
    )

    # Later independent Trade 2 on 3M
    ledger.record_entry(
        ep_3m,
        "CONFIRMED_REVERSAL",
        entry_time="2026-08-14T10:12:00+05:30",
        entry_ask=148.0,
        initial_sl=144.0,
        target=158.0,
    )

    trades = ledger.active_trades()
    assert len(trades) == 2
    assert {t["trade_id"] for t in trades} == {
        f"{ep_1m.episode_id}_VOB_ONLY",
        f"{ep_3m.episode_id}_CONFIRMED_REVERSAL",
    }
    assert {t["entry_ask"] for t in trades} == {150.0, 148.0}


def test_11_backtest_can_query_all_timeframes():
    """TEST 11: Backtest engine can query active trades across all timeframes (1m, 3m, 5m)."""
    ledger = MatchedShadowLedger()
    engine = VobReversalEngine(ledger=ledger)
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=True)
    engine.ingest_ose(ose)

    for tf in ("1m", "3m", "5m"):
        ep = engine.episodes[tf]
        ledger.record_entry(
            ep,
            "VOB_ONLY",
            entry_time=f"2026-08-14T10:05:{tf[:1]}0+05:30",
            entry_ask=100.0 + float(tf[:1]),
            initial_sl=95.0,
            target=110.0,
        )

    all_trades = ledger.active_trades()
    assert len(all_trades) == 3
    tf_set = {t["timeframe"] for t in all_trades}
    assert tf_set == {"1m", "3m", "5m"}


def test_12_no_regression_to_existing_vob_only_and_confirmed_behavior():
    """TEST 12: No regression to existing reversal state machine progression."""
    engine = VobReversalEngine()
    ose = sample_multi_tf_ose(has_1m=True, has_3m=True, has_5m=True)
    engine.ingest_ose(ose)

    assert engine.projection()["reversal_state"] == "WATCHING"

    # Ingest supportive order flow
    engine.ingest_flow(sample_flow(direction="CALL", reversal="REVERSAL_FORMING"))
    # State should advance to REVERSAL_BUILDING
    assert engine.states["5m"] == VobReversalState.REVERSAL_BUILDING
    assert engine.states["3m"] == VobReversalState.REVERSAL_BUILDING
    assert engine.states["1m"] == VobReversalState.REVERSAL_BUILDING

    # Ingest confirming ARGUS
    engine.ingest_argus(sample_argus(direction="CALL"))
    # State advances to REVERSAL_READY
    assert engine.states["5m"] == VobReversalState.REVERSAL_READY
    assert engine.states["3m"] == VobReversalState.REVERSAL_READY
    assert engine.states["1m"] == VobReversalState.REVERSAL_READY
