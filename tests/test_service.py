"""Tests for KakaoService core methods."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from kakao_mcp.job_manager import JobManager
from kakao_mcp.service import KakaoService


class PassthroughManager:
    """Run jobs inline without a background thread."""

    def submit(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def test_send_message_requires_non_empty():
    svc = KakaoService(ctrl=MagicMock(), job_manager=PassthroughManager())
    r = svc.send_message("Room", "   ")
    assert r["success"] is False
    assert r["error_code"] == "INVALID_REQUEST"


def test_send_message_opens_then_sends():
    fake = MagicMock()
    fake.open_room_strict.return_value = {"success": True, "hwnd": 1}
    fake.send_message_to_room.return_value = {"success": True, "message": "ok"}
    svc = KakaoService(ctrl=fake, job_manager=PassthroughManager())
    r = svc.send_message("Room", "hi")
    assert r["success"] is True
    assert r["automation_success"] is True
    assert r["verification"] == "UI_ACTION_COMPLETED"
    assert "delivered" not in r
    fake.open_room_strict.assert_called_once_with("Room")
    fake.send_message_to_room.assert_called_once_with("Room", "hi")


def test_health_running():
    fake = MagicMock()
    fake.is_kakaotalk_running.return_value = {"running": True, "pid": 99, "hwnd": 1}
    svc = KakaoService(ctrl=fake, job_manager=PassthroughManager())
    r = svc.health()
    assert r == {"success": True, "kakaotalk_running": True, "pid": 99}


def test_list_rooms_not_running():
    fake = MagicMock()
    fake.is_kakaotalk_running.return_value = {"running": False}
    svc = KakaoService(ctrl=fake, job_manager=PassthroughManager())
    r = svc.list_rooms()
    assert r["success"] is False
    assert r["error_code"] == "KAKAOTALK_NOT_RUNNING"


def test_open_room_queued_via_manager():
    fake = MagicMock()
    fake.open_room_strict.return_value = {"success": True, "hwnd": 5}
    mgr = JobManager(wait_timeout_sec=5, exec_timeout_sec=10)
    mgr.start()
    try:
        svc = KakaoService(ctrl=fake, job_manager=mgr)
        r = svc.open_room("Room")
        assert r["success"] is True
    finally:
        mgr.stop()
