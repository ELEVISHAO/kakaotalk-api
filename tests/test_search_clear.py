"""Tests for the search box clearing + paste logic in _search_open_first_result."""
from unittest.mock import patch, call

from kakao_mcp import controller


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller._focus_search_edit")
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_focuses_edit_before_paste(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_ctrl, mock_clip, mock_focus, mock_edit, mock_fg
):
    """Search Edit must be focused (AttachThreadInput+SetFocus) before Ctrl+V."""
    mock_gui.FindWindow.return_value = 100  # main window
    controller._search_open_first_result("테스트")

    # focus called on the edit hwnd before paste
    mock_focus.assert_called_once()
    assert mock_focus.call_args.args == (100, 77777)


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_clears_edit_before_paste(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_ctrl, mock_clip, mock_edit, mock_fg
):
    """Edit box must be cleared (WM_SETTEXT empty) before pasting the query."""
    mock_gui.FindWindow.return_value = 100  # main window
    result = controller._search_open_first_result("테스트")

    assert result["success"] is True

    # EM_SETSEL select-all then WM_SETTEXT to empty before typing
    calls = mock_api.SendMessage.call_args_list
    setsel_call = call(77777, 0x00B1, 0, -1)
    settext_call = call(77777, 0x000C, 0, "")
    assert setsel_call in calls
    assert settext_call in calls

    # query text goes to clipboard then Ctrl+V paste (handles CJK correctly)
    mock_clip.OpenClipboard.assert_called_once()
    mock_clip.SetClipboardText.assert_called_once_with("테스트", mock_clip.CF_UNICODETEXT)
    mock_ctrl.assert_any_call(0x56)  # Ctrl+V


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_clears_even_when_box_had_text(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_ctrl, mock_clip, mock_edit, mock_fg
):
    """Regression: previous query text must not leak into the new search."""
    mock_gui.FindWindow.return_value = 100
    controller._search_open_first_result("새검색")

    calls = mock_api.SendMessage.call_args_list
    # select all + clear
    assert call(77777, 0x00B1, 0, -1) in calls
    assert call(77777, 0x000C, 0, "") in calls
    mock_clip.SetClipboardText.assert_called_once_with("새검색", mock_clip.CF_UNICODETEXT)


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._double_click_first_result")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_no_enter_key_to_edit(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_dbl, mock_ctrl, mock_clip, mock_edit, mock_fg
):
    """The search result must be opened by double-click, not by sending an Enter
    key to the Edit control (Enter does not open the room reliably)."""
    mock_gui.FindWindow.return_value = 100
    controller._search_open_first_result("테스트")

    calls = mock_api.SendMessage.call_args_list
    for c in calls:
        assert c.args[1] != controller.config.WM_KEYDOWN, f"Enter/keydown sent: {c}"
    assert mock_dbl.called


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_no_wm_char_typing(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_ctrl, mock_clip, mock_edit, mock_fg
):
    """Regression: CJK search text must NOT be sent via WM_CHAR (breaks IME/search)."""
    mock_gui.FindWindow.return_value = 100
    controller._search_open_first_result("测试1")

    calls = mock_api.SendMessage.call_args_list
    for c in calls:
        assert c.args[1] != controller.config.WM_CHAR, f"WM_CHAR used: {c}"


@patch("kakao_mcp.controller._ensure_foreground", return_value=True)
@patch("kakao_mcp.controller._activate_search_and_get_edit", return_value=77777)
@patch("kakao_mcp.controller.win32clipboard")
@patch("kakao_mcp.controller._send_ctrl_key_combo")
@patch("kakao_mcp.controller._double_click_first_result")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32api")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_search_double_clicks_first_result(
    mock_sleep, mock_gui, mock_api, mock_user32, mock_dbl, mock_ctrl, mock_clip, mock_edit, mock_fg
):
    """After pasting, the first search result must be opened by double-clicking
    the result list (Enter/global keys do not reliably open the room)."""
    mock_gui.FindWindow.return_value = 100
    controller._search_open_first_result("테스트")

    mock_dbl.assert_called_once()


@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller.win32gui")
@patch("kakao_mcp.controller.time.sleep")
def test_double_click_first_result_clicks_search_list(
    mock_sleep, mock_gui, mock_user32, mock_bring
):
    """_double_click_first_result must find the visible SearchListCtrl and
    perform two left-clicks on its first row."""
    mock_gui.GetWindowText.return_value = "SearchListCtrl_0x001f17a4"
    mock_gui.GetClassName.return_value = "EVA_VH_ListControl_Dblclk"
    mock_gui.IsWindowVisible.return_value = True
    mock_gui.GetWindowRect.return_value = (235, 393, 561, 802)

    def enum_side_effect(parent, callback, lparam):
        callback(999, None)
        return None
    mock_gui.EnumChildWindows.side_effect = enum_side_effect

    ok = controller._double_click_first_result(100)
    assert ok is True

    # two left-click down/up pairs
    down = [c for c in mock_user32.mouse_event.call_args_list if c.args[0] == 0x0002]
    up = [c for c in mock_user32.mouse_event.call_args_list if c.args[0] == 0x0004]
    assert len(down) == 2
    assert len(up) == 2

    # clicked near top-center of the list (first row)
    pos = mock_user32.SetCursorPos.call_args.args
    assert pos == (398, 408)  # center x, top+15
