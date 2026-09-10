import pytest
import asyncio
from unittest.mock import patch, MagicMock
from src.oracle.tradingview_sync import TradingViewMCPReader, TradingViewSyncError
import time

def test_mcp_reader_timeout():
    # If the MCP server hangs (does not print a line), the reader should timeout.
    reader = TradingViewMCPReader(timeout_seconds=0.1)
    
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        
        mock_proc.stdout.fileno.return_value = 1
        
        # Simulate stdout.readline blocking forever (or a very long time)
        def mock_select(rlist, wlist, xlist, timeout):
            time.sleep(timeout)
            return [], [], []
            
        with patch('select.select', side_effect=mock_select):
            start = time.time()
            try:
                reader.read()
            except TradingViewSyncError:
                pass
            end = time.time()
        
        # Test will fail if readline() blocks indefinitely, since timeout=0.1s
        assert end - start < 0.5, "MCP Reader did not enforce timeout!"

def test_mcp_reader_cleanup():
    reader = TradingViewMCPReader(timeout_seconds=0.1)
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        mock_proc.stdout.fileno.return_value = 1
        mock_proc.poll.return_value = None
        
        def mock_select(r, w, x, t): return [mock_proc.stdout], [], []
        
        # Give a valid response first to initialize the reader and process, then fail
        with patch('os.read', side_effect=[
            b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "{\\"success\\": true}"}]}}\n',
            Exception("Crash")
        ]):
            with patch('select.select', side_effect=mock_select):
                reader.read()
                
                with pytest.raises(TradingViewSyncError):
                    reader.read()
                    
        assert mock_proc.terminate.call_count >= 1
        assert reader._process is None
