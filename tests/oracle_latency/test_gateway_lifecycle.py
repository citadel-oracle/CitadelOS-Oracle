import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from src.oracle.market_data_gateway import MarketDataGateway
import websockets

@pytest.fixture
def gateway():
    return MarketDataGateway(client_id="test", access_token="test")

@pytest.mark.asyncio
async def test_gateway_starts_once_and_stops_once(gateway):
    assert gateway._worker_task is None
    
    with patch('src.oracle.market_data_gateway.websockets.connect') as mock_connect:
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws
        
        # Start gateway in background
        task = asyncio.create_task(gateway.start())
        
        # Wait a tiny bit for the loop to start
        await asyncio.sleep(0.05)
        
        assert gateway._is_running is True
        # The websocket loop now owns only I/O.  Recorder and analytical
        # callback lanes are isolated workers rather than asyncio callbacks.
        assert gateway._worker_task is not None
        assert not gateway._worker_task.done()
        assert gateway._fanout_thread is not None and gateway._fanout_thread.is_alive()
        assert gateway._recorder_dispatch_thread is not None and gateway._recorder_dispatch_thread.is_alive()
        
        # Verify it tries to connect
        mock_connect.assert_called_once()
        
        # Now stop it
        if hasattr(gateway, 'stop'):
            await gateway.stop() 
        else:
            task.cancel() # It will fail because stop doesn't exist
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # This will fail before repair because `stop()` doesn't exist to cleanly shut it down
        assert gateway._is_running is False
        assert gateway._worker_task.done()
        assert not gateway._fanout_thread.is_alive()
        assert not gateway._recorder_dispatch_thread.is_alive()

@pytest.mark.asyncio
async def test_reconnect_resubscribes_exact_current_security_id(gateway):
    # If gateway drops connection, it must resubscribe to the currently requested instruments
    with patch('src.oracle.market_data_gateway.websockets.connect') as mock_connect:
        mock_ws = AsyncMock()
        
        async def mock_ws_iter():
            yield b'{"type": "connected"}'
            raise websockets.exceptions.ConnectionClosed(1006, "Abnormal")
            
        mock_ws.__aiter__.side_effect = mock_ws_iter
        mock_connect.return_value.__aenter__.return_value = mock_ws
        
        gateway.subscribe([{"security_id": "12345", "exchange_segment": "NSE_FO"}])
        gateway.RECONNECT_INITIAL_DELAY_SECONDS = 0.01
        gateway.RECONNECT_MAX_DELAY_SECONDS = 0.02
        gateway._backoff_jitter = lambda delay: delay

        task = asyncio.create_task(gateway.start())
        await asyncio.sleep(0.1)

        await gateway.stop()
        await asyncio.gather(task, return_exceptions=True)
        
        # This will fail if not implemented
        assert mock_ws.send.call_count >= 2
