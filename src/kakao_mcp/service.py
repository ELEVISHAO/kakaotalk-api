"""Shared KakaoTalk business service for HTTP and MCP."""
from __future__ import annotations

import hashlib
import logging
import os
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

    def validate_http_file_path(self, file_path: str) -> dict:
        """Validate path for HTTP sends (allowlist, exists, size)."""
        from pathlib import Path

        if not self.settings:
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR,
                "error": "Agent settings not configured",
            }
        try:
            root = Path(self.settings.allowed_file_root).resolve()
            resolved = Path(file_path).resolve()
        except OSError as e:
            return {
                "success": False,
                "error_code": ErrorCode.FILE_NOT_FOUND,
                "error": str(e),
            }

        try:
            resolved.relative_to(root)
        except ValueError:
            return {
                "success": False,
                "error_code": ErrorCode.FILE_PATH_NOT_ALLOWED,
                "error": f"Path outside allowed root: {file_path}",
            }

        if not resolved.is_file():
            return {
                "success": False,
                "error_code": ErrorCode.FILE_NOT_FOUND,
                "error": f"File not found: {file_path}",
            }

        max_bytes = self.settings.max_file_size_mb * 1024 * 1024
        size = resolved.stat().st_size
        if size > max_bytes:
            return {
                "success": False,
                "error_code": ErrorCode.FILE_TOO_LARGE,
                "error": f"File exceeds {self.settings.max_file_size_mb} MB",
            }
        return {"success": True, "path": str(resolved)}

    def send_image(self, room_name: str, image_path: str) -> dict:
        return self._submit(self._send_image_job, room_name, image_path)

    def _send_image_job(self, room_name: str, image_path: str) -> dict:
        if self.enforce_file_root:
            check = self.validate_http_file_path(image_path)
            if not check["success"]:
                return check
            image_path = check["path"]

        open_result = self.ctrl.open_room_strict(room_name)
        if not open_result.get("success"):
            return open_result

        result = self.ctrl.send_image_to_room(room_name, image_path)
        if not result.get("success"):
            return {
                "success": False,
                "error_code": ErrorCode.IMAGE_SEND_FAILED,
                "error": result.get("error", "Image send failed"),
                "room_name": room_name,
            }
        return {
            "success": True,
            "room_name": room_name,
            "automation_success": True,
            "verification": "UI_ACTION_COMPLETED",
        }

    def send_file(self, room_name: str, file_path: str) -> dict:
        return self._submit(self._send_file_job, room_name, file_path)

    def _send_file_job(self, room_name: str, file_path: str) -> dict:
        if self.enforce_file_root:
            check = self.validate_http_file_path(file_path)
            if not check["success"]:
                return check
            file_path = check["path"]

        open_result = self.ctrl.open_room_strict(room_name)
        if not open_result.get("success"):
            return open_result

        result = self.ctrl.send_file_to_room(room_name, file_path)
        if not result.get("success"):
            return {
                "success": False,
                "error_code": ErrorCode.FILE_SEND_FAILED,
                "error": result.get("error", "File send failed"),
                "room_name": room_name,
            }
        return {
            "success": True,
            "room_name": room_name,
            "automation_success": True,
            "verification": "UI_ACTION_COMPLETED",
        }

    def send_files(self, room_name: str, file_paths: list[str]) -> dict:
        return self._submit(self._send_files_job, room_name, file_paths)

    def _send_files_job(self, room_name: str, file_paths: list[str]) -> dict:
        if not file_paths:
            return {
                "success": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error": "file_paths cannot be empty",
            }

        resolved: list[str] = []
        if self.enforce_file_root:
            for p in file_paths:
                check = self.validate_http_file_path(p)
                if not check["success"]:
                    return check
                resolved.append(check["path"])
        else:
            resolved = file_paths

        open_result = self.ctrl.open_room_strict(room_name)
        if not open_result.get("success"):
            return open_result

        result = self.ctrl.send_files_to_room(room_name, resolved)
        files_out = []
        for item in result.get("results", []):
            entry = {
                "file": item.get("file") or os.path.basename(item.get("path", "")),
                "success": bool(item.get("success")),
            }
            if item.get("skipped"):
                entry["skipped"] = True
            if not item.get("success") and not item.get("skipped"):
                entry["error_code"] = ErrorCode.FILE_SEND_FAILED
            files_out.append(entry)

        if result.get("success"):
            return {
                "success": True,
                "room_name": room_name,
                "files": files_out,
                "automation_success": True,
                "verification": "UI_ACTION_COMPLETED",
            }

        failed = next((f for f in files_out if not f["success"] and not f.get("skipped")), None)
        return {
            "success": False,
            "room_name": room_name,
            "error_code": ErrorCode.FILE_SEND_FAILED,
            "files": files_out,
            "failed_file": failed["file"] if failed else None,
            "completed_files": sum(1 for f in files_out if f["success"]),
        }

    def send_materials(
        self,
        room_name: str,
        job_id: str,
        message: str = "",
        files: Optional[list[str]] = None,
    ) -> dict:
        files = files or []
        return self._submit(self._send_materials_job, room_name, job_id, message, files)

    def _send_materials_job(
        self,
        room_name: str,
        job_id: str,
        message: str,
        files: list[str],
    ) -> dict:
        import re
        from pathlib import Path

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id or ""):
            return {
                "success": False,
                "error_code": ErrorCode.INVALID_JOB_ID,
                "error": "Invalid job_id",
                "job_id": job_id,
            }

        msg = message or ""
        if not msg.strip() and not files:
            return {
                "success": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error": "message and files cannot both be empty",
                "job_id": job_id,
            }

        resolved: list[str] = []
        if self.enforce_file_root:
            for p in files:
                check = self.validate_http_file_path(p)
                if not check["success"]:
                    check = {**check, "job_id": job_id, "room_name": room_name}
                    return check
                resolved.append(check["path"])
        else:
            resolved = list(files)

        started = time.monotonic()
        open_result = self.ctrl.open_room_strict(room_name)
        if not open_result.get("success"):
            return {**open_result, "job_id": job_id}

        # Attachments first, then caption text. Doing text-before-files often left
        # pasted text stuck in the edit box when Enter lost focus before WM_DROPFILES.
        files_out: list[dict] = []
        completed = 0
        if resolved:
            file_result = self.ctrl.send_files_to_room(room_name, resolved)
            for item in file_result.get("results", []):
                entry = {
                    "file": item.get("file") or Path(item.get("path", "")).name,
                    "success": bool(item.get("success")),
                }
                if item.get("skipped"):
                    entry["skipped"] = True
                if not item.get("success") and not item.get("skipped"):
                    entry["error_code"] = ErrorCode.FILE_SEND_FAILED
                if entry["success"]:
                    completed += 1
                files_out.append(entry)

            if not file_result.get("success"):
                failed = next(
                    (f for f in files_out if not f["success"] and not f.get("skipped")),
                    None,
                )
                self._log_send(
                    job_id=job_id,
                    room_name=room_name,
                    message_sent=False,
                    files=[f["file"] for f in files_out],
                    success=False,
                    error_code=ErrorCode.FILE_SEND_FAILED,
                    error="partial file failure",
                    duration=time.monotonic() - started,
                    message=msg if msg.strip() else None,
                )
                return {
                    "success": False,
                    "job_id": job_id,
                    "room_name": room_name,
                    "message_sent": False,
                    "error_code": ErrorCode.FILE_SEND_FAILED,
                    "completed_files": completed,
                    "failed_file": failed["file"] if failed else None,
                    "files": files_out,
                }
            if msg.strip():
                time.sleep(0.4)

        message_sent = False
        if msg.strip():
            send_result = self.ctrl.send_message_to_room(room_name, msg)
            if not send_result.get("success"):
                self._log_send(
                    job_id=job_id,
                    room_name=room_name,
                    message_sent=False,
                    files=[f["file"] for f in files_out],
                    success=False,
                    error_code=ErrorCode.MESSAGE_SEND_FAILED,
                    error=send_result.get("error", "Message send failed"),
                    duration=time.monotonic() - started,
                    message=msg,
                )
                return {
                    "success": False,
                    "job_id": job_id,
                    "room_name": room_name,
                    "message_sent": False,
                    "error_code": ErrorCode.MESSAGE_SEND_FAILED,
                    "error": send_result.get("error", "Message send failed"),
                    "files": files_out,
                    "completed_files": completed,
                }
            message_sent = True

        self._log_send(
            job_id=job_id,
            room_name=room_name,
            message_sent=message_sent,
            files=[f["file"] for f in files_out],
            success=True,
            error_code=None,
            error=None,
            duration=time.monotonic() - started,
            message=msg if msg.strip() else None,
        )
        return {
            "success": True,
            "job_id": job_id,
            "room_name": room_name,
            "message_sent": message_sent,
            "files": files_out,
            "automation_success": True,
            "verification": "UI_ACTION_COMPLETED",
        }

    def save_upload_and_send_materials(
        self,
        room_name: str,
        job_id: str,
        message: str,
        uploads: list[tuple[str, bytes]],
    ) -> dict:
        """Save multipart uploads under allowed root, then send_materials."""
        import re
        from pathlib import Path

        if not self.settings:
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR,
                "error": "Agent settings not configured",
            }
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id or ""):
            return {
                "success": False,
                "error_code": ErrorCode.INVALID_JOB_ID,
                "error": "Invalid job_id",
                "job_id": job_id,
            }

        root = Path(self.settings.allowed_file_root).resolve()
        job_dir = (root / job_id).resolve()
        try:
            job_dir.relative_to(root)
        except ValueError:
            return {
                "success": False,
                "error_code": ErrorCode.FILE_PATH_NOT_ALLOWED,
                "error": "Invalid job directory",
            }
        job_dir.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        max_bytes = self.settings.max_file_size_mb * 1024 * 1024
        for filename, content in uploads:
            name = Path(filename).name
            if not name or name in (".", ".."):
                return {
                    "success": False,
                    "error_code": ErrorCode.INVALID_REQUEST,
                    "error": f"Invalid upload filename: {filename}",
                }
            if len(content) > max_bytes:
                return {
                    "success": False,
                    "error_code": ErrorCode.FILE_TOO_LARGE,
                    "error": f"Upload exceeds {self.settings.max_file_size_mb} MB: {name}",
                }
            dest = job_dir / name
            dest.write_bytes(content)
            saved.append(str(dest))

        return self.send_materials(room_name, job_id, message, saved)


_service: Optional[KakaoService] = None


def get_service(settings: Optional[AgentSettings] = None) -> KakaoService:
    global _service
    if _service is None:
        _service = KakaoService(settings=settings, enforce_file_root=True)
    return _service


def reset_service_for_tests() -> None:
    global _service
    _service = None
