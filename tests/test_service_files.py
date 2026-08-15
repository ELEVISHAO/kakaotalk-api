"""Service tests for file path validation and materials."""
from pathlib import Path
from unittest.mock import MagicMock

from kakao_mcp.config import AgentSettings
from kakao_mcp.service import KakaoService


class PassthroughManager:
    def submit(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _settings(root: Path) -> AgentSettings:
    return AgentSettings(
        api_key="secret",
        host="127.0.0.1",
        port=8765,
        allow_ips=[],
        allowed_file_root=str(root),
        max_file_size_mb=1,
        job_wait_timeout_sec=60.0,
        job_exec_timeout_sec=300.0,
        log_message_body=False,
    )


def test_path_traversal_rejected(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    svc = KakaoService(
        settings=_settings(root),
        ctrl=MagicMock(),
        job_manager=PassthroughManager(),
        enforce_file_root=True,
    )
    r = svc.validate_http_file_path(str(root / ".." / "secret.txt"))
    assert r["success"] is False
    assert r["error_code"] == "FILE_PATH_NOT_ALLOWED"


def test_file_missing(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    svc = KakaoService(
        settings=_settings(root),
        ctrl=MagicMock(),
        job_manager=PassthroughManager(),
    )
    r = svc.validate_http_file_path(str(root / "nope.pdf"))
    assert r["error_code"] == "FILE_NOT_FOUND"


def test_file_too_large(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    f = root / "big.bin"
    f.write_bytes(b"x" * (2 * 1024 * 1024))
    svc = KakaoService(
        settings=_settings(root),
        ctrl=MagicMock(),
        job_manager=PassthroughManager(),
    )
    r = svc.validate_http_file_path(str(f))
    assert r["error_code"] == "FILE_TOO_LARGE"


def test_materials_partial_failure(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    a = root / "a.pdf"
    b = root / "b.pdf"
    a.write_text("a")
    b.write_text("b")
    fake = MagicMock()
    fake.open_room_strict.return_value = {"success": True, "hwnd": 1}
    fake.send_message_to_room.return_value = {"success": True}
    fake.send_files_to_room.return_value = {
        "success": False,
        "results": [
            {"file": "a.pdf", "path": str(a), "success": True},
            {"file": "b.pdf", "path": str(b), "success": False, "detail": "fail"},
        ],
    }
    svc = KakaoService(
        settings=_settings(root),
        ctrl=fake,
        job_manager=PassthroughManager(),
    )
    r = svc.send_materials("Room", "GM-1", "hello", [str(a), str(b)])
    assert r["success"] is False
    assert r["message_sent"] is True
    assert r["completed_files"] == 1
    assert r["failed_file"] == "b.pdf"


def test_upload_saves_then_sends(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    fake = MagicMock()
    fake.open_room_strict.return_value = {"success": True, "hwnd": 1}
    fake.send_message_to_room.return_value = {"success": True}
    fake.send_files_to_room.return_value = {
        "success": True,
        "results": [{"file": "p.pdf", "success": True}],
    }
    svc = KakaoService(
        settings=_settings(root),
        ctrl=fake,
        job_manager=PassthroughManager(),
    )
    r = svc.save_upload_and_send_materials(
        "Room", "GM-2", "hi", [("p.pdf", b"%PDF")]
    )
    assert r["success"] is True
    saved = root / "GM-2" / "p.pdf"
    assert saved.is_file()
    assert saved.read_bytes() == b"%PDF"
