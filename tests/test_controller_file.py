"""Controller tests for CF_HDROP file clipboard helper."""
from unittest.mock import patch

import pytest

from kakao_mcp import controller


@patch("kakao_mcp.controller.win32clipboard")
@patch("os.path.isfile", return_value=True)
@patch("os.path.abspath", return_value=r"C:\KakaoAgent\jobs\a.pdf")
def test_copy_hdrop_sets_clipboard(mock_abs, mock_isfile, mock_clip):
    controller._copy_files_to_clipboard_hdrop([r"C:\KakaoAgent\jobs\a.pdf"])
    mock_clip.OpenClipboard.assert_called_once()
    mock_clip.EmptyClipboard.assert_called_once()
    mock_clip.SetClipboardData.assert_called_once()
    args = mock_clip.SetClipboardData.call_args[0]
    assert args[0]  # CF_HDROP constant
    assert isinstance(args[1], (bytes, memoryview))


@patch("os.path.isfile", return_value=False)
def test_copy_hdrop_missing(mock_isfile):
    with pytest.raises(FileNotFoundError):
        controller._copy_files_to_clipboard_hdrop([r"C:\missing.pdf"])
