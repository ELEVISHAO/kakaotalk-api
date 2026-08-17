"""Tests for strict room open matching."""
from unittest.mock import patch

from kakao_mcp import controller


@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller.find_chat_window", return_value=111)
@patch(
    "kakao_mcp.controller.is_kakaotalk_running",
    return_value={"running": True, "hwnd": 1, "pid": 2},
)
def test_already_open_exact(mock_run, mock_find, mock_bring):
    r = controller.open_room_strict("한패스 고객센터")
    assert r["success"] is True
    assert r["hwnd"] == 111
    mock_bring.assert_called_once_with(111)


@patch(
    "kakao_mcp.controller.is_kakaotalk_running",
    return_value={"running": False, "hwnd": None, "pid": None},
)
def test_not_running(mock_run):
    r = controller.open_room_strict("Room")
    assert r["success"] is False
    assert r["error_code"] == "KAKAOTALK_NOT_RUNNING"


@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller.list_chat_windows")
@patch("kakao_mcp.controller._search_open_first_result", return_value={"success": True})
@patch("kakao_mcp.controller.find_chat_window", return_value=None)
@patch(
    "kakao_mcp.controller.is_kakaotalk_running",
    return_value={"running": True, "hwnd": 1, "pid": 2},
)
def test_mismatch_new_window(mock_run, mock_find, mock_search, mock_list, mock_sleep):
    mock_list.side_effect = [
        [],  # before
        [{"title": "한패스", "hwnd": 222}],  # after
    ]
    r = controller.open_room_strict("한패스 고객센터")
    assert r["success"] is False
    assert r["error_code"] == "ROOM_MISMATCH"
    assert r["actual_room"] == "한패스"
    assert r["expected_room"] == "한패스 고객센터"


@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller.list_chat_windows", return_value=[])
@patch("kakao_mcp.controller._search_open_first_result", return_value={"success": True})
@patch("kakao_mcp.controller.find_chat_window", return_value=None)
@patch(
    "kakao_mcp.controller.is_kakaotalk_running",
    return_value={"running": True, "hwnd": 1, "pid": 2},
)
def test_not_found(mock_run, mock_find, mock_search, mock_list, mock_sleep):
    r = controller.open_room_strict("MissingRoom")
    assert r["success"] is False
    assert r["error_code"] == "ROOM_NOT_FOUND"


@patch("kakao_mcp.controller.open_room_strict")
def test_search_and_open_delegates_strict(mock_strict):
    mock_strict.return_value = {"success": False, "error_code": "ROOM_MISMATCH"}
    r = controller.search_and_open_room("X")
    mock_strict.assert_called_once_with("X")
    assert r["error_code"] == "ROOM_MISMATCH"


def test_no_any_window_success_in_source():
    """Guard: fuzzy any-window success message must not exist in controller."""
    import inspect
    src = inspect.getsource(controller.open_room_strict)
    assert "Opened a chat window" not in src
    src2 = inspect.getsource(controller.search_and_open_room)
    assert "Opened a chat window" not in src2


@patch("kakao_mcp.controller.time.sleep")
@patch("kakao_mcp.controller.list_chat_windows", return_value=[])
@patch("kakao_mcp.controller._search_open_first_result", return_value={"success": True})
@patch(
    "kakao_mcp.controller.find_chat_window",
    side_effect=[None, None, 333],  # window title becomes ready after 2 retries
)
@patch(
    "kakao_mcp.controller.is_kakaotalk_running",
    return_value={"running": True, "hwnd": 1, "pid": 2},
)
def test_window_title_ready_after_delay(mock_run, mock_find, mock_search, mock_list, mock_sleep):
    """Race: after search opens the room, window title may take a moment to appear."""
    r = controller.open_room_strict("한패스 고객센터")
    assert r["success"] is True
    assert r["hwnd"] == 333
