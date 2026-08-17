#!/usr/bin/env python
"""MCP Server for KakaoTalk PC automation via Win32 API."""
import os
import time
from typing import Dict, Optional

from mcp.server.fastmcp import FastMCP

from kakao_mcp import controller
from kakao_mcp import parser
from kakao_mcp import config
from kakao_mcp.schemas import ErrorCode
from kakao_mcp.service import KakaoService, get_service

app = FastMCP(
    "kakao-mcp-server",
    instructions="MCP Server for KakaoTalk PC automation via Win32 API",
)


def _svc() -> KakaoService:
    # MCP does not enforce HTTP file root
    svc = get_service()
    svc.enforce_file_root = False
    return svc


def _mcp_from_service(result: Dict) -> Dict:
    """Adapt service dict to MCP {message}/{error} (+ error_code)."""
    if result.get("success"):
        out = {k: v for k, v in result.items() if k not in ("success",)}
        if "message" not in out and result.get("room_name"):
            out["message"] = f"OK: {result.get('room_name')}"
        return out
    out: Dict = {
        "error": result.get("error") or result.get("error_code") or "failed",
    }
    if result.get("error_code"):
        out["error_code"] = result["error_code"]
    for key in ("expected_room", "actual_room", "hwnd", "results"):
        if key in result:
            out[key] = result[key]
    return out


@app.tool()
def kakao_health_check() -> Dict:
    """Check if KakaoTalk PC is currently running.
    Returns status, window handle, and process ID."""
    try:
        result = _svc().health()
        if result.get("kakaotalk_running"):
            return {
                "message": "KakaoTalk is running",
                "running": True,
                "pid": result.get("pid"),
            }
        return {
            "message": "KakaoTalk is not running",
            "running": False,
            "error_code": result.get("error_code"),
        }
    except Exception as e:
        return {"error": f"Health check failed: {e}"}


@app.tool()
def kakao_list_open_rooms() -> Dict:
    """List all currently open KakaoTalk chat room windows.
    Returns a list of open chat rooms with their window titles."""
    try:
        result = _svc().list_rooms()
        if not result.get("success"):
            return _mcp_from_service(result)
        rooms = result.get("rooms", [])
        return {
            "message": f"Found {len(rooms)} open chat room(s)",
            "rooms": rooms,
        }
    except Exception as e:
        return {"error": f"Failed to list rooms: {e}"}


@app.tool()
def kakao_open_room(room_name: str) -> Dict:
    """Open or bring to front a KakaoTalk chat room by name.
    Requires exact window title match after open.

    Args:
        room_name: The name of the chat room or person to open.
    """
    try:
        result = _svc().open_room(room_name)
        return _mcp_from_service(result)
    except Exception as e:
        return {"error": f"Failed to open room '{room_name}': {e}"}


@app.tool()
def kakao_send_message(room_name: str, message: str) -> Dict:
    """Send a text message to a KakaoTalk chat room.
    Strict-opens the room first (exact title required).

    Args:
        room_name: Exact title of the chat room window.
        message: The text message to send.
    """
    try:
        result = _svc().send_message(room_name, message)
        return _mcp_from_service(result)
    except Exception as e:
        return {"error": f"Failed to send message: {e}"}


@app.tool()
def kakao_send_bulk(room_names: list[str], message: str, interval_sec: float = 0.5) -> Dict:
    """Send the same message to multiple KakaoTalk chat rooms at once.
    Opens each room with strict matching and sends sequentially.

    Args:
        room_names: List of chat room names or person names to send to.
        message: The text message to send to all rooms.
        interval_sec: Seconds to wait between rooms (default 0.5, minimum 0.3).
    """
    try:
        if not room_names:
            return {"error": "room_names cannot be empty"}
        if not message.strip():
            return {"error": "Message cannot be empty"}
        interval_sec = max(0.3, interval_sec)
        results = []
        svc = _svc()
        for i, room_name in enumerate(room_names):
            send_result = svc.send_message(room_name, message)
            results.append({
                "room": room_name,
                "success": bool(send_result.get("success")),
                "detail": send_result.get("message")
                or send_result.get("error")
                or send_result.get("error_code"),
            })
            if i < len(room_names) - 1:
                time.sleep(interval_sec)
        sent_count = sum(1 for r in results if r["success"])
        return {
            "message": f"Sent to {sent_count}/{len(room_names)} room(s)",
            "results": results,
        }
    except Exception as e:
        return {"error": f"Failed to send bulk messages: {e}"}


@app.tool()
def kakao_send_image(room_name: str, image_paths: list[str]) -> Dict:
    """Send image file(s) to a KakaoTalk chat room.
    Strict-opens the room first. MCP does not enforce HTTP file root.

    Args:
        room_name: Exact title of the chat room window.
        image_paths: List of absolute file paths to images (JPG, PNG, GIF, BMP, WebP).
    """
    try:
        if not image_paths:
            return {"error": "image_paths cannot be empty"}

        for path in image_paths:
            if not os.path.isfile(os.path.abspath(path)):
                return {"error": f"Image file not found: {path}"}

        open_result = _svc().open_room(room_name)
        if not open_result.get("success"):
            return _mcp_from_service(open_result)

        if len(image_paths) == 1:
            result = controller.send_image_to_room(room_name, image_paths[0])
            if result["success"]:
                return {"message": result["message"]}
            return {"error": result["error"], "error_code": ErrorCode.IMAGE_SEND_FAILED}
        result = controller.send_images_to_room(room_name, image_paths)
        if result["success"]:
            return {"message": result["message"], "results": result["results"]}
        return {
            "error": result.get("message", "Failed to send images"),
            "results": result.get("results", []),
            "error_code": ErrorCode.IMAGE_SEND_FAILED,
        }
    except Exception as e:
        return {"error": f"Failed to send image: {e}"}


@app.tool()
def kakao_read_messages(room_name: str, max_messages: int = 50) -> Dict:
    """Read recent messages from a KakaoTalk chat room.
    Uses clipboard-based reading (Ctrl+A, Ctrl+C on the chat list).
    NOTE: This briefly brings the chat window to the foreground.

    Args:
        room_name: Exact title of the chat room window.
        max_messages: Maximum number of recent messages to return (default 50).
    """
    try:
        def _read():
            result = controller.read_chat_messages(room_name)
            if not result["success"]:
                return {"success": False, "error": result["error"]}
            parsed = parser.parse_chat_text(result["raw_text"])
            messages = parsed["messages"]
            if len(messages) > max_messages:
                messages = messages[-max_messages:]
            return {
                "success": True,
                "message": f"Read {len(messages)} messages from '{room_name}'",
                "room_name": parsed["room_name"],
                "member_count": parsed["member_count"],
                "messages": messages,
            }

        result = _svc()._submit(_read)
        return _mcp_from_service(result) if not result.get("success") else {
            k: v for k, v in result.items() if k != "success"
        }
    except Exception as e:
        return {"error": f"Failed to read messages: {e}"}


@app.tool()
def kakao_extract_links(room_name: str) -> Dict:
    """Extract all URLs/links from messages in a KakaoTalk chat room.
    Reads the chat first, then extracts URLs from all messages.

    Args:
        room_name: Exact title of the chat room window.
    """
    try:
        def _extract():
            result = controller.read_chat_messages(room_name)
            if not result["success"]:
                return {"success": False, "error": result["error"]}
            parsed = parser.parse_chat_text(result["raw_text"])
            urls = parser.extract_urls_from_messages(parsed["messages"])
            return {
                "success": True,
                "message": f"Found {len(urls)} URL(s) in '{room_name}'",
                "links": urls,
            }

        result = _svc()._submit(_extract)
        if not result.get("success"):
            return _mcp_from_service(result)
        return {k: v for k, v in result.items() if k != "success"}
    except Exception as e:
        return {"error": f"Failed to extract links: {e}"}


@app.tool()
def kakao_send_mention(room_name: str, mention_name: str, message: str) -> Dict:
    """Send a message with @mention to a KakaoTalk chat room.
    Types '@' to activate the mention popup, selects the target user,
    then sends the message. The chat room window must already be open.
    NOTE: This briefly brings the chat window to the foreground.

    Args:
        room_name: Exact title of the chat room window.
        mention_name: Display name of the person to mention (e.g. '홍길동').
        message: The text message to send after the mention.
    """
    try:
        if not mention_name.strip():
            return {"error": "Mention name cannot be empty"}
        if not message.strip():
            return {"error": "Message cannot be empty"}

        def _mention():
            open_result = controller.open_room_strict(room_name)
            if not open_result.get("success"):
                return open_result
            result = controller.send_mention_message(room_name, mention_name, message)
            if result["success"]:
                return {"success": True, "message": result["message"]}
            return {"success": False, "error": result["error"]}

        result = _svc()._submit(_mention)
        return _mcp_from_service(result)
    except Exception as e:
        return {"error": f"Failed to send mention message: {e}"}


@app.tool()
def kakao_download_images(
    room_name: str,
    output_dir: Optional[str] = None,
    max_images: int = 10,
) -> Dict:
    """Download recent images from KakaoTalk's local cache.
    Images are sorted by modification time (newest first).
    Note: Cache is global, not per-room — images are the most recently cached ones.

    Args:
        room_name: Chat room name (for context/logging).
        output_dir: Directory to save images. Defaults to Documents/KakaoMCP_Images.
        max_images: Maximum number of images to download (default 10).
    """
    try:
        if output_dir is None:
            output_dir = config.DEFAULT_IMAGE_OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)
        result = controller.download_recent_images(room_name, output_dir, max_images)
        return result
    except Exception as e:
        return {"error": f"Failed to download images: {e}"}


@app.tool()
def kakao_start_monitor(
    room_name: str,
    keywords: list[str],
    poll_interval_sec: float = 5.0,
) -> Dict:
    """Start monitoring a chat room for keywords.

    Disabled in v1 while the HTTP agent is the primary entrypoint — concurrent
    UI polling would race with send jobs.
    """
    return {
        "error": "Chat monitor is disabled in this agent build",
        "error_code": ErrorCode.MONITOR_DISABLED,
    }


@app.tool()
def kakao_stop_monitor() -> Dict:
    """Stop the running chat room monitor."""
    return {
        "error": "Chat monitor is disabled in this agent build",
        "error_code": ErrorCode.MONITOR_DISABLED,
    }


@app.tool()
def kakao_get_monitor_events() -> Dict:
    """Get pending keyword match events from the chat monitor."""
    return {
        "error": "Chat monitor is disabled in this agent build",
        "error_code": ErrorCode.MONITOR_DISABLED,
        "monitoring": False,
        "event_count": 0,
        "events": [],
    }


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
