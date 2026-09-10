import json
import pytest
from unittest.mock import MagicMock, patch
import time
from src.oracle.tradingview_sync import TradingViewMCPReader, TradingViewSyncError

class MockOsRead:
    def __init__(self, lines):
        self.data = "".join(lines).encode('utf-8')
        self.idx = 0
    def read(self, fd, size):
        if self.idx < len(self.data):
            res = self.data[self.idx:self.idx+size]
            self.idx += size
            return res
        return b""

@pytest.fixture
def mcp_mocks():
    with patch("subprocess.Popen") as mock_popen, \
         patch("os.read") as mock_os_read, \
         patch("select.select") as mock_select:
         
        process_mock = MagicMock()
        process_mock.stdin = MagicMock()
        process_mock.poll.return_value = None
        process_mock.stdout.fileno.return_value = 1
        mock_popen.return_value = process_mock
        
        mock_select.return_value = ([process_mock.stdout], [], [])
        
        yield process_mock, mock_os_read, mock_select

def test_jsonrpc_notification_before_response(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=1.0)
    
    lines = [
        '{"jsonrpc": "2.0", "id": 1, "result": {}}\n', # init
        '{"jsonrpc": "2.0", "method": "notifications/update"}\n', # unrelated notification
        '{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "{\\"success\\": true, \\"panes\\": []}"}]}}\n'
    ]
    reader_mock = MockOsRead(lines)
    mock_os_read.side_effect = reader_mock.read
    
    res = reader.read()
    assert res.get("success") is True

def test_unrelated_request_id_first(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=1.0)
    lines = [
        '{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
        '{"jsonrpc": "2.0", "id": 999, "result": {}}\n', # old request
        '{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "{\\"success\\": true}"}]}}\n'
    ]
    reader_mock = MockOsRead(lines)
    mock_os_read.side_effect = reader_mock.read
    
    res = reader.read()
    assert res.get("success") is True

def test_non_json_log_line(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=1.0)
    lines = [
        '{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
        'console.log("Some debug stuff");\n',
        '{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": "{\\"success\\": true}"}]}}\n'
    ]
    reader_mock = MockOsRead(lines)
    mock_os_read.side_effect = reader_mock.read
    
    res = reader.read()
    assert res.get("success") is True

def test_mcp_returns_jsonrpc_error(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=1.0)
    lines = [
        '{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
        '{"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "Internal error"}}\n'
    ]
    reader_mock = MockOsRead(lines)
    mock_os_read.side_effect = reader_mock.read
    
    with pytest.raises(TradingViewSyncError, match="TRADINGVIEW_MCP_RPC_ERROR:"):
        reader.read()

def test_mcp_timeout_kills_and_reaps(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=0.1)
    
    reader_mock = MockOsRead(['{"jsonrpc": "2.0", "id": 1, "result": {}}\n'])
    mock_os_read.side_effect = reader_mock.read
    mock_select.return_value = ([], [], []) # Timeout
    
    with pytest.raises(TradingViewSyncError, match="TRADINGVIEW_MCP_TIMEOUT"):
        reader.read()
            
    assert process_mock.terminate.called
    assert process_mock.wait.called

def test_repeated_reads_no_orphans(mcp_mocks):
    process_mock, mock_os_read, mock_select = mcp_mocks
    reader = TradingViewMCPReader(timeout_seconds=1.0)
    
    lines = ['{"jsonrpc": "2.0", "id": 1, "result": {}}\n']
    for i in range(2, 202):
        lines.append(f'{{"jsonrpc": "2.0", "id": {i}, "result": {{"content": [{{"text": "{{\\"success\\": true}}"}}]}}}}\n')
    
    reader_mock = MockOsRead(lines)
    mock_os_read.side_effect = reader_mock.read
    
    for _ in range(200):
        res = reader.read()
        assert res.get("success") is True
        
    assert process_mock.terminate.call_count == 0
