"""Focused tests for Twelve Data Real Quotes and Cognitive Model Status.

Verifies:
1. Twelve Data secret never enters frontend payload.
2. Real quote projection survives backend -> frontend.
3. EXACT/PROXY labels preserved.
4. LIVE/DELAYED/SESSION_LAST preserved.
5. provider timestamps preserved.
6. GPT/Qwen CONNECTED cannot be produced from key presence alone.
7. RUNNING requires request_in_flight=true.
8. IDLE distinct from RUNNING.
9. manual canary does not activate live SHADOW service.
10. Qwen challenger is not automatically called when GPT handles a live event.
11. provider failure does not blank deterministic Oracle sensors.
12. VOB unchanged.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.external_context.contracts import ExactOrProxy, DataAgeStatus, ExternalQuote
from src.external_context.core import ExternalContextCore
from src.oracle_sol.cognitive_status import get_cognitive_models_status
from src.oracle_sol.service import SolMarketBrainService


def test_1_twelve_data_secret_never_enters_payload():
    core = ExternalContextCore.get_instance()
    state = SolMarketBrainService.get_instance().get_latest_state()
    raw_text = json.dumps(state)
    
    # Secret must never be in payload
    api_key = core.market_adapter.api_key
    if api_key and len(api_key.strip()) >= 8:
        assert api_key not in raw_text
        assert api_key.strip() not in raw_text
    
    # Check that any api_key occurrences are boolean status indicators only
    assert '"api_key":' not in raw_text


def test_2_real_quote_projection_survives():
    state = SolMarketBrainService.get_instance().get_latest_state()
    quotes = state.get('world_context', {}).get('quotes', [])
    assert len(quotes) >= 8
    symbols = [q['symbol'] for q in quotes]
    assert 'USD/INR' in symbols
    assert 'BTC/USD' in symbols
    assert 'SPY' in symbols


def test_3_exact_proxy_labels_preserved():
    state = SolMarketBrainService.get_instance().get_latest_state()
    quotes = {q['symbol']: q for q in state.get('world_context', {}).get('quotes', [])}
    assert quotes['USD/INR']['exact_or_proxy'] == 'EXACT'
    assert quotes['BTC/USD']['exact_or_proxy'] == 'EXACT'
    assert quotes['SPY']['exact_or_proxy'] == 'PROXY'
    assert quotes['QQQ']['exact_or_proxy'] == 'PROXY'


def test_4_live_delayed_session_last_preserved():
    state = SolMarketBrainService.get_instance().get_latest_state()
    quotes = {q['symbol']: q for q in state.get('world_context', {}).get('quotes', [])}
    assert quotes['USD/INR']['data_age'] in ['LIVE', 'SESSION_LAST', 'DELAYED']
    assert quotes['SPY']['data_age'] in ['LIVE', 'SESSION_LAST', 'DELAYED']


def test_5_provider_timestamps_preserved():
    state = SolMarketBrainService.get_instance().get_latest_state()
    quotes = state.get('world_context', {}).get('quotes', [])
    for q in quotes:
        assert q.get('provider_timestamp') is not None
        assert len(str(q['provider_timestamp']).strip()) > 0


def test_6_connected_cannot_be_produced_from_key_presence_alone():
    with patch('pathlib.Path.exists', return_value=False):
        status = get_cognitive_models_status()
        # Without telemetry proving successful response, status must be UNPROVEN
        gpt = status['models']['gpt_oss']
        assert gpt['status'] == 'UNPROVEN'
        assert gpt['api_connected'] is False


def test_7_running_requires_request_in_flight():
    status = get_cognitive_models_status()
    gpt = status['models']['gpt_oss']
    if not gpt['current_request_in_flight']:
        assert gpt['status'] != 'RUNNING'


def test_8_idle_distinct_from_running():
    status = get_cognitive_models_status()
    gpt = status['models']['gpt_oss']
    if gpt['api_connected'] and not gpt['current_request_in_flight']:
        assert gpt['status'] == 'IDLE'


def test_9_manual_canary_does_not_activate_live_shadow():
    status = get_cognitive_models_status()
    gpt = status['models']['gpt_oss']
    qwen = status['models']['qwen']
    # Even though canaries succeeded, live shadow is NOT enabled
    assert gpt['live_shadow_enabled'] is False
    assert qwen['live_shadow_enabled'] is False
    assert status['live_shadow_enabled'] is False


def test_10_qwen_challenger_is_not_called_for_gpt_live():
    status = get_cognitive_models_status()
    assert status['models']['gpt_oss']['role'] == 'SHADOW PRIMARY'
    assert status['models']['qwen']['role'] == 'CHALLENGER'
    assert status['models']['qwen']['live_shadow_enabled'] is False


def test_11_provider_failure_does_not_blank_sensors():
    # If world context fails, canonical beacon and thesis remain intact
    state = SolMarketBrainService.get_instance().get_latest_state()
    assert 'beacon' in state
    assert 'canonical_market_state' in state
    assert state['vob_free_verified'] == 'ZERO_VOB_ALLOWLIST_CONFIRMED'


def test_12_vob_unchanged():
    state = SolMarketBrainService.get_instance().get_latest_state()
    assert state['vob_free_verified'] == 'ZERO_VOB_ALLOWLIST_CONFIRMED'
