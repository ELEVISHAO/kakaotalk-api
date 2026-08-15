# Kakao Agent HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI HTTP agent (`kakaotalk-api`) on top of the existing Win32 KakaoTalk controller, with shared `KakaoService`, strict room matching, serial UI jobs, API key + IP allowlist, path/upload file send — without breaking MCP entrypoints.

**Architecture:** FastAPI and MCP both call `KakaoService` → `JobManager` (single worker thread) → `controller.py`. Business failures return HTTP 200 + `success: false`; auth failures 401/403. Never claim `delivered`.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, pywin32, pytest, existing `kakao_mcp` package.

**Spec:** `docs/superpowers/specs/2026-08-13-kakao-agent-http-api-design.md`

## Global Constraints

- Platform: Windows 10/11 only for live KakaoTalk; unit tests mock Win32.
- Never return a `delivered` field.
- Exact room title match only (Unicode NFC normalize before compare); no substring / any-window success.
- Do not rewrite CF_DIB image pipeline, message send, window discovery, mention, parser.
- HTTP binds default `127.0.0.1:8765`; refuse start without `KAKAO_AGENT_API_KEY`; non-loopback host requires `KAKAO_AGENT_ALLOW_IPS`.
- File path allowlist applies to HTTP only, not MCP.
- Do not close chat windows after send (v1).
- Production primary path: `POST /send/materials/upload`; JSON path endpoints kept for local testing.
- Commit after each task; do not push unless asked.

---

## File map

| File | Responsibility |
|------|----------------|
| `src/kakao_mcp/config.py` | Existing Win32 constants + agent env helpers |
| `src/kakao_mcp/schemas.py` | Error codes, request/response TypedDicts / Pydantic |
| `src/kakao_mcp/job_manager.py` | Global queue + single worker; wait vs exec timeout |
| `src/kakao_mcp/service.py` | Business orchestration, path checks, upload save, logging |
| `src/kakao_mcp/api.py` | FastAPI app, auth middleware, routes, `main()` |
| `src/kakao_mcp/controller.py` | Add `open_room_strict`, CF_HDROP send; remove fuzzy success |
| `src/kakao_mcp/server.py` | MCP tools → KakaoService; disable monitor |
| `pyproject.toml` / `requirements.txt` | fastapi, uvicorn, `kakaotalk-api` script |
| `tests/test_*.py` | Layered unit tests with mocks |
| `README.md` | Deploy / curl / security |

---

### Task 1: Agent config + error schemas

**Files:**
- Modify: `src/kakao_mcp/config.py`
- Create: `src/kakao_mcp/schemas.py`
- Modify: `pyproject.toml`, `requirements.txt`
- Test: `tests/test_config_agent.py`

**Interfaces:**
- Produces: `load_agent_settings() -> AgentSettings`, constants `ErrorCode`, helpers `normalize_room_title(s: str) -> str`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml` dependencies add:

```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.32.0",
"python-multipart>=0.0.12",
```

In `requirements.txt` add the same three lines. Add script:

```toml
kakaotalk-api = "kakao_mcp.api:main"
```

- [ ] **Step 2: Write failing tests for settings**

```python
# tests/test_config_agent.py
import os
import pytest
from kakao_mcp import config

def test_load_settings_requires_api_key(monkeypatch):
    monkeypatch.delenv("KAKAO_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("KAKAO_AGENT_HOST", "127.0.0.1")
    with pytest.raises(RuntimeError, match="KAKAO_AGENT_API_KEY"):
        config.load_agent_settings()

def test_non_loopback_requires_allow_ips(monkeypatch):
    monkeypatch.setenv("KAKAO_AGENT_API_KEY", "secret")
    monkeypatch.setenv("KAKAO_AGENT_HOST", "0.0.0.0")
    monkeypatch.delenv("KAKAO_AGENT_ALLOW_IPS", raising=False)
    with pytest.raises(RuntimeError, match="KAKAO_AGENT_ALLOW_IPS"):
        config.load_agent_settings()

def test_loopback_allow_ips_optional(monkeypatch):
    monkeypatch.setenv("KAKAO_AGENT_API_KEY", "secret")
    monkeypatch.setenv("KAKAO_AGENT_HOST", "127.0.0.1")
    monkeypatch.delenv("KAKAO_AGENT_ALLOW_IPS", raising=False)
    s = config.load_agent_settings()
    assert s.api_key == "secret"
    assert s.allow_ips == []
    assert s.port == 8765
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest tests/test_config_agent.py -v
```

Expected: `load_agent_settings` missing.

- [ ] **Step 4: Implement config + schemas**

Append to `config.py` (keep all existing constants):

```python
from dataclasses import dataclass
import unicodedata

@dataclass(frozen=True)
class AgentSettings:
    api_key: str
    host: str
    port: int
    allow_ips: list[str]
    allowed_file_root: str
    max_file_size_mb: int
    job_wait_timeout_sec: float
    job_exec_timeout_sec: float
    log_message_body: bool

def _parse_allow_ips(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]

def _is_loopback_host(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")

def load_agent_settings() -> AgentSettings:
    api_key = os.environ.get("KAKAO_AGENT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("KAKAO_AGENT_API_KEY is required to start kakaotalk-api")
    host = os.environ.get("KAKAO_AGENT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("KAKAO_AGENT_PORT", "8765"))
    allow_ips = _parse_allow_ips(os.environ.get("KAKAO_AGENT_ALLOW_IPS"))
    if not _is_loopback_host(host) and not allow_ips:
        raise RuntimeError("KAKAO_AGENT_ALLOW_IPS is required when host is not loopback")
    wait = os.environ.get("KAKAO_JOB_WAIT_TIMEOUT_SEC") or os.environ.get("KAKAO_JOB_TIMEOUT_SEC") or "60"
    return AgentSettings(
        api_key=api_key,
        host=host,
        port=port,
        allow_ips=allow_ips,
        allowed_file_root=os.environ.get("KAKAO_ALLOWED_FILE_ROOT", r"C:\KakaoAgent\jobs"),
        max_file_size_mb=int(os.environ.get("KAKAO_MAX_FILE_SIZE_MB", "100")),
        job_wait_timeout_sec=float(wait),
        job_exec_timeout_sec=float(os.environ.get("KAKAO_JOB_EXEC_TIMEOUT_SEC", "300")),
        log_message_body=os.environ.get("KAKAO_LOG_MESSAGE_BODY", "").strip() in ("1", "true", "TRUE"),
    )

def normalize_room_title(value: str) -> str:
    return unicodedata.normalize("NFC", value)
```

Create `schemas.py` with string constants for every error code in the spec (`KAKAOTALK_NOT_RUNNING`, `ROOM_NOT_FOUND`, `ROOM_MISMATCH`, … `INTERNAL_ERROR`) and Pydantic models:

```python
from pydantic import BaseModel, Field

class RoomOpenRequest(BaseModel):
    room_name: str

class SendMessageRequest(BaseModel):
    room_name: str
    message: str

class SendImageRequest(BaseModel):
    room_name: str
    image_path: str

class SendFileRequest(BaseModel):
    room_name: str
    file_path: str

class SendFilesRequest(BaseModel):
    room_name: str
    file_paths: list[str]

class SendMaterialsRequest(BaseModel):
    room_name: str
    job_id: str
    message: str = ""
    files: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest tests/test_config_agent.py -v
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt src/kakao_mcp/config.py src/kakao_mcp/schemas.py tests/test_config_agent.py
git commit -m "Add agent settings, schemas, and HTTP dependencies."
```

---

### Task 2: JobManager (serial UI queue)

**Files:**
- Create: `src/kakao_mcp/job_manager.py`
- Test: `tests/test_job_manager.py`

**Interfaces:**
- Produces: `class JobManager` with `submit(fn, *args, **kwargs) -> Any`, `start()`, `stop()`; module singleton `get_job_manager() -> JobManager`
- Raises / returns: on wait timeout, raise `JobWaitTimeout` (service maps to `AUTOMATION_BUSY`)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_job_manager.py
import threading
import time
from kakao_mcp.job_manager import JobManager, JobWaitTimeout

def test_jobs_do_not_interleave():
    mgr = JobManager(wait_timeout_sec=5, exec_timeout_sec=30)
    mgr.start()
    order = []
    lock = threading.Lock()

    def job(name, delay):
        with lock:
            order.append(f"start-{name}")
        time.sleep(delay)
        with lock:
            order.append(f"end-{name}")
        return name

    t1 = threading.Thread(target=lambda: mgr.submit(job, "A", 0.2))
    t2 = threading.Thread(target=lambda: mgr.submit(job, "B", 0.05))
    t1.start(); t2.start(); t1.join(); t2.join()
    mgr.stop()
    # A must fully finish before B starts (or vice versa — serial, no overlap)
    assert order in (
        ["start-A", "end-A", "start-B", "end-B"],
        ["start-B", "end-B", "start-A", "end-A"],
    ) or (
        order.index("end-A") < order.index("start-B")
        or order.index("end-B") < order.index("start-A")
    )

def test_wait_timeout_when_worker_busy():
    mgr = JobManager(wait_timeout_sec=0.2, exec_timeout_sec=30)
    mgr.start()
    barrier = threading.Event()

    def blocker():
        barrier.wait(timeout=2)
        return "ok"

    threading.Thread(target=lambda: mgr.submit(blocker)).start()
    time.sleep(0.05)  # ensure blocker is running
    try:
        with pytest.raises(JobWaitTimeout):
            mgr.submit(lambda: "second", wait_timeout_sec=0.15)
    finally:
        barrier.set()
        mgr.stop()
```

(Add `import pytest`.)

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_job_manager.py -v
```

- [ ] **Step 3: Implement JobManager**

```python
# src/kakao_mcp/job_manager.py
import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable, Optional

class JobWaitTimeout(Exception):
    pass

class JobManager:
    def __init__(self, wait_timeout_sec: float = 60.0, exec_timeout_sec: float = 300.0):
        self.wait_timeout_sec = wait_timeout_sec
        self.exec_timeout_sec = exec_timeout_sec
        self._q: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Event()  # set while a job runs

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="kakao-ui-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=timeout)

    def submit(self, fn: Callable[..., Any], *args, wait_timeout_sec: Optional[float] = None, **kwargs) -> Any:
        fut: Future = Future()
        wait = self.wait_timeout_sec if wait_timeout_sec is None else wait_timeout_sec
        self._q.put((fut, fn, args, kwargs))
        try:
            return fut.result(timeout=wait)
        except TimeoutError as e:
            # Only treat as wait timeout if work never started.
            if not fut.running() and not fut.done():
                # Best-effort: if still queued, mark cancelled view for caller
                raise JobWaitTimeout("automation queue wait timed out") from e
            # Started: wait until complete without the short wait timeout
            return fut.result(timeout=self.exec_timeout_sec)

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            fut, fn, args, kwargs = item
            if fut.set_running_or_notify_cancel():
                self._busy.set()
                try:
                    fut.set_result(fn(*args, **kwargs))
                except Exception as e:
                    fut.set_exception(e)
                finally:
                    self._busy.clear()

_manager: Optional[JobManager] = None
_manager_lock = threading.Lock()

def get_job_manager(wait_timeout_sec: float = 60.0, exec_timeout_sec: float = 300.0) -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager(wait_timeout_sec, exec_timeout_sec)
            _manager.start()
        return _manager
```

Refine `submit` so wait timeout only applies while waiting for the future to **start**. Practical approach:

1. Put job on queue with a `started` Event set by worker before calling `fn`.
2. Caller waits on `started.wait(timeout=wait)`; if not started → `JobWaitTimeout` and attempt to remove/mark skipped if still queued.
3. Then `fut.result(timeout=exec_timeout_sec)` for the running job.

Implement the Event-based wait carefully so a timed-out waiter does not steal a later result.

- [ ] **Step 4: Run — expect PASS**

```bash
pytest tests/test_job_manager.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/kakao_mcp/job_manager.py tests/test_job_manager.py
git commit -m "Add serial JobManager for KakaoTalk UI automation."
```

---

### Task 3: Strict open_room in controller

**Files:**
- Modify: `src/kakao_mcp/controller.py` (`search_and_open_room`, add `open_room_strict`)
- Test: `tests/test_open_room_strict.py`

**Interfaces:**
- Produces: `open_room_strict(room_name: str) -> dict` with keys `success`, optional `hwnd`, `error_code`, `expected_room`, `actual_room`, `error`
- Modifies: `search_and_open_room` to return failure (not success) on non-exact match; prefer having `open_room_strict` own the public contract and make `search_and_open_room` call into shared search UI without fuzzy success

- [ ] **Step 1: Write failing tests**

```python
# tests/test_open_room_strict.py
from unittest.mock import patch
from kakao_mcp import controller

@patch("kakao_mcp.controller.is_kakaotalk_running", return_value={"running": True, "hwnd": 1, "pid": 2})
@patch("kakao_mcp.controller.find_chat_window", return_value=111)
def test_already_open_exact(mock_find, mock_run):
    r = controller.open_room_strict("한패스 고객센터")
    assert r["success"] is True
    assert r["hwnd"] == 111

@patch("kakao_mcp.controller.is_kakaotalk_running", return_value={"running": True, "hwnd": 1, "pid": 2})
@patch("kakao_mcp.controller.find_chat_window", side_effect=[None, None])
@patch("kakao_mcp.controller._search_open_first_result")  # extract search UI without success policy
@patch("kakao_mcp.controller.list_chat_windows", return_value=[{"title": "한패스", "hwnd": 222}])
def test_mismatch(mock_list, mock_search, mock_find, mock_run):
    r = controller.open_room_strict("한패스 고객센터")
    assert r["success"] is False
    assert r["error_code"] == "ROOM_MISMATCH"
    assert r["actual_room"] == "한패스"

@patch("kakao_mcp.controller.search_and_open_room")
def test_search_and_open_no_any_window_fallback(mock_search):
    # After refactor, calling legacy helper must not return success for unrelated window
    ...
```

Also add a direct test that the old fallback code paths are gone: after search, if only wrong titles exist → not `success: True`.

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_open_room_strict.py -v
```

- [ ] **Step 3: Implement**

1. Import `normalize_room_title` from config.
2. Extract search keystrokes into `_search_open_first_result(room_name) -> None` (no success policy).
3. Rewrite end of `search_and_open_room` / implement `open_room_strict`:

```python
def open_room_strict(room_name: str) -> dict:
    expected = normalize_room_title(room_name)
    status = is_kakaotalk_running()
    if not status["running"]:
        return {"success": False, "error_code": "KAKAOTALK_NOT_RUNNING",
                "error": "KakaoTalk is not running", "expected_room": room_name}

    hwnd = find_chat_window(expected)  # find_chat_window must compare NFC titles
    if hwnd:
        bring_window_to_front(hwnd)
        return {"success": True, "hwnd": hwnd, "room_name": room_name}

    before = {w["hwnd"] for w in list_chat_windows()}
    _search_open_first_result(room_name)
    # Prefer exact match among all windows
    hwnd = find_chat_window(expected)
    if hwnd:
        return {"success": True, "hwnd": hwnd, "room_name": room_name}

    after = list_chat_windows()
    new = [w for w in after if w["hwnd"] not in before]
    if new:
        actual = new[0]["title"]
        return {
            "success": False,
            "error_code": "ROOM_MISMATCH",
            "expected_room": room_name,
            "actual_room": actual,
            "error": f"Opened '{actual}' but expected '{room_name}'",
        }
    return {
        "success": False,
        "error_code": "ROOM_NOT_FOUND",
        "expected_room": room_name,
        "error": f"Chat room '{room_name}' not found after search",
    }
```

Update `find_chat_window` to compare `normalize_room_title(title) == normalize_room_title(room_name)`.

Remove the substring and any-window success branches from `search_and_open_room` (make it delegate to `open_room_strict` or share the same failure policy).

- [ ] **Step 4: Run all controller/open tests**

```bash
pytest tests/test_open_room_strict.py tests/test_controller.py -v
```

Expected: PASS (fix any mocks broken by signature changes).

- [ ] **Step 5: Commit**

```bash
git add src/kakao_mcp/controller.py tests/test_open_room_strict.py
git commit -m "Add open_room_strict and remove fuzzy room-open fallbacks."
```

---

### Task 4: KakaoService core (health, rooms, open, send message)

**Files:**
- Create: `src/kakao_mcp/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Produces: `class KakaoService` methods:
  - `health() -> dict`
  - `list_rooms() -> dict`
  - `open_room(room_name: str) -> dict`  # queued
  - `send_message(room_name: str, message: str) -> dict`  # queued; empty message → INVALID_REQUEST
- Uses: `JobManager`, `controller`, `schemas` error codes
- HTTP path validation helpers stubbed later; message send must call `open_room_strict` then `send_message_to_room`

- [ ] **Step 1: Write failing service tests (mock controller + inline job manager)**

```python
def test_send_message_requires_non_empty():
    svc = KakaoService(controller=fake, job_manager=passthrough_mgr, enforce_file_root=True)
    r = svc.send_message("Room", "   ")
    assert r["success"] is False
    assert r["error_code"] == "INVALID_REQUEST"

def test_send_message_opens_then_sends():
    fake.open_room_strict.return_value = {"success": True, "hwnd": 1}
    fake.send_message_to_room.return_value = {"success": True, "message": "ok"}
    r = svc.send_message("Room", "hi")
    assert r["success"] is True
    assert r["automation_success"] is True
    assert r["verification"] == "UI_ACTION_COMPLETED"
    assert "delivered" not in r
```

- [ ] **Step 2: Implement minimal KakaoService**

Map `JobWaitTimeout` → `{success: False, error_code: "AUTOMATION_BUSY", ...}`.

Queue `open_room` / `send_message` via `job_manager.submit`.

Do not queue `health` / `list_rooms`.

- [ ] **Step 3: Tests PASS + commit**

```bash
pytest tests/test_service.py -v
git add src/kakao_mcp/service.py tests/test_service.py
git commit -m "Add KakaoService for health, rooms, open, and send message."
```

---

### Task 5: FastAPI app — auth, health, rooms, open, send/message

**Files:**
- Create: `src/kakao_mcp/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `create_app(settings, service) -> FastAPI`, `main()`
- Auth: dependency checking client IP then `X-API-Key`
- Routes: `GET /health`, `GET /rooms`, `POST /rooms/open`, `POST /send/message`

- [ ] **Step 1: Failing API tests with TestClient**

```python
from fastapi.testclient import TestClient

def test_missing_api_key_401(client):
    r = client.get("/health")
    assert r.status_code == 401
    assert r.json()["error_code"] == "INVALID_API_KEY"

def test_ip_not_allowed_403(client_with_allowlist):
    # TestClient uses client host override if available; set allow_ips=["10.0.0.1"]
    ...
    assert r.status_code == 403
    assert r.json()["error_code"] == "IP_NOT_ALLOWED"

def test_health_ok(authed_client, mock_service):
    mock_service.health.return_value = {"success": True, "kakaotalk_running": True, "pid": 1}
    r = authed_client.get("/health")
    assert r.status_code == 200
    assert r.json()["success"] is True
```

Normalize IPv4-mapped IPv6: if host starts with `::ffff:`, strip prefix before allowlist check.

- [ ] **Step 2: Implement `api.py`**

- Sync `def` routes.
- On missing settings at `main()`: call `load_agent_settings()` and exit with clear message on `RuntimeError`.
- `uvicorn.run(app, host=settings.host, port=settings.port)`.

- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_api.py -v
git add src/kakao_mcp/api.py tests/test_api.py
git commit -m "Add FastAPI agent with auth, health, rooms, and send message."
```

---

### Task 6: Wire MCP server through KakaoService

**Files:**
- Modify: `src/kakao_mcp/server.py`
- Test: `tests/test_mcp_service_wiring.py` (call tool functions directly with mocked service)

- [ ] **Step 1: Tests** — `kakao_start_monitor` returns error with `MONITOR_DISABLED`; `kakao_open_room` uses service and surfaces `ROOM_MISMATCH`.

- [ ] **Step 2: Refactor** each tool to call a module-level `get_service()`; monitor tools short-circuit.

- [ ] **Step 3: Keep MCP response shape** `{message}` / `{error}` plus `error_code` when failing.

- [ ] **Step 4: Commit**

```bash
git commit -m "Route MCP tools through KakaoService; disable monitor."
```

---

### Task 7: HTTP file path validation + send image/file/files

**Files:**
- Modify: `service.py`, `controller.py`, `api.py`, `schemas.py`
- Test: `tests/test_service_files.py`, extend `tests/test_api.py`, `tests/test_controller_file.py`

**Interfaces:**
- Produces: `validate_http_file_path(path, settings) -> dict` either ok with resolved path or error_code
- `controller.send_file_to_room(room_name, file_path) -> dict`
- `controller._copy_files_to_clipboard_hdrop(paths: list[str]) -> None` (single path for one paste)
- Extract `_wait_and_confirm_send_dialog(chat_hwnd) -> bool` from image send

- [ ] **Step 1: Tests for path traversal / outside root / missing / too large**

```python
def test_path_traversal_rejected(tmp_path, settings):
    root = tmp_path / "jobs"
    root.mkdir()
    r = validate_http_file_path(str(root / ".." / "secret.txt"), settings_with_root(root))
    assert r["success"] is False
    assert r["error_code"] == "FILE_PATH_NOT_ALLOWED"
```

- [ ] **Step 2: Implement CF_HDROP clipboard**

Build `DROPFILES` structure + double-null-terminated UTF-16LE path list; `SetClipboardData(CF_HDROP, ...)`.

Reuse image focus + Ctrl+V + confirm dialog helper.

- [ ] **Step 3: Service methods** `send_image`, `send_file`, `send_files` — always `open_room_strict` first; HTTP enforces root; stop at first file failure; mark rest `skipped: true`.

- [ ] **Step 4: API routes** `POST /send/image`, `/send/file`, `/send/files`.

- [ ] **Step 5: Commit**

```bash
git commit -m "Add HTTP file/image send with CF_HDROP and path allowlist."
```

---

### Task 8: Materials path + multipart upload

**Files:**
- Modify: `service.py`, `api.py`
- Test: `tests/test_service_materials.py`, `tests/test_api_upload.py`

**Interfaces:**
- `send_materials(room_name, job_id, message, files: list[str]) -> dict`
- `save_upload_files(job_id, uploads) -> list[Path]` then `send_materials(...)`
- `job_id` regex: `^[A-Za-z0-9_-]{1,64}$` else `INVALID_JOB_ID`
- Upload filenames: `Path(name).name` only

- [ ] **Step 1: Tests** — empty message+files → `INVALID_REQUEST`; partial file failure shape; illegal job_id; upload saves under `root/job_id/`.

- [ ] **Step 2: Implement** one queued job for the whole materials send (message + all files). Upload disk write may happen before queue; open+send must be one job.

- [ ] **Step 3: Route** `POST /send/materials` (JSON) and `POST /send/materials/upload` (multipart).

- [ ] **Step 4: Commit**

```bash
git commit -m "Add send/materials path and multipart upload endpoints."
```

---

### Task 9: JobManager hardening tests + exec timeout checkpoints

**Files:**
- Modify: `job_manager.py`, `service.py` (check elapsed between files)
- Test: extend `tests/test_job_manager.py`

- [ ] **Step 1: Test** wait timeout does not cancel an already-running long job’s side effects (use shared list: long job appends after sleep; waiter times out; long job still completes append).

- [ ] **Step 2: Test** materials submitted as one job is not interleaved with another open_room.

- [ ] **Step 3: Between files in `send_files` / `send_materials`, if exec deadline passed → stop with `JOB_EXEC_TIMEOUT` / partial results.

- [ ] **Step 4: Commit**

```bash
git commit -m "Harden job wait/exec timeout behavior for materials sends."
```

---

### Task 10: Logging + README

**Files:**
- Modify: `service.py` (structured log lines), `README.md`

- [ ] **Step 1: Add send logging** — timestamp, job_id, room_name, message_sent, file_count, basenames, success, error_code, duration, message_length, message_hash (sha256 of UTF-8); body only if `log_message_body`.

- [ ] **Step 2: Rewrite README sections** per spec §15: install, `kakaotalk-api`, env table, local vs production, curl for `/send/materials/upload`, firewall, Task Scheduler, no public port forward, CF_HDROP live verify note, job dir cleanup.

- [ ] **Step 3: Update CHANGELOG** under Unreleased.

- [ ] **Step 4: Full test suite**

```bash
pytest -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "Document HTTP agent deployment and add redacted send logging."
```

---

## Spec coverage checklist

| Spec area | Task |
|-----------|------|
| Agent env + refuse start | 1 |
| JobManager serial queue | 2, 9 |
| open_room_strict / no fuzzy | 3 |
| Service + send message | 4 |
| FastAPI + API key + IP allowlist | 5 |
| MCP via service, monitor disabled | 6 |
| CF_HDROP + path allowlist + image | 7 |
| materials + upload | 8 |
| wait vs exec timeout | 2, 9 |
| Logging + README | 10 |
| No close-after-send | constraint (no task adds close) |
| No `delivered` | 4, 7, 8 asserts |

## Placeholder / consistency notes for implementers

- Prefer one module-level `KakaoService` factory used by both `api.py` and `server.py`.
- MCP must **not** call `validate_http_file_path`.
- `send_bulk_messages` in controller should be updated to use `open_room_strict` when Task 6 wires MCP bulk through service (service method `send_bulk`).

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-08-15-kakao-agent-http-api.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
