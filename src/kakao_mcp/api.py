"""FastAPI HTTP server for KakaoTalk Windows Agent."""
from __future__ import annotations

import json
import sys
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from kakao_mcp.config import AgentSettings, load_agent_settings
from kakao_mcp.schemas import (
    ErrorCode,
    RoomOpenRequest,
    SendFileRequest,
    SendFilesRequest,
    SendImageRequest,
    SendMaterialsRequest,
    SendMessageRequest,
)
from kakao_mcp.service import KakaoService
from kakao_mcp.webhook import notify_failure_async


def normalize_client_ip(host: Optional[str]) -> str:
    if not host:
        return ""
    if host.startswith("::ffff:"):
        return host[7:]
    return host


class _WebhookFailureMiddleware(BaseHTTPMiddleware):
    """Send WeCom webhook notification for auth / business / server failures."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        response = await call_next(request)
        status = response.status_code
        payload = None
        needs_body = status >= 400 or (
            status == 200
            and "application/json" in response.headers.get("content-type", "")
        )

        if needs_body:
            body_bytes = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
            try:
                payload = json.loads(body_bytes) if body_bytes else {}
            except Exception:
                payload = {}
            response = JSONResponse(content=payload, status_code=status)

        webhook_url = getattr(request.app.state.settings, "webhook_url", "") or ""
        notify_failure_async(
            webhook_url,
            path=str(request.url.path),
            status_code=status,
            payload=payload,
        )
        return response


def create_app(
    settings: AgentSettings,
    service: Optional[KakaoService] = None,
) -> FastAPI:
    app = FastAPI(title="KakaoTalk Windows Agent", version="0.2.0")
    app.add_middleware(_WebhookFailureMiddleware)
    svc = service or KakaoService(settings=settings, enforce_file_root=True)
    if service is None:
        # keep singleton in sync for MCP coexistence in-process
        from kakao_mcp import service as service_mod
        service_mod._service = svc
    else:
        svc.settings = settings
        svc.enforce_file_root = True
    app.state.settings = settings
    app.state.service = svc

    def require_auth(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        client_host = normalize_client_ip(
            request.client.host if request.client else None
        )
        allow = settings.allow_ips
        if allow:
            if client_host not in allow:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error_code": ErrorCode.IP_NOT_ALLOWED,
                        "error": "Client IP not allowed",
                    },
                )
        if not x_api_key or x_api_key != settings.api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error_code": ErrorCode.INVALID_API_KEY,
                    "error": "Invalid or missing API key",
                },
            )
        return None

    @app.get("/health")
    def health(auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.health()

    @app.get("/rooms")
    def rooms(auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.list_rooms()

    @app.post("/rooms/open")
    def rooms_open(body: RoomOpenRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.open_room(body.room_name)

    @app.post("/send/message")
    def send_message(body: SendMessageRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.send_message(body.room_name, body.message)

    @app.post("/send/image")
    def send_image(body: SendImageRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.send_image(body.room_name, body.image_path)

    @app.post("/send/file")
    def send_file(body: SendFileRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.send_file(body.room_name, body.file_path)

    @app.post("/send/files")
    def send_files(body: SendFilesRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.send_files(body.room_name, body.file_paths)

    @app.post("/send/materials")
    def send_materials(body: SendMaterialsRequest, auth=Depends(require_auth)):
        if isinstance(auth, JSONResponse):
            return auth
        return svc.send_materials(
            body.room_name, body.job_id, body.message, body.files
        )

    @app.post("/send/materials/upload")
    async def send_materials_upload(
        room_name: str = Form(...),
        job_id: str = Form(...),
        message: str = Form(""),
        files: list[UploadFile] = File(default=[]),
        auth=Depends(require_auth),
    ):
        if isinstance(auth, JSONResponse):
            return auth
        uploads: list[tuple[str, bytes]] = []
        for f in files:
            content = await f.read()
            uploads.append((f.filename or "upload.bin", content))
        return svc.save_upload_and_send_materials(
            room_name, job_id, message, uploads
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR,
                "error": str(exc),
            },
        )

    return app


def main() -> None:
    try:
        settings = load_agent_settings()
    except RuntimeError as e:
        print(f"kakaotalk-api failed to start: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
