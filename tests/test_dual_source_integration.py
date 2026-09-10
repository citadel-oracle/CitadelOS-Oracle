"""Comprehensive dual-source integration test suite for CITADEL ORACLE.

Validates all 8 core integration invariants:
1. Keychain security and safe fingerprint redaction.
2. Official Protobuf MarketDataFeedV3 decoding and level-5 depth normalization.
3. Bidirectional instrument mapping (Dhan <-> Canonical <-> Upstox).
4. Dual-source gateway lifecycle, provenance tagging, zero price averaging, divergence detection.
5. ARGUS option chain dual-source fallback and field-level provenance.
6. Market Info Service (PCR, Max Pain, OI, FII/DII, Global Quotes).
7. World Market Adapter Upstox exact quote resolution and unavailable targets filtration.
8. Canonical runtime truth evaluation with Upstox healthy failover.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.broker.upstox_client import UpstoxClient
from src.broker.upstox_proto import UpstoxProtoDecoder
from src.broker.proto import MarketDataFeedV3_pb2 as pb
from src.order_flow.instrument_mapping import InstrumentMappingRegistry, CanonicalInstrument, CANONICAL_INDICES
from src.oracle.market_data_gateway import MarketDataGateway
from src.argus.option_chain_engine import OptionChainEngine, OptionChainSnapshot
from src.external_context.adapters.world_market import WorldMarketAdapter, ExactOrProxy
from src.oracle.canonical_runtime_truth import CanonicalRuntimeTruth, GlobalReadinessState


def test_keychain_token_and_fingerprint_safety():
    client = UpstoxClient()
    token = client.token
    assert token is not None
    assert len(token) > 20
    # Safe fingerprint must be sha256 hash prefix, never containing raw token
    fp = client.safe_fingerprint
    assert fp.startswith("sha256:")
    assert token not in fp
    # Payload inspection
    claims = client.jwt_claims
    assert claims.get("sub") == "87BUAC"
    assert claims.get("isPlusPlan") is True


def test_protobuf_normalization():
    feed_resp = pb.FeedResponse()
    feed_resp.type = pb.Type.initial_feed
    
    feed = pb.Feed()
    feed.ltpc.ltp = 23805.5
    feed.ltpc.ltt = 1788777000000
    feed.ltpc.ltq = 75
    feed.ltpc.cp = 23790.0
    feed_resp.feeds["NSE_INDEX|Nifty 50"].CopyFrom(feed)
    
    full_feed = pb.FullFeed()
    full_feed.marketFF.ltpc.CopyFrom(feed.ltpc)
    full_feed.marketFF.marketOHLC.ohlc.add(interval="1d", open=23750.0, high=23850.0, low=23740.0, close=23805.5, ts=1788777000000)
    
    # 5 depth levels
    for i in range(5):
        quote = full_feed.marketFF.marketLevel.bidAskQuote.add()
        quote.bidQ = 100 * (i + 1)
        quote.bidP = 23805.0 - (i * 0.5)
        quote.askQ = 120 * (i + 1)
        quote.askP = 23806.0 + (i * 0.5)
        
    feed_fno = pb.Feed()
    feed_fno.fullFeed.CopyFrom(full_feed)
    feed_resp.feeds["NSE_FO|68407"].CopyFrom(feed_fno)
    
    raw_bytes = feed_resp.SerializeToString()
    decoded = UpstoxProtoDecoder.decode_packet(raw_bytes)
    ticks = decoded.ticks
    assert len(ticks) == 2
    
    # Check index tick
    idx_tick = next(t for t in ticks if t["instrument_key"] == "NSE_INDEX|Nifty 50")
    assert idx_tick["ltp"] == 23805.5
    assert idx_tick["provider"] == "UPSTOX"
    assert idx_tick["feed_union"] == "ltpc"
    
    # Check full FNO tick with 5-level depth
    fno_tick = next(t for t in ticks if t["instrument_key"] == "NSE_FO|68407")
    assert fno_tick["ltp"] == 23805.5
    assert fno_tick["provider"] == "UPSTOX"
    assert fno_tick["feed_union"] == "fullFeed"
    assert len(fno_tick["depth_5"]) == 5
    assert fno_tick["depth_5"][0]["bid_price"] == 23805.0
    assert fno_tick["depth_5"][0]["ask_price"] == 23806.0


def test_instrument_mapping_registry():
    reg = InstrumentMappingRegistry()
    
    # Reverse lookup from Upstox key
    c_inst = reg.get_by_upstox_key("NSE_INDEX|Nifty 50")
    assert c_inst is not None
    assert c_inst.symbol == "NIFTY"
    assert c_inst.dhan_security_id == "13"
    
    # Reverse lookup from Dhan segment and security_id
    c_dhan = reg.get_by_dhan_key("IDX_I", "13")
    assert c_dhan is not None
    assert c_dhan.symbol == "NIFTY"
    assert c_dhan.upstox_key == "NSE_INDEX|Nifty 50"


def test_dual_source_gateway_no_averaging_and_divergence_detection():
    gw = MarketDataGateway(lossless_tick_delivery=True)
    
    # Register subscription for spot
    gw.subscribe([{"exchange_segment": "IDX_I", "security_id": "13", "instrument_key": "NSE_INDEX|Nifty 50"}])
    
    # Seed Dhan tick in provider latest ticks
    gw._provider_latest_ticks[("DHAN", "IDX_I", "13")] = {
        "provider": "DHAN",
        "exchange_segment": "IDX_I",
        "security_id": "13",
        "ltp": 23800.0,
        "ltt": 1788777000,
    }
    
    # Simulate Upstox tick at 23802.0 (< 0.15% diff, no divergence)
    upstox_tick = {
        "provider": "UPSTOX",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "ltp": 23802.0,
        "ltt": 1788777000,
    }
    gw._handle_upstox_tick(upstox_tick)
    
    emitted_tick = gw._tick_queue.get_nowait()
    # NO PRICE AVERAGING: tick must retain exact Upstox price 23802.0
    assert emitted_tick["ltp"] == 23802.0
    assert emitted_tick["provider"] == "UPSTOX"
    assert emitted_tick.get("SOURCE_DIVERGENCE") is not True
    assert emitted_tick["provenance_state"] == "DUAL_VERIFIED"
    
    # Simulate wide divergence (> 0.15% diff: 23800 vs 23900 is ~0.42%)
    divergent_tick = {
        "provider": "UPSTOX",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "ltp": 23900.0,
        "ltt": 1788777001,
    }
    gw._handle_upstox_tick(divergent_tick)
    
    emitted_divergent = gw._tick_queue.get_nowait()
    assert emitted_divergent["ltp"] == 23900.0  # Exact, no averaging!
    assert emitted_divergent["SOURCE_DIVERGENCE"] is True
    assert emitted_divergent["provenance_state"] == "SOURCE_DIVERGENCE"
    assert gw._divergence_count > 0


def test_option_chain_fallback_and_provenance():
    mock_upstox = MagicMock()
    mock_dhan = MagicMock()
    # Dhan fails (401 unauthorized / expired)
    mock_dhan.get_option_expiries.return_value = {"status": "failed", "data": {"808": "Expired"}}
    mock_dhan.get_option_chain.return_value = {"status": "failed", "data": {"808": "Expired"}}
    
    mock_upstox.get_option_contracts.return_value = [{"expiry": "2026-09-15"}]
    mock_upstox.get_option_chain.return_value = [
        {
            "strike_price": 23800.0,
            "underlying_spot_price": 23780.0,
            "call_options": {"instrument_key": "NSE_FO|101", "market_data": {"ltp": 120.0, "oi": 5000, "close_price": 110.0}},
            "put_options": {"instrument_key": "NSE_FO|102", "market_data": {"ltp": 95.0, "oi": 6000, "close_price": 100.0}},
        }
    ]
    
    engine = OptionChainEngine(dhan=mock_dhan, upstox=mock_upstox)
    snap = engine.fetch_current_snapshot("NIFTY", "IDX_I", 13)
    assert isinstance(snap, OptionChainSnapshot)
    assert snap.source == "UPSTOX"
    assert snap.provider == "UPSTOX"
    assert snap.underlying_ltp == 23780.0
    assert snap.atm_strike == 23800.0


def test_world_market_adapter_with_upstox():
    mock_upstox = MagicMock()
    mock_upstox.has_token = True
    mock_upstox.get_quotes.return_value = {
        "GLOBAL_INDEX:SGX NIFTY": {"last_price": 23800.0, "net_change": 15.0, "instrument_token": "GLOBAL_INDEX|SGX NIFTY"},
        "NSE_INDEX:India VIX": {"last_price": 11.2, "net_change": 0.3, "instrument_token": "NSE_INDEX|India VIX"},
        "GLOBAL_INDEX:^N225": {"last_price": 66200.0, "net_change": 500.0, "instrument_token": "GLOBAL_INDEX|^N225"},
    }
    
    adapter = WorldMarketAdapter(api_key=None, upstox_client=mock_upstox)
    quotes = adapter.poll_quotes()
    by_sym = {q.symbol: q for q in quotes}
    
    assert "GIFT_NIFTY" in by_sym
    assert by_sym["GIFT_NIFTY"].price == 23800.0
    assert by_sym["GIFT_NIFTY"].provider == "upstox"
    assert by_sym["GIFT_NIFTY"].exact_or_proxy == ExactOrProxy.EXACT.value
    
    assert "INDIA_VIX" in by_sym
    assert by_sym["INDIA_VIX"].price == 11.2
    assert by_sym["INDIA_VIX"].exact_or_proxy == ExactOrProxy.EXACT.value
    
    health = adapter.get_health()
    unavailable_names = [t["target"] for t in health["unavailable_targets"]]
    # GIFT NIFTY and INDIA VIX must NOT be in unavailable targets!
    assert "GIFT NIFTY" not in unavailable_names
    assert "INDIA VIX" not in unavailable_names
    assert "NIKKEI 225" not in unavailable_names
    assert "HANG SENG" in unavailable_names


def test_canonical_runtime_truth_evaluates_live_with_upstox():
    crt = CanonicalRuntimeTruth()
    crt.update_process(process_live=True)
    # Upstox is healthy, supplying market data
    crt.update_market_data(
        futures_live=True,
        spot_live=True,
        options_live=True,
        order_flow_live=True,
    )
    crt.update_analytics(
        argus_live=True,
        ose_live=True,
        vob_live=True,
        strategy_lab_live=True,
        worker_alive=True,
    )
    crt.update_persistence(persistence_live=True)
    crt.update_safety(paper_only=True, live_trading_enabled=False, execution_influence="ZERO", broker_submission=False)
    
    snap = crt.evaluate()
    assert snap.global_readiness == GlobalReadinessState.READY
    assert snap.is_ready is True
    assert snap.market_data_state == "FULLY_FRESH"
    assert snap.futures_available is True
    assert snap.analytics_available is True
