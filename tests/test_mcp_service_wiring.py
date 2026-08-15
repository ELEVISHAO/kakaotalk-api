"""MCP wiring tests (call tool functions directly)."""
from unittest.mock import MagicMock, patch

from kakao_mcp import server
from kakao_mcp.schemas import ErrorCode


def test_monitor_disabled():
    r = server.kakao_start_monitor("Room", ["hi"])
    assert r["error_code"] == ErrorCode.MONITOR_DISABLED
    r2 = server.kakao_stop_monitor()
    assert r2["error_code"] == ErrorCode.MONITOR_DISABLED


@patch("kakao_mcp.server._svc")
def test_open_room_mismatch(mock_svc):
    svc = MagicMock()
    svc.open_room.return_value = {
        "success": False,
        "error_code": "ROOM_MISMATCH",
        "error": "mismatch",
        "expected_room": "A",
        "actual_room": "B",
    }
    mock_svc.return_value = svc
    r = server.kakao_open_room("A")
    assert r["error_code"] == "ROOM_MISMATCH"
    assert r["actual_room"] == "B"
