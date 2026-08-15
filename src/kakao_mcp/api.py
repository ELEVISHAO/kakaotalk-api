"""FastAPI HTTP server for KakaoTalk Windows Agent."""
from __future__ import annotations

import sys
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from kakao_mcp.config import AgentSettings, load_agent_settings
from kakao_mcp.schemas import (
    ErrorCode,
    RoomOpenRequest,
    SendMessageRequest,
)
from kakao_mcp.service import KakaoService, get_service


def normalize_client_ip(host: Optional[str]) -> str:
    if not host:
        return ""
    if host.startswith("::ffff:"):
        return host[7:]
    return host


def create_app(
    settings: AgentSettings,
    service: Optional[KakaoService] = None,
) -> FastAPI:
    app = FastAPI(title="KakaoTalk Windows Agent", version="0.2.0")
    svc = service or get_service(settings)
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
        # Enforce allowlist when configured OR when non-loopback bind
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
