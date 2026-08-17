"""Enterprise WeChat (企业微信) group robot webhook notifications."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import httpx

logger = logging.getLogger("kakao_mcp.webhook")


def build_wecom_markdown(
    *,
    path: str,
    status_code: int,
    error_code: str = "",
    error: str = "",
    room_name: str = "",
    job_id: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict:
    """Build 企业微信 markdown webhook body."""
    lines = [
        "## Kakao Agent 失败告警",
        f">path: `{path}`",
        f">http: <font color=\"warning\">{status_code}</font>",
    ]
    if error_code:
        lines.append(f">error_code: <font color=\"warning\">{error_code}</font>")
    if error:
        # keep content bounded for WeCom 4096-byte limit
        err = error.replace("\n", " ")[:500]
        lines.append(f">error: {err}")
    if room_name:
        lines.append(f">room: {room_name}")
    if job_id:
        lines.append(f">job_id: {job_id}")
    if extra:
        for k, v in list(extra.items())[:8]:
            lines.append(f">{k}: {v}")
    return {
        "msgtype": "markdown",
        "markdown": {"content": "\n".join(lines)},
    }


def should_notify_response(status_code: int, payload: Optional[dict]) -> bool:
    if status_code >= 400:
        return True
    if isinstance(payload, dict) and payload.get("success") is False:
        return True
    return False


def send_wecom_webhook(url: str, body: dict, timeout_sec: float = 5.0) -> None:
    if not url or not url.strip():
        return
    resp = httpx.post(url.strip(), json=body, timeout=timeout_sec)
    if resp.status_code >= 400:
        logger.warning("WeCom webhook HTTP %s: %s", resp.status_code, resp.text[:200])
    else:
        try:
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning("WeCom webhook err: %s", data)
        except Exception:
            pass


def _extract_error(payload: dict) -> str:
    """Extract a readable error string, handling FastAPI validation detail."""
    error = str(payload.get("error") or "")
    if error:
        return error
    detail = payload.get("detail")
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            loc = item.get("loc") or item.get("loc2") or []
            field = ".".join(str(x) for x in loc if x != "body")
            msg = str(item.get("msg") or "invalid")
            ctx = item.get("ctx")
            detail_msg = str(ctx.get("error")) if isinstance(ctx, dict) and ctx.get("error") else ""
            if detail_msg:
                msg = f"{msg} ({detail_msg})"
            if field:
                parts.append(f"{field}: {msg}")
            else:
                parts.append(msg)
        return "; ".join(parts)
    if detail:
        return str(detail)
    return ""


def notify_failure_async(
    webhook_url: str,
    *,
    path: str,
    status_code: int,
    payload: Optional[dict] = None,
) -> None:
    """Fire-and-forget WeCom notify. Never raises to caller."""
    if not webhook_url or not webhook_url.strip():
        return
    if not should_notify_response(status_code, payload):
        return

    payload = payload or {}
    body = build_wecom_markdown(
        path=path,
        status_code=status_code,
        error_code=str(payload.get("error_code") or ""),
        error=_extract_error(payload),
        room_name=str(payload.get("room_name") or payload.get("expected_room") or ""),
        job_id=str(payload.get("job_id") or ""),
    )

    def _run():
        try:
            send_wecom_webhook(webhook_url, body)
        except Exception as exc:
            logger.warning("WeCom webhook failed: %s", exc)

    threading.Thread(target=_run, name="wecom-webhook", daemon=True).start()
