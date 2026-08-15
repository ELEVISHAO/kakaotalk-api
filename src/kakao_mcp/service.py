"""Shared KakaoTalk business service for HTTP and MCP."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Callable, Optional

from kakao_mcp import controller
from kakao_mcp.config import AgentSettings
from kakao_mcp.job_manager import JobManager, JobWaitTimeout, get_job_manager
from kakao_mcp.schemas import ErrorCode

logger = logging.getLogger("kakao_agent")


class KakaoService:
    def __init__(
        self,
        settings: Optional[AgentSettings] = None,
        job_manager: Optional[JobManager] = None,
        ctrl: Any = None,
        enforce_file_root: bool = True,
    ):
        self.settings = settings
        self.job_manager = job_manager
        self.ctrl = ctrl or controller
        self.enforce_file_root = enforce_file_root

    def _submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        mgr = self.job_manager or get_job_manager(
            wait_timeout_sec=(
                self.settings.job_wait_timeout_sec if self.settings else 60.0
            ),
            exec_timeout_sec=(
                self.settings.job_exec_timeout_sec if self.settings else 300.0
            ),
        )
        try:
            return mgr.submit(fn, *args, **kwargs)
        except JobWaitTimeout:
            return {
                "success": False,
                "error_code": ErrorCode.AUTOMATION_BUSY,
                "error": "KakaoTalk UI automation is busy; try again later",
            }

    def health(self) -> dict:
        status = self.ctrl.is_kakaotalk_running()
        if status.get("running"):
            return {
                "success": True,
                "kakaotalk_running": True,
                "pid": status.get("pid"),
            }
        return {
            "success": False,
            "kakaotalk_running": False,
            "error_code": ErrorCode.KAKAOTALK_NOT_RUNNING,
        }

    def list_rooms(self) -> dict:
        status = self.ctrl.is_kakaotalk_running()
        if not status.get("running"):
            return {
                "success": False,
                "error_code": ErrorCode.KAKAOTALK_NOT_RUNNING,
                "error": "KakaoTalk is not running",
            }
        rooms = self.ctrl.list_chat_windows()
        return {
            "success": True,
            "rooms": [{"title": r["title"], "hwnd": r["hwnd"]} for r in rooms],
        }

    def open_room(self, room_name: str) -> dict:
        return self._submit(self.ctrl.open_room_strict, room_name)

    def send_message(self, room_name: str, message: str) -> dict:
        if not message or not message.strip():
            return {
                "success": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error": "Message cannot be empty",
            }
        return self._submit(self._send_message_job, room_name, message)

    def _send_message_job(self, room_name: str, message: str) -> dict:
        started = time.monotonic()
        open_result = self.ctrl.open_room_strict(room_name)
        if not open_result.get("success"):
            return open_result

        send_result = self.ctrl.send_message_to_room(room_name, message)
        if not send_result.get("success"):
            return {
                "success": False,
                "error_code": ErrorCode.MESSAGE_SEND_FAILED,
                "error": send_result.get("error", "Message send failed"),
                "room_name": room_name,
            }

        self._log_send(
            job_id=None,
            room_name=room_name,
            message_sent=True,
            files=[],
            success=True,
            error_code=None,
            error=None,
            duration=time.monotonic() - started,
            message=message,
        )
        return {
            "success": True,
            "room_name": room_name,
            "automation_success": True,
            "verification": "UI_ACTION_COMPLETED",
        }

    def _log_send(
        self,
        *,
        job_id: Optional[str],
        room_name: str,
        message_sent: bool,
        files: list[str],
        success: bool,
        error_code: Optional[str],
        error: Optional[str],
        duration: float,
        message: Optional[str] = None,
    ) -> None:
        msg_len = len(message) if message else 0
        msg_hash = (
            hashlib.sha256(message.encode("utf-8")).hexdigest()[:16] if message else None
        )
        payload = {
            "job_id": job_id,
            "room_name": room_name,
            "message_sent": message_sent,
            "file_count": len(files),
            "files": files,
            "success": success,
            "error_code": error_code,
            "error": error,
            "duration": round(duration, 3),
            "message_length": msg_len,
            "message_hash": msg_hash,
        }
        if (
            message
            and self.settings
            and self.settings.log_message_body
        ):
            payload["message"] = message
        logger.info("send_job %s", payload)


_service: Optional[KakaoService] = None


def get_service(settings: Optional[AgentSettings] = None) -> KakaoService:
    global _service
    if _service is None:
        _service = KakaoService(settings=settings, enforce_file_root=True)
    return _service


def reset_service_for_tests() -> None:
    global _service
    _service = None
