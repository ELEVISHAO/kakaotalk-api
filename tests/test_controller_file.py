"""Controller tests for WM_DROPFILES file attachment helper."""
from unittest.mock import patch

import pytest

from kakao_mcp import controller


@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", side_effect=lambda p: p)
def test_build_hdrop_bytes_contains_path(mock_abs, mock_isfile):
    raw = controller._build_hdrop_bytes([r"C:\KakaoAgent\jobs\a.xlsx"])
    assert isinstance(raw, bytes)
    assert len(raw) > 20
    # UTF-16LE path should appear after DROPFILES header
    assert "C:\\KakaoAgent\\jobs\\a.xlsx".encode("utf-16le") in raw


@patch("os.path.isfile", return_value=False)
def test_build_hdrop_bytes_missing(mock_isfile):
    with pytest.raises(FileNotFoundError):
        controller._build_hdrop_bytes([r"C:\missing.xlsx"])


@patch("kakao_mcp.controller.ctypes.memmove")
@patch("kakao_mcp.controller._kernel32")
@patch("kakao_mcp.controller._user32")
@patch("kakao_mcp.controller._build_hdrop_bytes", return_value=b"\x00" * 24)
def test_post_files_wm_dropfiles_posts_message(
    mock_build, mock_user32, mock_kernel32, mock_memmove
):
    mock_kernel32.GlobalAlloc.return_value = 0x1234
    mock_kernel32.GlobalLock.return_value = 0x5678
    mock_user32.PostMessageW.return_value = 1

    controller._post_files_wm_dropfiles(999, [r"C:\KakaoAgent\jobs\a.xlsx"])

    mock_kernel32.GlobalAlloc.assert_called_once()
    mock_memmove.assert_called_once()
    mock_user32.PostMessageW.assert_called_once()
    args = mock_user32.PostMessageW.call_args[0]
    assert args[0] == 999
    assert args[1] == controller.WM_DROPFILES
    assert args[2] == 0x1234


@patch("kakao_mcp.controller._post_files_wm_dropfiles")
@patch("kakao_mcp.controller._wait_and_confirm_send_dialog", return_value=False)
@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller.find_chat_window", return_value=111)
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value=r"C:\KakaoAgent\jobs\a.xlsx")
def test_send_file_uses_wm_dropfiles_without_dialog(
    mock_abs, mock_isfile, mock_find, mock_bring, mock_wait, mock_post
):
    result = controller.send_file_to_room("TestRoom", r"C:\KakaoAgent\jobs\a.xlsx")
    assert result["success"] is True
    mock_post.assert_called_once_with(111, [r"C:\KakaoAgent\jobs\a.xlsx"])
    mock_bring.assert_called_once_with(111)


@patch("kakao_mcp.controller._post_files_wm_dropfiles", side_effect=OSError("post failed"))
@patch("kakao_mcp.controller.bring_window_to_front")
@patch("kakao_mcp.controller.find_chat_window", return_value=111)
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value=r"C:\KakaoAgent\jobs\a.xlsx")
def test_send_file_post_failure(mock_abs, mock_isfile, mock_find, mock_bring, mock_post):
    result = controller.send_file_to_room("TestRoom", r"C:\KakaoAgent\jobs\a.xlsx")
    assert result["success"] is False
    assert "drop" in result["error"].lower() or "failed" in result["error"].lower()
