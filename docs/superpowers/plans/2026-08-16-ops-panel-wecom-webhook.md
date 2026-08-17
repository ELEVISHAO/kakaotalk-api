# Ops Panel + WeCom Webhook Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** tkinter 运维面板（启停/配置/health）+ 失败时企业微信 markdown webhook。

**Architecture:** `agent.env` 落盘配置；面板子进程启动 API；API 中间件检测非成功响应后异步 POST 企业微信。

**Tech Stack:** tkinter, httpx, FastAPI/Starlette middleware, existing AgentSettings.

## Global Constraints

- Windows only for panel/agent
- Webhook empty = disabled
- Do not block HTTP on webhook I/O

---

### Task 1: Config + envfile + webhook module

**Files:** `config.py`, `envfile.py`, `webhook.py`, `tests/test_webhook.py`, `tests/test_envfile.py`

- [ ] Add `webhook_url` to `AgentSettings` / `load_agent_settings`
- [ ] `load_env_file` / `save_env_file` / `apply_env_file_to_os`
- [ ] `notify_wecom_failure` fire-and-forget + unit test payload
- [ ] Commit

### Task 2: API middleware

**Files:** `api.py`, `tests/test_api_webhook.py`

- [ ] Middleware: 401/403/5xx or `success:false` → notify
- [ ] Tests with TestClient + mocked notify
- [ ] Commit

### Task 3: Panel UI + entry

**Files:** `panel.py`, `pyproject.toml`, `README.md`

- [ ] tkinter window, start/stop subprocess, health poll, save agent.env
- [ ] Script `kakaotalk-panel`
- [ ] README 本机启动说明
- [ ] Commit
