# Windows KakaoTalk Automation Agent — HTTP API Design

Date: 2026-08-13  
Status: Approved for spec review  
Source: fork of `kronenz/kakaotalk-mcp`  
Branch intent: keep MCP, add a local HTTP agent for business systems

## 1. Goal

Turn this MCP-only KakaoTalk Win32 automation project into a Windows local agent that Django, Celery, n8n, and other servers can call over HTTP.

Production must not require Claude, Cursor, an LLM, or an MCP client. MCP remains an extra interface.

Actual sending still uses KakaoTalk PC + Win32 / UI Automation. No Kakao private protocol, no reverse engineering, no Partner whitelist. The business system passes `room_name`. Room title must match exactly before any send.

```text
Business Server / Django
        ↓ HTTP
Windows Kakao Agent (FastAPI)
        ↓
KakaoService
        ↓
JobManager (single worker)
        ↓
controller.py
        ↓
Win32 API
        ↓
KakaoTalk PC → exact chat room / channel
```

## 2. Decisions

| Topic | Choice |
|-------|--------|
| Architecture | Thin controller + shared `KakaoService` + single-worker queue |
| MCP vs HTTP | Same `KakaoService` / `open_room_strict` path |
| MCP send tools | Also strict-open before send |
| Business HTTP status | Always 200; inspect `success` + `error_code` |
| Auth HTTP status | 401 for missing/wrong API key |
| Uncaught errors | 500 + `INTERNAL_ERROR` |
| Request validation | 422 (FastAPI default) |
| `/health` auth | Requires `X-API-Key` |
| MCP monitor | Disabled in v1 (`MONITOR_DISABLED`) |
| Concurrency | Queue and wait; timeout then `AUTOMATION_BUSY` |
| Job timeout | 60 seconds default, env-configurable |
| Multi-file failure | Stop at first failure; remaining files skipped |
| File paste | CF_HDROP first; no coordinate clicking |
| Image paste | Keep existing CF_DIB path |
| Delivery claims | Never return `delivered` |
| Package name | Keep `kakaotalk-mcp`; add `kakaotalk-api` entry point |

## 3. Non-goals (v1)

- Rewriting working Win32 code in `controller.py`
- Kakao protocol / Partner API
- Claiming server-side delivery
- Complex Windows installer
- Re-enabling MCP chat monitor
- Fallback file send via fixed screen coordinates
- Auto-fallback from CF_HDROP to file-button / drag-drop (document for later if CF_HDROP fails on a KakaoTalk version)

## 4. Architecture

```text
Django / Celery / n8n / MCP Client
        │
        ├─ HTTP  kakaotalk-api   (FastAPI, 127.0.0.1:8765)
        └─ stdio kakaotalk-mcp   (FastMCP, kept)
                │
                ▼
          KakaoService           ← only business entry
                │
          JobManager             ← one worker thread
                │
          controller.py          ← Win32, reuse as-is
                │
          KakaoTalk PC
```

| Layer | Does | Does not |
|-------|------|----------|
| `api.py` | HTTP, API key, Pydantic models | Win32 |
| `server.py` | MCP tool adapters | Call controller directly |
| `service.py` | Running check, strict open, path allowlist, send orchestration, error codes, logging | `keybd_event` |
| `job_manager.py` | Global serial UI jobs, wait timeout | KakaoTalk details |
| `controller.py` | Windows/clipboard/send actions | Fuzzy success, HTTP |
| `schemas.py` | Request/response models and error codes | Business logic |
| `config.py` | Env + existing Win32 constants | |

Entry points:

- `kakaotalk-mcp` / `python -m kakao_mcp` → MCP stdio (unchanged command)
- `kakaotalk-api` / `python -m kakao_mcp.api` → HTTP `http://127.0.0.1:8765`

Read-only, not queued: `GET /health`, `GET /rooms`.  
Queued: every `open` / `send*` (HTTP and MCP).

## 5. Files to add or change

Add:

- `src/kakao_mcp/api.py`
- `src/kakao_mcp/schemas.py`
- `src/kakao_mcp/service.py`
- `src/kakao_mcp/job_manager.py`
- `tests/test_api.py`
- `tests/test_service.py`
- `tests/test_job_manager.py`
- `tests/test_open_room_strict.py`

Change:

- `controller.py` — add `open_room_strict`, CF_HDROP send; remove fuzzy search success; extract confirm-dialog helper
- `server.py` — tools call `KakaoService`; disable monitor
- `config.py` — agent env vars
- `pyproject.toml` — `fastapi`, `uvicorn`, `kakaotalk-api` script
- `requirements.txt`, `README.md`

Do not rewrite: `parser.py`, image CF_DIB pipeline, mention, cache image download.

Do not rename the Python package.

## 6. Strict room matching

`KakaoService.open_room(room_name)` / `controller.open_room_strict(room_name)`:

1. KakaoTalk not running → `KAKAOTALK_NOT_RUNNING`, stop.
2. If `find_chat_window(room_name)` finds a window whose title equals `room_name` exactly → success (may bring to front; do not search).
3. Otherwise use the existing search UI (Ctrl+F, type, Enter).
4. Read the actual opened chat window title.
5. `actual_title == room_name` → success.
6. Otherwise → `ROOM_MISMATCH` with `expected_room` and `actual_room`. Stop. Do not send.

Matching is exact string equality. No trim, no case folding, no substring.

Remove these fallbacks from `search_and_open_room()` (and do not re-expose them):

- success if `room_name` is a substring of a window title
- success if any chat window is open

`search_and_open_room()` is not a public success path. MCP `kakao_open_room` and HTTP `POST /rooms/open` both call `open_room_strict` only.

Every send path (`send_message`, `send_image`, `send_file`, `send_files`, `send_materials`, including MCP send tools) must:

```text
KakaoTalk running
  → open_room_strict
  → verify title again even if already open
  → send only after both pass
  → stop on first failure
```

## 7. HTTP API

### 7.1 Bind address

- `KAKAO_AGENT_HOST` default `127.0.0.1`
- `KAKAO_AGENT_PORT` default `8765`
- Listen on all interfaces only when host is explicitly `0.0.0.0`

### 7.2 Auth

Every HTTP route, including `/health`, requires:

```http
X-API-Key: <KAKAO_AGENT_API_KEY>
```

Missing env, missing header, or wrong key → HTTP 401:

```json
{"success": false, "error_code": "INVALID_API_KEY", "error": "..."}
```

Never commit the key. Never log the key.

### 7.3 Status codes

| Case | HTTP |
|------|------|
| Business success or business failure | 200, use `success` + `error_code` |
| Missing/wrong API key | 401 |
| Invalid request body | 422 |
| Uncaught exception | 500 + `INTERNAL_ERROR` |

### 7.4 Endpoints

Phase 2:

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/health` | `is_kakaotalk_running()` |
| GET | `/rooms` | `list_chat_windows()` |
| POST | `/rooms/open` | `open_room_strict` |
| POST | `/send/message` | strict open → send text |

Phase 4–5:

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/send/image` | existing CF_DIB image send |
| POST | `/send/file` | CF_HDROP one file |
| POST | `/send/files` | sequential files, stop on first failure |
| POST | `/send/materials` | message + files, primary business path |

### 7.5 Response shapes

`GET /health` when running:

```json
{"success": true, "kakaotalk_running": true, "pid": 1234}
```

When not running (still HTTP 200):

```json
{
  "success": false,
  "kakaotalk_running": false,
  "error_code": "KAKAOTALK_NOT_RUNNING"
}
```

`GET /rooms`:

```json
{
  "success": true,
  "rooms": [{"title": "한패스 고객센터", "hwnd": 123456}]
}
```

`POST /rooms/open` body: `{"room_name": "..."}`.

`POST /send/message` success:

```json
{
  "success": true,
  "room_name": "한패스 고객센터",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

Never include `delivered`.

`POST /send/image` body: `{"room_name": "...", "image_path": "C:\\\\KakaoAgent\\\\jobs\\\\123\\\\passport.jpg"}`.

`POST /send/file` body: `{"room_name": "...", "file_path": "..."}`.

`POST /send/files` body: `{"room_name": "...", "file_paths": ["...", "..."]}`.  
File order must match the request. Response lists each file by basename.

`POST /send/materials` request:

```json
{
  "room_name": "한패스 고객센터",
  "job_id": "GM-123456",
  "message": "신규 개통 서류 전달드립니다.",
  "files": [
    "C:\\\\KakaoAgent\\\\jobs\\\\GM-123456\\\\passport.pdf",
    "C:\\\\KakaoAgent\\\\jobs\\\\GM-123456\\\\application.jpg"
  ]
}
```

Empty or whitespace-only `message`: skip text send, `message_sent: false`.  
Empty `files`: skip file sends.  
If both message and files are empty: HTTP 200, `success: false`, `error_code: "INVALID_REQUEST"`. Malformed JSON or wrong types remain FastAPI 422.

Success:

```json
{
  "success": true,
  "job_id": "GM-123456",
  "room_name": "한패스 고객센터",
  "message_sent": true,
  "files": [
    {"file": "passport.pdf", "success": true},
    {"file": "application.jpg", "success": true}
  ],
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

Partial failure (text sent, second file failed; later files not attempted):

```json
{
  "success": false,
  "job_id": "GM-123456",
  "room_name": "한패스 고객센터",
  "message_sent": true,
  "error_code": "FILE_SEND_FAILED",
  "completed_files": 1,
  "failed_file": "application.jpg",
  "files": [
    {"file": "passport.pdf", "success": true},
    {"file": "application.jpg", "success": false, "error_code": "FILE_SEND_FAILED"},
    {"file": "extra.zip", "success": false, "skipped": true}
  ]
}
```

Do not roll back already-sent text. Skipped files are not successes.

`ROOM_MISMATCH` extra fields: `expected_room`, `actual_room`.

### 7.6 Error codes

```text
KAKAOTALK_NOT_RUNNING
ROOM_NOT_FOUND
ROOM_MISMATCH
EDIT_CONTROL_NOT_FOUND
FILE_NOT_FOUND
FILE_PATH_NOT_ALLOWED
FILE_TOO_LARGE
FILE_SEND_FAILED
IMAGE_SEND_FAILED
MESSAGE_SEND_FAILED
INVALID_API_KEY
INVALID_REQUEST
AUTOMATION_BUSY
MONITOR_DISABLED
INTERNAL_ERROR
```

Common failure body:

```json
{"success": false, "error_code": "ROOM_MISMATCH", "error": "..."}
```

## 8. File sending

Images (`POST /send/image`): keep `_copy_image_to_clipboard` (PowerShell BMP → `CF_DIB`) + Ctrl+V + confirm dialog. Do not rewrite.

Attachments (`send_file_to_room` / `send_files_to_room`):

```text
validate path (allowlist, exists, regular file, size)
→ write CF_HDROP (DROPFILES + UTF-16 paths)
→ open_room_strict + title verify
→ AttachThreadInput + SetFocus on RICHEDIT50W (same as image; no dead coordinates)
→ Ctrl+V
→ poll foreground window change as confirm dialog
→ Enter
→ automation_success only
```

`/send/files` pastes one file per CF_HDROP, in request order. Do not drop multiple files in one paste.

A `.jpg` on `/send/image` is an image. The same `.jpg` on `/send/file` is a file attachment.

Extract confirm-dialog wait + Enter from `send_image_to_room` for reuse. If the dialog never appears → `IMAGE_SEND_FAILED` or `FILE_SEND_FAILED`.

v1 implements CF_HDROP only. If a KakaoTalk build rejects paste, return a real automation failure. Later options (not v1): KakaoTalk file button + system Open dialog, then `WM_DROPFILES`. Do not start with fixed click coordinates.

No extension allowlist. After path/size checks, try to send. If KakaoTalk rejects the format, return the real automation failure. README examples: `.pdf .xlsx .xls .doc .docx .txt .zip .jpg .jpeg .png`.

## 9. File security

- `KAKAO_ALLOWED_FILE_ROOT` default `C:\KakaoAgent\jobs`
- Resolve with `Path.resolve()`. The file must stay inside the root. Reject `..` traversal.
- Must exist and be a regular file.
- `KAKAO_MAX_FILE_SIZE_MB` default `100` (documented; aligned with common KakaoTalk PC attachment limits).
- Outside root → `FILE_PATH_NOT_ALLOWED`
- Missing → `FILE_NOT_FOUND`
- Too large → `FILE_TOO_LARGE`
- `/send/image` paths use the same root and size rules.

## 10. JobManager

Do not use `asyncio.Lock` as the only serialization. Controller is synchronous Win32.

```text
HTTP/MCP request
  → KakaoService method
  → JobManager.submit(fn)
  → single worker thread runs fn
  → Future returns to caller
```

- One process-wide `queue.Queue` and one worker thread.
- Only that thread calls controller UI functions.
- Caller waits `future.result(timeout=KAKAO_JOB_TIMEOUT_SEC)` default 60.
- Timeout → `AUTOMATION_BUSY`. Do not kill the in-flight worker job (avoids half-finished Ctrl+V).
- No tiny queue cap; timeout prevents HTTP threads from waiting forever.

Queued: open/send HTTP and MCP.  
Not queued: `/health`, `/rooms`.

`send_materials` is submitted as **one** job so its message and files cannot be interleaved with another request.

FastAPI routes are sync `def` so waiting happens in the thread pool, not on the event loop.

Required ordering:

```text
Wrong: Job A opens room A → Job B opens room B → Job A Ctrl+V
Right: Job A finishes open+verify+send → then Job B starts
```

## 11. Logging

Per send job log: timestamp, job_id, room_name, message_sent, file_count, file **basenames**, success, error_code, error, duration.

Do not log file contents.  
Do not log full message text by default; log `message_length` and `message_hash`.  
Log body only if `KAKAO_LOG_MESSAGE_BODY=1`.  
Never log the API key.

## 12. MCP compatibility

Keep `kakaotalk-mcp`, `python -m kakao_mcp`, tool names, and tool parameters.

Route tools through `KakaoService`:

| Tool | v1 behavior |
|------|-------------|
| `kakao_open_room` | Exact match only; mismatch fails |
| `kakao_send_message` / `kakao_send_image` / `kakao_send_bulk` | Strict open before send |
| `kakao_start_monitor` | Reject with `MONITOR_DISABLED` |
| `kakao_stop_monitor` / `kakao_get_monitor_events` | Reject the same way (monitor is not running) |
| read / mention / extract_links / download_images | Keep, but go through Service + JobManager so they cannot race HTTP sends |

MCP responses stay close to `{message}` / `{error}` and may include `error_code`. Do not force the full HTTP JSON envelope onto MCP clients.

## 13. Config / environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `KAKAO_AGENT_API_KEY` | (required for HTTP) | `X-API-Key` |
| `KAKAO_AGENT_HOST` | `127.0.0.1` | Bind address |
| `KAKAO_AGENT_PORT` | `8765` | Bind port |
| `KAKAO_ALLOWED_FILE_ROOT` | `C:\KakaoAgent\jobs` | Send path root |
| `KAKAO_MAX_FILE_SIZE_MB` | `100` | Max attachment/image size |
| `KAKAO_JOB_TIMEOUT_SEC` | `60` | Queue wait timeout |
| `KAKAO_LOG_MESSAGE_BODY` | unset/false | Log full message text |

If `KAKAO_AGENT_API_KEY` is unset or empty, `kakaotalk-api` refuses to start with a clear error. Do not bind a listening socket without a key.

## 14. Testing

Mock Win32 and real KakaoTalk in CI.

| Layer | Assert | Mock |
|-------|--------|------|
| API | Auth, 401, health, 422, error JSON | Service |
| Service | Exact match, mismatch stops send, traversal, missing file, too large, materials partial failure, skipped files | controller + JobManager (or run jobs inline) |
| JobManager | Jobs do not interleave; timeout → BUSY; materials not split | Slow fake functions |
| Controller | `open_room_strict` exact success / mismatch / no any-window success; file clipboard payload | win32gui / clipboard |

Minimum cases:

1. health
2. valid API key
3. invalid / missing API key
4. rooms
5. strict exact room match
6. room mismatch
7. dangerous fallback gone
8. file missing
9. file outside allow root
10. path traversal
11. send message
12. send image
13. send file
14. send files
15. send materials
16. partial file failure
17. global UI serial queue
18. controller mocks

Phase 2 covers 1–7, 11, auth, and a basic JobManager non-interleaving test. File cases come with Phase 4–5. Phase 6 expands queue/timeout tests. Keep existing `test_parser.py` and `test_controller.py`. Add MCP tests for open-room mismatch and disabled monitor.

## 15. README / deployment (Phase 8)

Document:

- Windows 10/11, user logged in, KakaoTalk PC logged in and running
- No Claude / Cursor / LLM / MCP client required in production
- No Kakao private protocol; no Partner code; pass `room_name`
- Install, env vars, curl examples including `/send/materials`
- Default bind `127.0.0.1`; `0.0.0.0` needs firewall, VPN, reverse proxy, HTTPS, API key
- Autostart via Task Scheduler “at user logon” for `kakaotalk-api`; no custom installer in v1
- UI action ≠ delivered; agent steals focus and clipboard
- Room name must equal the KakaoTalk window title exactly
- CF_HDROP file send needs a one-time live KakaoTalk verification on the target PC

## 16. Implementation phases

Do not land everything in one change. After this spec is accepted, write an implementation plan, then execute phase by phase.

**Phase 2 — HTTP baseline**  
`KakaoService` + FastAPI: `/health`, `/rooms`, `/rooms/open`, `/send/message`. API key. `kakaotalk-api` entry. Introduce `JobManager` here so open/send cannot interleave even before file sending exists. Tests for health, auth, rooms, send message (mock controller). Open already uses exact title; do not expose fuzzy search success over HTTP.

**Phase 3 — Strict room**  
`open_room_strict`. Delete substring / any-window success. Tests for exact match, mismatch, fallback gone. MCP open/send/bulk use the same path.

**Phase 4 — Files**  
CF_HDROP + confirm dialog. `/send/file`, `/send/files`, `/send/image` (image reuses CF_DIB). Path allowlist tests.

**Phase 5 — Materials**  
`/send/materials` with `job_id`, message, files, partial failure.

**Phase 6 — Queue hardening**  
JobManager already exists from Phase 2. This phase adds timeout/`AUTOMATION_BUSY` tests, materials-as-one-job non-interleaving tests, and any remaining race fixes.

**Phase 7 — Security / logging**  
File root, max size, redacted logs. Path checks should already exist from Phase 4; this phase finishes config and docs.

**Phase 8 — README**  
Install, run, Windows/KakaoTalk requirements, curl, security, Task Scheduler autostart.

Phase 2 produces a runnable `kakaotalk-api`. File send waits until Phase 4.

## 17. Risks

1. Search cannot guarantee the first KakaoTalk result is the target room. Only post-open exact title check is the safety gate.
2. Some KakaoTalk versions may ignore CF_HDROP paste. Return real failure; do not fake success.
3. UI automation proves a local send action, not Kakao server delivery.
4. Clipboard is global; sends overwrite the user clipboard.
5. Foreground stealing: the agent machine should not be a heavy daily desktop.
6. MCP monitor would race HTTP sends; v1 disables it.
7. MCP open/send behavior becomes stricter (intentional breaking change vs fuzzy success).
8. KakaoTalk may still reject size/format after our checks.

## 18. Controller change boundary

Allowed:

- Add `open_room_strict`
- Change search success to exact title only; return mismatch details
- Add `send_file_to_room` / `send_files_to_room`
- Extract confirm-dialog helper for image and file

Not allowed in this work:

- Rewrite window discovery, foreground, text send, CF_DIB image send, read messages, mention
- Reintroduce “any open chat window means success”
