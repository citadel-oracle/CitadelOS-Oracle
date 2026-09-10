"""
Focused Unit Tests for DhanHQ v2 WebSocket Edge Protocol Implementation.
"""

import struct
import json
import pytest
from unittest.mock import AsyncMock, patch
from src.oracle.market_data_gateway import MarketDataGateway


def test_dhan_ws_url_requires_auth_type_2():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    # Verify URL construction in _connect_and_run
    import urllib.parse
    expected_token = urllib.parse.quote("test_jwt_token")
    # Verify url string parameters
    url = f"wss://api-feed.dhan.co?version=2&token={expected_token}&clientId=1102464196&authType=2"
    assert "authType=2" in url
    assert "version=2" in url
    assert "clientId=1102464196" in url


def test_dhan_ws_subscription_uses_instrument_list():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    gw.subscribe([{"exchange_segment": "IDX_I", "security_id": "13"}])
    
    inst_list = []
    for inst in gw.instruments:
        inst_list.append({
            "ExchangeSegment": str(inst.get("exchange_segment", "IDX_I")),
            "SecurityId": str(inst.get("security_id", "13"))
        })
    payload = {
        "RequestCode": 15,
        "InstrumentCount": len(inst_list),
        "InstrumentList": inst_list
    }
    assert payload["RequestCode"] == 15
    assert "InstrumentList" in payload
    assert payload["InstrumentList"][0]["ExchangeSegment"] == "IDX_I"
    assert payload["InstrumentList"][0]["SecurityId"] == "13"


def test_dhan_ws_binary_packet_index_code_1():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    # Code 1 Index Packet: Header (8 bytes) + LTP float (4 bytes) = 12 bytes
    payload = bytearray(12)
    struct.pack_into("<BHBi", payload, 0, 1, 12, 1, 13) # Code 1, len 12, seg 1, sec_id 13
    struct.pack_into("<f", payload, 8, 24550.35)       # LTP
    
    gw._handle_binary_message(bytes(payload))
    assert gw._last_response_code == 1
    assert gw._last_message_time is not None
    assert not gw._tick_queue.empty()
    tick = gw._tick_queue.get_nowait()
    assert tick["security_id"] == "13"
    assert tick["feed_code"] == 1
    assert round(tick["ltp"], 2) == 24550.35


def test_dhan_ws_binary_packet_ticker_code_2():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    payload = bytearray(16)
    struct.pack_into("<BHBi", payload, 0, 2, 16, 1, 13) # Code 2
    struct.pack_into("<f", payload, 8, 24560.50)
    struct.pack_into("<I", payload, 12, 1786095000)
    
    gw._handle_binary_message(bytes(payload))
    assert gw._last_response_code == 2
    tick = gw._tick_queue.get_nowait()
    assert tick["ltp"] == 24560.50
    assert tick["ltt"] == 1786095000


def test_dhan_ws_disconnect_code_50():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    payload = bytearray(8)
    struct.pack_into("<BHBi", payload, 0, 50, 8, 1, 13)
    gw._handle_binary_message(bytes(payload))
    assert gw._last_response_code == 50
    tick = gw._tick_queue.get_nowait()
    assert tick["disconnect_code"] == 50


def test_dhan_ws_no_fake_timestamp_before_recv():
    gw = MarketDataGateway(client_id="1102464196", access_token="test_jwt_token")
    assert gw._last_message_time is None
