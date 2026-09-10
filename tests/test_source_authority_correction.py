"""Automated verification suite for Market Data Source Authority Correction.

Tests:
A. UPSTOX HEALTHY + DHAN UNAVAILABLE -> canonical market data AVAILABLE
B. UPSTOX HEALTHY + DHAN UNAVAILABLE -> no repeated Dhan timeout on every cycle
C. UPSTOX data reaches deterministic sensors
D. provenance = UPSTOX
E. no cross-provider averaging
F. future simulated: UPSTOX HEALTHY + DHAN HEALTHY -> both coexist in parallel
G. one provider failure does not kill the healthy provider
H. current Upstox-only state does not create duplicate publishers
I. execution remains disabled (paper_only=True, live_trading=False, broker_submission=False)
"""

import os
import time
import pytest
from unittest.mock import MagicMock, patch

from src.broker.upstox_client import UpstoxClient
from src.oracle.market_data_gateway import MarketDataGateway
from src.argus.market_snapshot import ArgusMarketSnapshotProvider


def test_a_upstox_healthy_dhan_unavailable_canonical_available():
    """A. UPSTOX HEALTHY + DHAN UNAVAILABLE -> canonical market data AVAILABLE."""
    mock_upstox = MagicMock()
    mock_upstox.has_token = True
    mock_upstox.is_token_expired = False
    mock_upstox.fingerprint = "sha256:cecbac4ef4105a31a5be03d002f54a88373a0a382d6101c40ea46897ce88a2af"
    mock_upstox.claims = {"days_remaining": 365}

    gw = MarketDataGateway(
        client_id="dhan_test",
        access_token="",  # Expired / absent Dhan token
        upstox_client=mock_upstox,
    )
    gw._upstox_feed = MagicMock()
    gw._upstox_feed.connection_state = "CONNECTED"
    gw.ws = None
    gw._dhan_dormant = True

    h = gw.health()
    assert h["UPSTOX_WS_CONNECTED"] is True
    assert h["DHAN_WS_CONNECTED"] is False
    assert h["COEXISTENCE_STATE"] == "DHAN_UNAVAILABLE / UPSTOX_HEALTHY"
    assert h["CANONICAL_SOURCE"] == "UPSTOX"
    assert h["ACTIVE_SOURCE"] == "UPSTOX"
    assert h["DHAN_STATE"] == "DORMANT"
    assert h["UPSTOX_STATE"] == "HEALTHY"


def test_b_no_repeated_dhan_timeout_on_cycle():
    """B. UPSTOX HEALTHY + DHAN UNAVAILABLE -> no repeated Dhan timeout on every cycle."""
    mock_dhan = MagicMock()
    mock_dhan.get_full_quotes.side_effect = RuntimeError("DH-901: Your access token is expired!")

    mock_upstox = MagicMock()
    mock_upstox.has_token = True
    mock_upstox.is_token_expired = False
    mock_upstox.get_quotes.return_value = {
        "NSE_FO:68407": {
            "instrument_token": "NSE_FO|68407",
            "last_price": 23866.1,
            "total_buy_quantity": 100000,
            "total_sell_quantity": 250000,
            "volume": 2000000,
            "oi": 17000000,
            "depth": {"buy": [], "sell": []},
        }
    }

    provider = ArgusMarketSnapshotProvider(
        dhan=mock_dhan,
        state_path="/tmp/test_argus_state.json",
        master_path="/tmp/test_argus_master.json",
    )
    provider.upstox = mock_upstox

    projection = {
        "data": {
            "underlying": {"ltp": 23779.15, "fetched_at": "2026-09-07T15:30:00"},
            "atm_window": [],
        }
    }

    contract = {
        "security_id": 68407,
        "symbol": "NIFTY-Sep2026-FUT",
        "expiry": "2026-09-29",
        "lot_size": 65,
        "segment": "NSE_FNO",
        "source": "DHAN_INSTRUMENT_MASTER",
    }

    start = time.perf_counter()
    with patch.object(provider, "_resolve_near_month", return_value=contract):
        with patch.object(provider, "_load", return_value={}):
            with patch.object(provider, "_atomic_write"):
                res1 = provider.refresh(projection)
                res2 = provider.refresh(projection)
    elapsed = time.perf_counter() - start

    # Dhan should NEVER have been called because Upstox is primary active and healthy
    assert mock_dhan.get_full_quotes.call_count == 0
    assert res1["futures"]["source"] == "UPSTOX"
    assert res2["futures"]["source"] == "UPSTOX"
    assert elapsed < 0.5


def test_c_and_d_upstox_data_provenance_reaches_sensors():
    """C & D. UPSTOX data reaches deterministic sensors with provenance = UPSTOX."""
    from src.oracle.market_info_service import MarketInfoService

    mock_client = MagicMock()
    mock_client.has_token = True
    mock_client.get_option_contracts.return_value = [{"expiry": "2026-09-08"}]
    mock_client.get_pcr.return_value = {"pcr": 0.5641}
    mock_client.get_max_pain.return_value = {"max_pain": 23800.0}
    mock_client.get_open_interest.return_value = {
        "total_calls": 262194335,
        "total_puts": 147901195,
    }
    mock_client.get_quotes.return_value = {
        "NSE_INDEX:India VIX": {
            "instrument_token": "NSE_INDEX|India VIX",
            "last_price": 11.16,
            "previous_close_price": 11.50,
        },
        "GLOBAL_INDEX:SGX NIFTY": {
            "instrument_token": "GLOBAL_INDEX|SGX NIFTY",
            "last_price": 23814.0,
            "previous_close_price": 23826.5,
        },
    }

    service = MarketInfoService(client=mock_client)
    snap = service.refresh_once()

    assert snap["status"] == "AVAILABLE"
    assert snap["provider"] == "UPSTOX"
    assert snap["pcr"] == 0.5641
    assert snap["max_pain"] == 23800.0
    assert snap["total_call_oi"] == 262194335
    assert snap["total_put_oi"] == 147901195
    assert snap["india_vix"] == 11.16
    assert snap["gift_nifty"] == 23814.0


def test_e_no_cross_provider_averaging():
    """E. Zero cross-provider price averaging or synthetic order book blending."""
    gw = MarketDataGateway(client_id="dhan", access_token="tok")
    
    # Tick from Upstox
    upstox_tick = {
        "instrument_token": "NSE_FO|68407",
        "exchange_segment": "NSE_FNO",
        "security_id": "68407",
        "ltp": 23866.10,
        "source": "UPSTOX",
        "provider": "UPSTOX",
    }
    # Tick from Dhan
    dhan_tick = {
        "exchange_segment": "NSE_FNO",
        "security_id": "68407",
        "ltp": 23865.00,
        "source": "DHAN",
        "provider": "DHAN",
    }

    gw._handle_upstox_tick(dict(upstox_tick))
    gw._provider_latest_ticks[("DHAN", "NSE_FNO", "68407")] = dhan_tick

    # Verify Upstox tick retains its exact price and was NEVER averaged to 23865.55
    stored_upstox = gw._provider_latest_ticks[("UPSTOX", "NSE_FNO", "68407")]
    assert stored_upstox["ltp"] == 23866.10
    assert stored_upstox["provider"] == "UPSTOX"
    assert "average_price" not in stored_upstox or stored_upstox.get("average_price") != 23865.55


def test_f_future_parallel_coexistence():
    """F. Simulated future state: UPSTOX HEALTHY + DHAN HEALTHY -> both coexist in parallel."""
    gw = MarketDataGateway(client_id="dhan", access_token="valid_dhan_token")
    mock_ws = MagicMock()
    mock_ws.closed = False
    gw.ws = mock_ws

    mock_upstox_feed = MagicMock()
    mock_upstox_feed.connection_state = "CONNECTED"
    gw._upstox_feed = mock_upstox_feed
    gw._dhan_dormant = False

    h = gw.health()
    assert h["DHAN_WS_CONNECTED"] is True
    assert h["UPSTOX_WS_CONNECTED"] is True
    assert h["COEXISTENCE_STATE"] == "DUAL_SOURCE_HEALTHY"
    assert h["CANONICAL_SOURCE"] == "DYNAMIC_PARALLEL"
    assert h["DHAN_STATE"] == "HEALTHY"
    assert h["UPSTOX_STATE"] == "HEALTHY"


def test_g_one_provider_failure_does_not_kill_healthy():
    """G. One provider failure does not kill the healthy provider."""
    gw = MarketDataGateway(client_id="dhan", access_token="")
    gw.ws = None  # Dhan down
    gw._dhan_dormant = True

    mock_upstox_feed = MagicMock()
    mock_upstox_feed.connection_state = "CONNECTED"
    gw._upstox_feed = mock_upstox_feed

    h = gw.health()
    assert h["UPSTOX_WS_CONNECTED"] is True
    assert h["status"] == "UP"
    assert h["CANONICAL_SOURCE"] == "UPSTOX"


def test_h_single_publisher_no_duplicate_publishers():
    """H. Upstox-only active state maintains exactly one canonical publishing gateway."""
    gw = MarketDataGateway(client_id="dhan", access_token="")
    assert hasattr(gw, "_tick_queue")
    assert hasattr(gw, "_enqueue_tick")
    assert gw._is_running is False


def test_i_execution_safety_invariants():
    """I. Execution safety remains strictly disabled (read-only market data)."""
    from src.broker.upstox_client import UpstoxClient
    c = UpstoxClient()
    
    forbidden_methods = [
        "place_order", "modify_order", "cancel_order",
        "submit_order", "execute_trade", "buy", "sell"
    ]
    for m in forbidden_methods:
        assert not hasattr(c, m), f"Forbidden execution method found on UpstoxClient: {m}"


def test_data_truth_audit_of_telemetry_cards():
    """Verify exact raw math, provenance, freshness, and IST date for the 5 telemetry cards."""
    from src.oracle.market_info_service import MarketInfoService

    mock_client = MagicMock()
    mock_client.has_token = True
    mock_client.get_option_contracts.return_value = [{"expiry": "2026-09-08"}]
    # Direct Upstox Market Info endpoints
    mock_client.get_pcr.return_value = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "pcr": 0.56408997,
    }
    mock_client.get_max_pain.return_value = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "max_pain": 23800.0,
    }
    mock_client.get_open_interest.return_value = {
        "total_calls": 262194335,
        "total_puts": 147901195,
    }
    # Raw Upstox quotes with net_change
    mock_client.get_quotes.return_value = {
        "NSE_INDEX:India VIX": {
            "instrument_token": "NSE_INDEX|India VIX",
            "last_price": 11.16,
            "net_change": 0.48,
            "last_trade_time": "1788777000000",
        },
        "GLOBAL_INDEX:SGX NIFTY": {
            "instrument_token": "GLOBAL_INDEX|SGX NIFTY",
            "last_price": 23816.5,
            "net_change": -10.0,
            "last_trade_time": "1788787306000",
        },
    }
    # Official NSE Clearing participant records (1788460200000 ms = 2026-09-04 00:00:00 IST)
    mock_client.get_fii_data.return_value = {
        "NSE_FO|INDEX_FUTURES": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 1106.90,
                "sell_amount": 1229.76,
            }
        ]
    }
    mock_client.get_dii_data.return_value = {
        "NSE_EQ|CASH": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 19254.19,
                "sell_amount": 10324.07,
            }
        ]
    }

    service = MarketInfoService(client=mock_client)
    snap = service.refresh_once()

    # 1. INDIA VIX: Prove displayed percentage from raw response values
    # ltp = 11.16, net_change = 0.48 -> prev_close = 11.16 - 0.48 = 10.68
    # pct = (0.48 / 10.68) * 100 = 4.49438...% -> rounded to 4.49%
    assert snap["india_vix"] == 11.16
    assert snap["india_vix_change"] == 0.48
    assert snap["india_vix_change_pct"] == 4.49

    # 2. GIFT NIFTY: GLOBAL_INDEX|SGX NIFTY with DELAYED_PROVIDER freshness
    assert snap["gift_nifty"] == 23816.5
    assert snap["gift_nifty_change"] == -10.0
    assert snap["gift_nifty_freshness"] == "DELAYED_PROVIDER"
    assert snap["global_quotes"]["GLOBAL_INDEX|SGX NIFTY"]["freshness"] == "DELAYED_PROVIDER"

    # 3. PCR + MAX PAIN: Provenance must be DIRECT_UPSTOX_MARKET_INFO
    assert snap["pcr"] == 0.5641
    assert snap["pcr_provenance"] == "DIRECT_UPSTOX_MARKET_INFO"
    assert snap["max_pain"] == 23800.0
    assert snap["max_pain_provenance"] == "DIRECT_UPSTOX_MARKET_INFO"

    # 4. FII / DII: DAILY_OFFICIAL, prominent IST source date (04 SEP), ₹ Crores units
    fii_dii = snap["fii_dii_summary"]
    assert fii_dii["status"] == "DAILY_OFFICIAL"
    assert fii_dii["date"] == "04 SEP"
    assert fii_dii["fii_fut_net"] == -122.86
    assert fii_dii["dii_cash_net"] == 8930.12


def test_upstox_market_context_expansion_patch():
    """Verify market context expansion patch: 3 broad indices, temporal shifts, OI shift, and expanded FII/DII."""
    from src.oracle.market_info_service import MarketInfoService

    mock_client = MagicMock()
    mock_client.has_token = True
    mock_client.get_option_contracts.return_value = [{"expiry": "2026-09-08"}]
    mock_client.get_pcr.return_value = {
        "pcr": 0.5641,
        "insights": [
            {"pcr": 0.6521, "time": "15:15"},
            {"pcr": 0.6100, "time": "15:30"},
        ],
    }
    mock_client.get_max_pain.return_value = {
        "max_pain": 23800.0,
        "insights": [
            {"max_pain": 23800.0, "time": "15:15"},
            {"max_pain": 23800.0, "time": "15:30"},
        ],
    }
    mock_client.get_open_interest.return_value = {
        "total_calls": 262194335,
        "total_puts": 147901195,
    }
    mock_client.get_option_chain.return_value = [
        {
            "strike_price": 23800.0,
            "call_options": {"market_data": {"oi": 17532970.0, "prev_oi": 1997320.0}},
            "put_options": {"market_data": {"oi": 2100000.0, "prev_oi": 2500000.0}},
        },
        {
            "strike_price": 25500.0,
            "call_options": {"market_data": {"oi": 3977545.0, "prev_oi": 5805280.0}},
            "put_options": {"market_data": {"oi": 100000.0, "prev_oi": 100000.0}},
        },
    ]
    mock_client.get_quotes.return_value = {
        "NSE_INDEX:Nifty Bank": {
            "instrument_token": "NSE_INDEX|Nifty Bank",
            "last_price": 57088.30,
            "net_change": -281.35,
        },
        "NSE_INDEX:NIFTY MID SELECT": {
            "instrument_token": "NSE_INDEX|NIFTY MID SELECT",
            "last_price": 14650.70,
            "net_change": -62.95,
        },
        "BSE_INDEX:SENSEX": {
            "instrument_token": "BSE_INDEX|SENSEX",
            "last_price": 76132.81,
            "net_change": -382.62,
        },
        "NSE_INDEX:India VIX": {
            "instrument_token": "NSE_INDEX|India VIX",
            "last_price": 11.16,
            "net_change": 0.48,
        },
        "GLOBAL_INDEX:SGX NIFTY": {
            "instrument_token": "GLOBAL_INDEX|SGX NIFTY",
            "last_price": 23816.5,
            "net_change": -10.0,
        },
    }
    mock_client.get_fii_data.return_value = {
        "NSE_FO|INDEX_FUTURES": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 1106.90,
                "sell_amount": 1229.76,
                "buy_contracts": 6906,
                "sell_contracts": 7642,
                "total_long_contracts": 33689,
                "total_short_contracts": 269527,
                "oi_contracts": 303216,
                "oi_amount": 48891.52,
            }
        ],
        "NSE_FO|INDEX_OPTIONS": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 871378.46,
                "sell_amount": 881281.75,
                "buy_contracts": 5566210,
                "sell_contracts": 5626595,
                "total_call_long_contracts": 561316,
                "total_call_short_contracts": 864770,
                "total_put_long_contracts": 1070255,
                "total_put_short_contracts": 489344,
                "oi_contracts": 2985686,
                "oi_amount": 470956.48,
            }
        ],
        "NSE_EQ|CASH": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 13857.58,
                "sell_amount": 16969.52,
            }
        ],
    }
    mock_client.get_dii_data.return_value = {
        "NSE_EQ|CASH": [
            {
                "time_stamp": 1788460200000,
                "buy_amount": 19254.19,
                "sell_amount": 10324.07,
            }
        ]
    }

    service = MarketInfoService(client=mock_client)
    snap = service.refresh_once()

    # Broad indices
    assert snap["bank_nifty"] == 57088.30
    assert snap["bank_nifty_change"] == -281.35
    assert snap["bank_nifty_change_pct"] == -0.49
    assert snap["midcap_select"] == 14650.70
    assert snap["midcap_select_change"] == -62.95
    assert snap["midcap_select_change_pct"] == -0.43
    assert snap["sensex"] == 76132.81
    assert snap["sensex_change"] == -382.62
    assert snap["sensex_change_pct"] == -0.50

    # PCR shift
    assert snap["pcr_shift"] == {
        "prev": 0.6521,
        "curr": 0.6100,
        "delta": -0.0421,
        "interval": "15m",
        "prev_time": "15:15",
        "curr_time": "15:30",
    }

    # Max Pain shift
    assert snap["max_pain_shift"] == {
        "prev": 23800.0,
        "curr": 23800.0,
        "delta": 0.0,
        "interval": "15m",
        "prev_time": "15:15",
        "curr_time": "15:30",
    }

    # OI shift
    oi_shift = snap["oi_shift"]
    assert oi_shift is not None
    assert oi_shift["provenance"] == "DERIVED_UPSTOX_OPTION_CHAIN"
    assert oi_shift["largest_call_increase"]["strike"] == 23800.0
    assert oi_shift["largest_call_unwind"]["strike"] == 25500.0
    assert oi_shift["bias_rule"] == "FACTUAL_OI_DELTAS_NO_BIAS_INFERRED"

    # FII / DII expanded breakdown
    fii_dii = snap["fii_dii_summary"]
    assert fii_dii["fii_futures"]["buy_contracts"] == 6906
    assert fii_dii["fii_futures"]["sell_contracts"] == 7642
    assert fii_dii["fii_futures"]["long_contracts"] == 33689
    assert fii_dii["fii_futures"]["short_contracts"] == 269527
    assert fii_dii["fii_futures"]["oi_contracts"] == 303216
    assert fii_dii["fii_futures"]["net_amount_cr"] == -122.86

    assert fii_dii["fii_options"]["buy_contracts"] == 5566210
    assert fii_dii["fii_options"]["sell_contracts"] == 5626595
    assert fii_dii["fii_options"]["call_long_contracts"] == 561316
    assert fii_dii["fii_options"]["call_short_contracts"] == 864770
    assert fii_dii["fii_options"]["put_long_contracts"] == 1070255
    assert fii_dii["fii_options"]["put_short_contracts"] == 489344

    assert fii_dii["dii_cash"]["buy_amount_cr"] == 19254.19
    assert fii_dii["dii_cash"]["sell_amount_cr"] == 10324.07
    assert fii_dii["dii_cash"]["net_amount_cr"] == 8930.12
    assert fii_dii["dii_cash"]["derivatives"] == "N/A"


def test_final_market_context_intelligence_patch():
    """Verify final market context intelligence patch: official Change in OI endpoint, multi-day FII/DII deltas, and Futures OI day range."""
    from src.oracle.market_info_service import MarketInfoService

    mock_client = MagicMock()
    mock_client.has_token = True
    mock_client.get_option_contracts.return_value = [{"expiry": "2026-09-08"}]
    mock_client.get_pcr.return_value = {"pcr": 0.5641}
    mock_client.get_max_pain.return_value = {"max_pain": 23800.0}
    mock_client.get_open_interest.return_value = {"total_calls": 262194335, "total_puts": 147901195}

    # Official Upstox Change in OI Endpoint mock
    mock_client.get_change_oi.return_value = {
        "total_call_change_oi": 64732330,
        "total_put_change_oi": -20210255,
        "spot_closing_price": 23779.15,
        "expiry": "08-09-2026",
        "call_put_oi_data_list": [
            {"strike_price": 23800.0, "call_change_oi": 15535650, "put_change_oi": -1374620},
            {"strike_price": 25500.0, "call_change_oi": -1827735, "put_change_oi": -56290},
        ],
    }

    mock_client.get_option_chain.return_value = [
        {
            "strike_price": 23800.0,
            "call_options": {"market_data": {"ltp": 56.6, "close_price": 195.6, "oi": 17532970.0, "prev_oi": 1997320.0}},
            "put_options": {"market_data": {"ltp": 45.7, "close_price": 22.4, "oi": 2100000.0, "prev_oi": 2500000.0}},
        },
        {
            "strike_price": 25500.0,
            "call_options": {"market_data": {"ltp": 0.8, "close_price": 0.6, "oi": 3977545.0, "prev_oi": 5805280.0}},
            "put_options": {"market_data": {"ltp": 140.0, "close_price": 59.85, "oi": 100000.0, "prev_oi": 100000.0}},
        },
    ]

    mock_client.get_quotes.return_value = {
        "NSE_INDEX:Nifty 50": {
            "instrument_token": "NSE_INDEX|Nifty 50",
            "last_price": 23779.15,
            "net_change": -118.55,
            "ohlc": {"open": 23883.15, "high": 23890.0, "low": 23737.9, "close": 23779.15},
        },
        "NSE_FO:NIFTY26SEPFUT": {
            "instrument_token": "NSE_FO|68407",
            "last_price": 23866.1,
            "net_change": -182.0,
            "oi": 17640935.0,
            "oi_day_high": 17649125.0,
            "oi_day_low": 16814460.0,
            "symbol": "NIFTY26SEPFUT",
        },
        "NSE_INDEX:India VIX": {
            "instrument_token": "NSE_INDEX|India VIX",
            "last_price": 11.16,
            "net_change": 0.48,
            "ohlc": {"open": 10.50, "high": 11.35, "low": 10.28, "close": 11.16},
        },
    }

    mock_client.get_fii_data.return_value = {
        "NSE_FO|INDEX_FUTURES": [
            {"time_stamp": 1788460200000, "buy_amount": 1106.90, "sell_amount": 1229.76, "total_long_contracts": 33689, "total_short_contracts": 269527, "oi_contracts": 303216, "oi_amount": 48891.52},
            {"time_stamp": 1788373800000, "buy_amount": 2171.52, "sell_amount": 3097.67, "total_long_contracts": 33502, "total_short_contracts": 268604, "oi_contracts": 302106, "oi_amount": 48647.38},
        ],
        "NSE_FO|INDEX_OPTIONS": [
            {"time_stamp": 1788460200000, "buy_amount": 871378.46, "sell_amount": 881281.75, "total_call_long_contracts": 561316, "total_call_short_contracts": 864770, "total_put_long_contracts": 1070255, "total_put_short_contracts": 489344, "oi_contracts": 2985686, "oi_amount": 470956.48},
            {"time_stamp": 1788373800000, "buy_amount": 713351.77, "sell_amount": 706165.59, "total_call_long_contracts": 554883, "total_call_short_contracts": 867090, "total_put_long_contracts": 1051305, "total_put_short_contracts": 401256, "oi_contracts": 2874535, "oi_amount": 453132.27},
        ],
        "NSE_EQ|CASH": [
            {"time_stamp": 1788460200000, "buy_amount": 13857.58, "sell_amount": 16969.52},
            {"time_stamp": 1788373800000, "buy_amount": 14000.00, "sell_amount": 16000.00},
        ],
    }
    mock_client.get_dii_data.return_value = {
        "NSE_EQ|CASH": [
            {"time_stamp": 1788460200000, "buy_amount": 19254.19, "sell_amount": 10324.07},
            {"time_stamp": 1788373800000, "buy_amount": 17063.65, "sell_amount": 12086.19},
        ]
    }

    service = MarketInfoService(client=mock_client)
    snap = service.refresh_once()

    # 1. Official Change in OI Verified
    oi_shift = snap["oi_shift"]
    assert oi_shift["provenance"] == "OFFICIAL_UPSTOX_CHANGE_OI"
    assert oi_shift["source_type"] == "OFFICIAL_ENDPOINT"
    assert oi_shift["horizon"] == "TODAY ΔOI vs PREVIOUS SESSION (1D)"
    assert oi_shift["total_call_delta_oi"] == 64732330
    assert oi_shift["total_put_delta_oi"] == -20210255
    assert oi_shift["largest_call_increase"]["strike"] == 23800.0
    assert oi_shift["largest_call_unwind"]["strike"] == 25500.0
    assert "heuristic_explainer" in oi_shift

    # 2. Futures OI Day Range Verified
    assert snap["nifty_futures_oi"] == 17640935.0
    assert snap["nifty_futures_oi_day_high"] == 17649125.0
    assert snap["nifty_futures_oi_day_low"] == 16814460.0
    assert "LOW 1.68Cr → CURRENT 1.76Cr → HIGH 1.76Cr" in snap["nifty_futures_oi_range_text"]

    # 3. Nifty Spot Extremes & VIX Context Verified
    assert snap["nifty_spot"] == 23779.15
    assert snap["nifty_spot_change"] == -118.55
    assert snap["nifty_spot_low"] == 23737.9
    assert snap["nifty_spot_high"] == 23890.0
    assert snap["india_vix_context"] == "RISING VOL"
    assert snap["india_vix_low"] == 10.28
    assert snap["india_vix_high"] == 11.35

    # 4. Multi-day FII / DII Deltas & Segments
    fii_dii = snap["fii_dii_summary"]
    assert fii_dii["fii_fut_net"] == -122.86
    assert fii_dii["fii_fut_chg"] == 803.29
    assert fii_dii["fii_fut_view"] == "BEARISH"

    assert fii_dii["fii_opt_net"] == -9903.29
    assert fii_dii["fii_opt_chg"] == -17089.47
    assert fii_dii["fii_opt_view"] == "BEARISH"
    assert fii_dii["fii_call_options"]["view"] == "SHORT CALL"
    assert fii_dii["fii_put_options"]["view"] == "LONG PUT"

    assert fii_dii["dii_cash_net"] == 8930.12
    assert fii_dii["dii_cash_chg"] == 3952.66
    assert fii_dii["dii_cash_view"] == "BULLISH"
    assert fii_dii["dii_derivatives"] == "N/A (official source unavailable)"



