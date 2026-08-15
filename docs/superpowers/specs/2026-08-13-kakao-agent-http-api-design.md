# Windows KakaoTalk Automation Agent — HTTP API 设计

日期：2026-08-13  
状态：已通过（2026-08-15）  
来源：fork 自 `kronenz/kakaotalk-mcp`  
目标：保留 MCP，新增可供业务系统调用的本机 HTTP Agent

## 1. 目标

把当前这个主要通过 MCP 调用的 KakaoTalk Win32 自动化项目，改造成 Windows 本机 Agent，让 Django、Celery、n8n 和其他服务器可以通过 HTTP 直接调用。

生产环境不需要 Claude、Cursor、LLM 或 MCP Client。MCP 只作为额外接口保留。

实际发送仍然通过 KakaoTalk PC + Win32 / UI Automation 完成。不使用 Kakao 私有协议，不逆向，不需要 Partner 白名单。业务系统直接传 `room_name`。发送前聊天室窗口标题必须完全一致。

生产拓扑（已确认）：业务代码跑在公司服务器上，Agent 跑在公司闲置 Windows 电脑上。服务器经内网 HTTP POST JSON 调用 Agent。默认开发绑定仍是 `127.0.0.1`；生产必须监听局域网并启用来源 IP 白名单。

```text
公司业务服务器 / Django
        ↓ 内网 HTTP + X-API-Key（仅白名单 IP）
闲置 Windows 上的 Kakao Agent (FastAPI)
        ↓
KakaoService
        ↓
JobManager（单 worker）
        ↓
controller.py
        ↓
Win32 API
        ↓
KakaoTalk PC → 精确匹配的聊天室 / Channel
```

## 2. 已确认决策

| 主题 | 选择 |
|------|------|
| 架构 | 薄 controller + 共用 `KakaoService` + 单 worker 队列 |
| MCP 与 HTTP | 走同一条 `KakaoService` / `open_room_strict` 路径 |
| MCP 发送类工具 | 发送前同样 strict open |
| 业务 HTTP 状态码 | 一律 200，看 `success` + `error_code` |
| 鉴权 HTTP 状态码 | 缺少或错误 API Key 返回 401 |
| 来源 IP 不在白名单 | HTTP 403 + `IP_NOT_ALLOWED` |
| 未捕获异常 | 500 + `INTERNAL_ERROR` |
| 请求体校验失败 | 422（FastAPI 默认） |
| `/health` 鉴权 | 也要 `X-API-Key`，也要过 IP 白名单 |
| 来源 IP 白名单 | `KAKAO_AGENT_ALLOW_IPS`；非本机监听时必填 |
| MCP 监控 | 第一版禁用（`MONITOR_DISABLED`） |
| 并发 | 排队等待超时 → `AUTOMATION_BUSY`；已开始执行则等到做完 |
| 排队等待超时 | 默认 60 秒（`KAKAO_JOB_WAIT_TIMEOUT_SEC`） |
| 单次执行上限 | 默认 300 秒（`KAKAO_JOB_EXEC_TIMEOUT_SEC`）；超时仍不杀半截 UI |
| 多文件失败 | 在第一处失败停止，其余文件标记为跳过 |
| 文件进入 Agent | 方案 C：路径接口保留（本机测试）；生产主用 multipart 上传 |
| 文件根目录 | 只约束 HTTP；MCP 不套用路径白名单 |
| 文件粘贴 | 优先 CF_HDROP，不点死坐标 |
| 图片粘贴 | 保留现有 CF_DIB 路径 |
| 聊天窗生命周期 | 不「用完就关」；在已开窗口中按 title 精确选用 |
| 生产入口 | 只跑 `kakaotalk-api`；不与 MCP 同时操作同一台 KakaoTalk |
| 送达声明 | 永不返回 `delivered` |
| 包名 | 保留 `kakaotalk-mcp`，新增 `kakaotalk-api` 入口 |

## 3. 第一版不做

- 重写已经稳定工作的 `controller.py` Win32 代码
- Kakao 私有协议 / Partner API
- 声称服务端已送达
- 复杂 Windows 安装包
- 重新启用 MCP 聊天室监控
- 用固定屏幕坐标点击来发文件
- CF_HDROP 失败后自动改走文件按钮 / 拖放（若某版 KakaoTalk 不支持，只在文档里记为后续方案）
- 「用完就关」聊天窗
- 自动清理上传 job 目录（第一版只文档建议定期清理）

## 4. 架构

```text
Django / Celery / n8n / MCP Client
        │
        ├─ HTTP  kakaotalk-api   (FastAPI；开发 127.0.0.1，生产内网 + IP 白名单)
        └─ stdio kakaotalk-mcp   (FastMCP，保留)
                │
                ▼
          KakaoService           ← 唯一业务入口
                │
          JobManager             ← 单 worker 线程
                │
          controller.py          ← Win32，尽量原样复用
                │
          KakaoTalk PC
```

| 层 | 负责 | 不负责 |
|----|------|--------|
| `api.py` | HTTP、API Key、来源 IP 白名单、Pydantic 模型 | Win32 |
| `server.py` | MCP tool 适配 | 直接调用 controller |
| `service.py` | 运行检查、strict open、HTTP 路径白名单、上传落盘、发送编排、错误码、日志 | `keybd_event` |
| `job_manager.py` | 全局串行 UI 任务、等待超时 | KakaoTalk 细节 |
| `controller.py` | 窗口 / 剪贴板 / 发送动作 | 模糊成功、HTTP |
| `schemas.py` | 请求 / 响应模型和错误码 | 业务逻辑 |
| `config.py` | 环境变量 + 现有 Win32 常量 | |

启动入口：

- `kakaotalk-mcp` / `python -m kakao_mcp` → MCP stdio（命令不变）
- `kakaotalk-api` / `python -m kakao_mcp.api` → HTTP。开发默认 `http://127.0.0.1:8765`；生产监听内网地址，仅白名单 IP 可访问

只读、不进队列：`GET /health`、`GET /rooms`。  
进队列：所有 `open` / `send*`（HTTP 和 MCP）。

## 5. 新增 / 修改文件

新增：

- `src/kakao_mcp/api.py`
- `src/kakao_mcp/schemas.py`
- `src/kakao_mcp/service.py`
- `src/kakao_mcp/job_manager.py`
- `tests/test_api.py`
- `tests/test_service.py`
- `tests/test_job_manager.py`
- `tests/test_open_room_strict.py`

修改：

- `controller.py` — 增加 `open_room_strict`、CF_HDROP 发文件；删除模糊搜索成功；抽出确认对话框辅助函数
- `server.py` — tool 改为调用 `KakaoService`；禁用 monitor
- `config.py` — Agent 环境变量
- `pyproject.toml` — 增加 `fastapi`、`uvicorn`、`kakaotalk-api` 入口
- `requirements.txt`、`README.md`

不重写：`parser.py`、图片 CF_DIB 链路、mention、缓存图片下载。

不改 Python 包名。

## 6. 严格聊天室匹配

### 6.1 窗口生命周期（不是「用完就关」）

KakaoTalk PC 与当前 controller 的实际行为是：

```text
打开聊天室 → 窗口一直留着
下次同名房间 → 在已开窗口里精确找 title
找不到才再搜索打开
```

第一版**不实现**「发完关闭聊天窗」（已确认选 A）。原因：

- 现有 Win32 代码没有稳定关窗流程；新做有关错窗 / 关到主窗口 / 碰到确认框的风险
- 复用已开窗可少走一次搜索（搜索是最容易开错房的环节）
- 生产闲置机通常只服务少数固定房间，可锁屏，不要求桌面整洁优先

多个聊天窗可以同时开着。认定目标窗时：

- **不要**假设桌上只有一个聊天窗
- **不要**用「最新打开的那个」当目标
- **必须**在全部已开聊天窗里找 `title == room_name`

若以后窗口过多再考虑可配置「发送成功后关闭」（不在第一版范围）。README 可说明：运维可手动关闭不用的聊天窗，或只预开常用房间。

### 6.2 `open_room_strict` 流程

`KakaoService.open_room(room_name)` / `controller.open_room_strict(room_name)`：

1. KakaoTalk 未运行 → `KAKAOTALK_NOT_RUNNING`，停止。
2. 枚举全部已开聊天窗，找 `title == room_name`（复用 `find_chat_window`）。找到 → 成功（可前置窗口，不搜索）。
3. 否则走现有搜索 UI（Ctrl+F、输入、Enter）。
4. 再次枚举全部已开聊天窗，找 `title == room_name`。
5. 找到且完全相等 → 成功。
6. 搜索后仍没有任何 `title == room_name` 的窗口：
   - 若能观察到一个明显因本次搜索打开、但 title **不等于** `room_name` 的窗口 → `ROOM_MISMATCH`（带 `expected_room`、`actual_room`）
   - 若搜索后仍找不到任何可认定的目标窗 → `ROOM_NOT_FOUND`
7. 任一失败都立即停止，不得发送。

### 6.3 错误码何时用哪个

| 错误码 | 含义 |
|--------|------|
| `ROOM_NOT_FOUND` | 搜索后仍没有 `title == room_name` 的聊天窗（没打开到目标） |
| `ROOM_MISMATCH` | 打开了聊天窗，但实际 title ≠ 请求的 `room_name` |

匹配规则是完整字符串相等。不去空白、不忽略大小写、不做子串匹配。实现时对 title / `room_name` 统一做 Unicode NFC 正规化后再比较，避免韩文 NFC/NFD 误报 mismatch。

从 `search_and_open_room()` 删除以下 fallback，并且不再对外暴露：

- `room_name` 是窗口 title 的子串就算成功
- 只要有任意聊天窗口打开就算成功

`search_and_open_room()` 不再作为对外成功路径。MCP `kakao_open_room` 和 HTTP `POST /rooms/open` 都只调用 `open_room_strict`。

所有发送路径（`send_message`、`send_image`、`send_file`、`send_files`、`send_materials`，包括 MCP 发送工具）必须：

```text
KakaoTalk 正在运行
  → open_room_strict
  → 即使窗口已打开也再次校验 title
  → 两步都通过才发送
  → 任何一步失败都停止
```

## 7. HTTP API

### 7.1 监听地址

- `KAKAO_AGENT_HOST` 默认 `127.0.0.1`（本机调试）
- `KAKAO_AGENT_PORT` 默认 `8765`
- 生产（业务服务器 → 闲置 Windows）必须显式设置 `KAKAO_AGENT_HOST=0.0.0.0`，或该 Windows 的局域网 IP
- **禁止**把 8765 做路由器/公网端口映射

### 7.1.1 两种用法：本机测试 vs 生产

两种场景都支持，用环境变量区分，不要混用一套配置。

**本机测试（你现在的方式）：调用代码和 Agent、KakaoTalk 都在同一台 Windows 上。**

```text
KAKAO_AGENT_HOST=127.0.0.1
KAKAO_AGENT_PORT=8765
KAKAO_AGENT_API_KEY=本地测试用的随机字符串
# 不要设 KAKAO_AGENT_ALLOW_IPS
```

此时只监听本机回环。curl、本地 Python、本机 Django 都打 `http://127.0.0.1:8765`。外网和局域网进不来，所以 **不需要 IP 白名单**。只校验 API Key。

**生产：业务代码在公司服务器，Agent 在闲置 Windows 上。**

```text
KAKAO_AGENT_HOST=0.0.0.0
KAKAO_AGENT_PORT=8765
KAKAO_AGENT_API_KEY=足够长的随机密钥
KAKAO_AGENT_ALLOW_IPS=10.0.0.12
```

`10.0.0.12` 换成那台业务服务器的内网 IP。服务器 POST `http://闲置电脑局域网IP:8765`。未在白名单里的机器即使有 Key 也是 403。

同一台电脑上也可以先按「本机测试」把功能跑通，确认 KakaoTalk 自动化没问题后，再换成生产那套环境变量部署到闲置机。

### 7.2 鉴权

每个 HTTP 请求按这个顺序检查（含 `/health`）：

1. 若配置了 IP 白名单（或当前是非回环监听）：来源 IP 必须在 `KAKAO_AGENT_ALLOW_IPS` 中
2. `X-API-Key` 是否等于 `KAKAO_AGENT_API_KEY`

本机测试、监听 `127.0.0.1` 且未配置 `KAKAO_AGENT_ALLOW_IPS` 时：**跳过第 1 步**，只检查 API Key。

```http
X-API-Key: <KAKAO_AGENT_API_KEY>
```

来源 IP 不在白名单 → HTTP **403**：

```json
{"success": false, "error_code": "IP_NOT_ALLOWED", "error": "..."}
```

环境变量未配置、缺少 header、或 Key 不对 → HTTP **401**：

```json
{"success": false, "error_code": "INVALID_API_KEY", "error": "..."}
```

Key 不进 Git，不写进日志。日志可记来源 IP，不记 Key。

### 7.2.1 来源 IP 白名单

环境变量：`KAKAO_AGENT_ALLOW_IPS`，逗号分隔的 IPv4 地址，例如：

```text
KAKAO_AGENT_ALLOW_IPS=10.0.0.12,10.0.0.13
```

规则：

- 比较 TCP 对端地址（`request.client.host`），**不信任** `X-Forwarded-For`（第一版不做反向代理）。
- IPv4-mapped IPv6（如 `::ffff:10.0.0.12`）先还原成 `10.0.0.12` 再比较。
- 只做精确 IP 匹配，第一版不做 CIDR。
- 空白项忽略；比较前去掉首尾空格。
- 本机用 curl 调试且监听 `0.0.0.0` 时，白名单需包含 `127.0.0.1`。

启动约束：

- `KAKAO_AGENT_HOST` 为 `127.0.0.1` 或 `::1`：白名单可选。未配置则不做 IP 检查。这就是本机测试模式。
- `KAKAO_AGENT_HOST` 为 `0.0.0.0`、`::` 或其它非回环地址：`KAKAO_AGENT_ALLOW_IPS` **必填且至少一条**。未配置则拒绝启动，避免局域网裸奔。

Windows 防火墙仍应只放行业务服务器 IP 入站 8765。应用层白名单是第二道闸，不能替代防火墙。

### 7.3 状态码

| 情况 | HTTP |
|------|------|
| 业务成功或业务失败 | 200，看 `success` + `error_code` |
| 来源 IP 不在白名单 | 403 |
| 缺少或错误 API Key | 401 |
| 请求体不合法 | 422 |
| 未捕获异常 | 500 + `INTERNAL_ERROR` |

### 7.4 端点

Phase 2：

| 方法 | 路径 | 行为 |
|------|------|------|
| GET | `/health` | `is_kakaotalk_running()` |
| GET | `/rooms` | `list_chat_windows()` |
| POST | `/rooms/open` | `open_room_strict` |
| POST | `/send/message` | strict open → 发文字 |

Phase 4–5：

| 方法 | 路径 | 行为 |
|------|------|------|
| POST | `/send/image` | JSON 路径；复用现有 CF_DIB 发图（本机测试） |
| POST | `/send/file` | JSON 路径；CF_HDROP 单文件（本机测试） |
| POST | `/send/files` | JSON 路径列表；按顺序逐个发送，首败即停 |
| POST | `/send/materials` | JSON：`job_id` + message + 本机路径列表 |
| POST | `/send/materials/upload` | **生产主路径**：multipart 上传文件到 Agent 后再发送 |

路径版接口要求文件**已经**在 Agent 所在 Windows 的 `KAKAO_ALLOWED_FILE_ROOT` 内。  
上传版由 Agent 落盘后再走同一套 strict open + 发送逻辑。


### 7.5 响应形状

`GET /health`（KakaoTalk 在跑）：

```json
{"success": true, "kakaotalk_running": true, "pid": 1234}
```

没在跑（仍是 HTTP 200）：

```json
{
  "success": false,
  "kakaotalk_running": false,
  "error_code": "KAKAOTALK_NOT_RUNNING"
}
```

`GET /rooms`：KakaoTalk 未运行时 HTTP 200，`success: false`，`error_code: "KAKAOTALK_NOT_RUNNING"`。在跑时：

```json
{
  "success": true,
  "rooms": [{"title": "한패스 고객센터", "hwnd": 123456}]
}
```

`POST /rooms/open` 请求体：`{"room_name": "..."}`。未运行 → `KAKAOTALK_NOT_RUNNING`；搜不到 → `ROOM_NOT_FOUND`；开错 → `ROOM_MISMATCH`。

`POST /send/message` 成功：

```json
{
  "success": true,
  "room_name": "한패스 고객센터",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

永不包含 `delivered` 字段。

`POST /send/image` 请求体：`{"room_name": "...", "image_path": "C:\\KakaoAgent\\jobs\\123\\passport.jpg"}`。

`POST /send/file` 请求体：`{"room_name": "...", "file_path": "..."}`。

`POST /send/files` 请求体：`{"room_name": "...", "file_paths": ["...", "..."]}`。  
文件顺序必须与请求一致。响应里每个文件用 basename。

`POST /send/materials` 请求（本机路径版，适合本机测试）：

```json
{
  "room_name": "한패스 고객센터",
  "job_id": "GM-123456",
  "message": "신규 개통 서류 전달드립니다.",
  "files": [
    "C:\\KakaoAgent\\jobs\\GM-123456\\passport.pdf",
    "C:\\KakaoAgent\\jobs\\GM-123456\\application.jpg"
  ]
}
```

`message` 为空或只有空白：跳过发文字，`message_sent: false`。  
`files` 为空：跳过发文件。  
message 和 files 都空：HTTP 200，`success: false`，`error_code: "INVALID_REQUEST"`。JSON 畸形或类型错误仍走 FastAPI 422。

单独 `POST /send/message` 若 `message` 为空或只有空白：同样 HTTP 200 + `INVALID_REQUEST`。

#### `POST /send/materials/upload`（生产主路径）

`Content-Type: multipart/form-data`

| 字段 | 类型 | 说明 |
|------|------|------|
| `room_name` | text | 必填 |
| `job_id` | text | 必填；用于落盘子目录名（只允许安全字符，见下） |
| `message` | text | 可选；空则不发文字 |
| `files` | file（可多个） | 按表单顺序发送；至少一个文件，或与非空 message 至少有其一 |

流程：

```text
鉴权（IP + API Key）
→ 校验 job_id / 文件名安全
→ 每个上传文件检查大小 ≤ KAKAO_MAX_FILE_SIZE_MB
→ 保存到 KAKAO_ALLOWED_FILE_ROOT\<job_id>\
→ 与 /send/materials 相同：strict open → 发文字 → 按顺序发文件
→ 返回相同形状的 JSON（含 automation_success / 部分失败）
```

`job_id` 规则：只允许字母、数字、`-`、`_`；长度上限例如 64。禁止 `..`、路径分隔符。  
上传文件名只用 basename；禁止路径穿越。同名文件覆盖同 job 目录下已有文件。

落盘后发送失败：已写入磁盘的文件**保留**（方便排查）；不在第一版做自动清理。README 建议定期清理 `KAKAO_ALLOWED_FILE_ROOT` 下过期 job 目录。

生产 Django 应调用 `/send/materials/upload`，把服务器上的护照/申请表直接 POST 过来，不必再维护 SMB 共享。本机调试可继续用 JSON 路径版。

成功：

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

部分失败（文字已发、第二个文件失败；后面的文件未尝试）：

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

不回滚已经发出的文字。被跳过的文件不算成功。

`ROOM_MISMATCH` 额外字段：`expected_room`、`actual_room`。  
`ROOM_NOT_FOUND` 带 `expected_room`（请求的房间名）。

### 7.6 错误码

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
IP_NOT_ALLOWED
INVALID_REQUEST
INVALID_JOB_ID
AUTOMATION_BUSY
JOB_EXEC_TIMEOUT
MONITOR_DISABLED
INTERNAL_ERROR
```

通用失败结构：

```json
{"success": false, "error_code": "ROOM_MISMATCH", "error": "..."}
```

## 8. 文件发送

图片（`POST /send/image`）：保留 `_copy_image_to_clipboard`（PowerShell 转 BMP → `CF_DIB`）+ Ctrl+V + 确认对话框。不重写。

附件（`send_file_to_room` / `send_files_to_room`）：

```text
校验路径（白名单、存在、普通文件、大小）
→ 写入 CF_HDROP（DROPFILES + UTF-16 路径）
→ open_room_strict + 再次校验 title
→ AttachThreadInput + SetFocus 到 RICHEDIT50W（与发图相同，不点死坐标）
→ Ctrl+V
→ 轮询前景窗口变化，当作确认对话框
→ Enter
→ 只返回 automation_success
```

`/send/files` 按请求顺序，每次 CF_HDROP 只贴一个文件。不要一次 drop 多个文件。

`/send/image` 的 `.jpg` 按图片发送。  
`/send/file` 的同一个 `.jpg` 按文件附件发送。

从 `send_image_to_room` 抽出「等待确认对话框 → Enter」，给图片和文件共用。对话框未出现 → `IMAGE_SEND_FAILED` 或 `FILE_SEND_FAILED`。

第一版只实现 CF_HDROP。若某版 KakaoTalk 拒绝粘贴，返回真实 automation 失败。后续方案（不做进第一版）：KakaoTalk 文件按钮 + 系统打开对话框，然后 `WM_DROPFILES`。不要一开始就用固定点击坐标。

不设扩展名白名单。通过路径和大小校验后尝试发送。若 KakaoTalk 拒绝该格式，返回真实 automation 失败。README 举例：`.pdf .xlsx .xls .doc .docx .txt .zip .jpg .jpeg .png`。

## 9. 文件安全与落盘

### 9.1 HTTP 路径约束（只约束 HTTP）

- `KAKAO_ALLOWED_FILE_ROOT` 默认 `C:\KakaoAgent\jobs`
- 使用 `Path.resolve()`。解析后必须仍在 root 内。禁止 `..` 穿越。
- 必须存在，必须是普通文件。
- `KAKAO_MAX_FILE_SIZE_MB` 默认 `100`（写入 README；贴近 KakaoTalk PC 常见附件上限）。
- 超出 root → `FILE_PATH_NOT_ALLOWED`
- 不存在 → `FILE_NOT_FOUND`
- 过大 → `FILE_TOO_LARGE`
- JSON 路径版的 `/send/image`、`/send/file`、`/send/files`、`/send/materials` 都受上述约束。
- 上传版落盘目标也必须在 root 内；单文件上传大小同样受 `KAKAO_MAX_FILE_SIZE_MB` 限制。

### 9.2 MCP 不套用路径白名单

MCP 走本机 stdio，生产几乎不用。`kakao_send_image` 等可继续使用本机任意可读路径（与今天行为一致）。开房与发送仍走 `KakaoService` + JobManager，但**不做** `KAKAO_ALLOWED_FILE_ROOT` 校验。

### 9.3 远程服务器如何把文件交给 Agent

方案 C（已确认）：

| 场景 | 用哪个接口 |
|------|------------|
| 本机测试（文件已在同一台 Windows） | JSON 路径：`/send/file`、`/send/materials` |
| 生产（Django 在远程服务器） | multipart：`/send/materials/upload` |

不要假设服务器与 Agent 共享同一个 `C:\` 盘符。生产主路径是上传，不是 SMB（若运维另有共享盘，仍可用路径版，但不作为默认要求）。

## 10. JobManager

不要只用 `asyncio.Lock` 做串行。controller 是同步 Win32。

```text
HTTP / MCP 请求
  → KakaoService 方法
  → JobManager.submit(fn)
  → 单 worker 线程执行 fn
  → Future 把结果交回调用方
```

- 进程内一个 `queue.Queue` + 一条 worker 线程。
- 只有这条线程调用 controller 的 UI 函数。
- **排队等待超时**（`KAKAO_JOB_WAIT_TIMEOUT_SEC`，默认 60）：只统计「还没轮到我」的时间。超时 → `AUTOMATION_BUSY`。此时 worker **尚未开始**该 job，不会出现半截发送。
- **一旦 worker 开始执行**：HTTP 等到该 job 结束。不要用 60 秒去砍正在跑的 `send_materials`。
- **执行上限**（`KAKAO_JOB_EXEC_TIMEOUT_SEC`，默认 300）：从开始执行算起。超时返回 `JOB_EXEC_TIMEOUT`。**仍不强制杀掉**正在进行的 Win32 动作（避免半截 Ctrl+V）；以日志告警为主。若实现上可用协作式检查点（每个文件之间检查是否超时）则在文件边界停止后续文件并返回部分失败。
- 不设很小的队列上限；靠排队等待超时防止 HTTP 线程无限堵在队头。

进队列：HTTP 和 MCP 的 open / send（含 upload 落盘后的发送段；落盘本身可在进队前完成，但「开房+发送」必须在同一 job 内）。  
不进队列：`/health`、`/rooms`。

`send_materials` / `send_materials/upload` 的发送段作为**一个** job 提交，内部的文字和多个文件不会被其它请求插队。

FastAPI 路由用同步 `def`，等待发生在线程池，不卡住事件循环。

必须遵守的顺序：

```text
错误：Job A 打开房间 A → Job B 打开房间 B → Job A Ctrl+V
正确：Job A 整段开房+校验+发送完成 → 才开始 Job B
```

## 11. 日志

每条发送任务记录：timestamp、job_id、room_name、message_sent、file_count、文件 **basename**、success、error_code、error、duration。

不记录文件内容。  
默认不记录完整 message，只记 `message_length` 和 `message_hash`。  
只有 `KAKAO_LOG_MESSAGE_BODY=1` 时才记录正文。  
永不记录 API Key。

## 12. MCP 兼容

保留 `kakaotalk-mcp`、`python -m kakao_mcp`、现有 tool 名和参数。

生产预期：**只跑 `kakaotalk-api`**。不要求也不设计「MCP 与 HTTP 同进程抢 UI」的防护；运维上不要同时对同一台 KakaoTalk 开 MCP 和 API。

tool 改为走 `KakaoService`：

| Tool | 第一版行为 |
|------|------------|
| `kakao_open_room` | 只精确匹配；`ROOM_NOT_FOUND` / `ROOM_MISMATCH` |
| `kakao_send_message` / `kakao_send_image` / `kakao_send_bulk` | 发送前 strict open |
| `kakao_start_monitor` | 拒绝，`MONITOR_DISABLED` |
| `kakao_stop_monitor` / `kakao_get_monitor_events` | 同样拒绝（monitor 未运行） |
| read / mention / extract_links / download_images | 保留，走 Service + JobManager |
| 文件路径 | **不**套用 `KAKAO_ALLOWED_FILE_ROOT`（仅 HTTP 约束） |

MCP 响应仍接近 `{message}` / `{error}`，可以带 `error_code`。不要把完整 HTTP JSON 信封强加给 MCP 客户端。

## 13. 配置 / 环境变量

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `KAKAO_AGENT_API_KEY` | （HTTP 必填） | `X-API-Key` |
| `KAKAO_AGENT_HOST` | `127.0.0.1` | 监听地址；生产用 `0.0.0.0` 或局域网 IP |
| `KAKAO_AGENT_PORT` | `8765` | 监听端口 |
| `KAKAO_AGENT_ALLOW_IPS` | 本机监听时可空；非回环监听必填 | 允许调用的来源 IPv4，逗号分隔 |
| `KAKAO_ALLOWED_FILE_ROOT` | `C:\KakaoAgent\jobs` | HTTP 可发送 / 上传落盘根目录 |
| `KAKAO_MAX_FILE_SIZE_MB` | `100` | 附件 / 图片 / 上传单文件大小上限 |
| `KAKAO_JOB_WAIT_TIMEOUT_SEC` | `60` | 排队等待超时 → `AUTOMATION_BUSY` |
| `KAKAO_JOB_EXEC_TIMEOUT_SEC` | `300` | 单次 job 执行上限（见第 10 节） |
| `KAKAO_LOG_MESSAGE_BODY` | 未设置 / false | 是否记录完整 message |

（若代码里仍读旧名 `KAKAO_JOB_TIMEOUT_SEC`，视为 `KAKAO_JOB_WAIT_TIMEOUT_SEC` 的别名，README 只文档化新名。）


启动失败条件（均给出明确错误，不绑定端口）：

- `KAKAO_AGENT_API_KEY` 未设置或为空
- 监听非回环地址，且 `KAKAO_AGENT_ALLOW_IPS` 为空

## 14. 测试

CI 中 mock Win32 和真机 KakaoTalk。

| 层 | 断言 | Mock |
|----|------|------|
| API | 鉴权、401、403 IP 白名单、health、422、错误 JSON 形状 | Service |
| Service | 精确匹配、mismatch 停发、路径穿越、缺文件、过大、materials 部分失败、跳过未尝试文件 | controller + JobManager（或同步直跑） |
| JobManager | job 不交错；超时 → BUSY；materials 不被拆开 | 假的慢函数 |
| Controller | `open_room_strict` 精确成功 / mismatch / 禁止任意窗口成功；文件剪贴板内容 | win32gui / clipboard |

至少覆盖：

1. health
2. API Key 正确
3. API Key 错误 / 缺失
3b. 来源 IP 不在白名单 → 403
3c. 来源 IP 在白名单且 Key 正确 → 通过
4. rooms
5. 严格精确房间匹配（已开窗精确命中）
6. `ROOM_MISMATCH`（打开了错误 title）
6b. `ROOM_NOT_FOUND`（搜索后仍无目标窗）
7. 危险 fallback 已不存在
8. 文件不存在
9. 文件在允许目录外
10. path traversal
11. send message
12. send image
13. send file
14. send files
15. send materials（路径版）
15b. send materials/upload（multipart 落盘 + 发送）
15c. 非法 job_id / 上传文件名穿越
16. 部分文件失败
17. 全局 UI 串行队列
17b. 排队等待超时 → `AUTOMATION_BUSY`，且不中断已在执行的 job
18. controller mock

Phase 2 覆盖 1–7、11、API Key、IP 白名单，以及 JobManager 基础不交错与排队超时测试。文件与 upload 随 Phase 4–5 补。Phase 6 扩充执行上限与 materials 不被插队测试。保留现有 `test_parser.py` 和 `test_controller.py`。补 MCP 测试：开房 mismatch、monitor 被禁用；确认 MCP 发图不强制 file root。

## 15. README / 部署（Phase 8）

文档写清：

- Windows 10/11，用户已登录，KakaoTalk PC 已登录并在运行
- 生产环境不需要 Claude / Cursor / LLM / MCP Client
- 不走 Kakao 私有协议，不需要 Partner Code，业务传 `room_name`
- 开发 / 本机测试：调用方和 Agent 同一台电脑，绑 `127.0.0.1`，不配 IP 白名单，只带 API Key
- 生产拓扑：公司服务器 multipart POST → 闲置 Windows 上的 Agent（内网，不要公网映射）
- 生产主用 `/send/materials/upload`；本机测试可用 JSON 路径版
- 生产：`0.0.0.0` + `KAKAO_AGENT_ALLOW_IPS`（业务服务器 IP）+ Windows 防火墙只放行该 IP + API Key
- 禁止把 8765 端口转发到公网
- 闲置电脑建议固定局域网 IP（或 DHCP 保留），避免白名单与 Django 目标地址失效
- 开机：任务计划程序「用户登录时」启动 `kakaotalk-api`；第一版不写自定义安装包
- 生产只跑 API，不要同时开 MCP 打同一台 KakaoTalk
- UI 动作不等于送达；Agent 会抢焦点并占用剪贴板
- 聊天室名必须与 KakaoTalk 窗口标题完全一致；窗口用完不自动关闭
- 定期清理 `KAKAO_ALLOWED_FILE_ROOT` 下过期 job 目录
- CF_HDROP 发文件需要在目标电脑上对当前 KakaoTalk 版本做一次真机验证

## 16. 实施阶段

不要一次改完。spec 确认后先写实施计划，再按阶段执行。

**Phase 2 — HTTP 基础**  
`KakaoService` + FastAPI：`/health`、`/rooms`、`/rooms/open`、`/send/message`。API Key。来源 IP 白名单。`kakaotalk-api` 入口。这里就引入 `JobManager`，即使还没有发文件，开房 / 发送也不能交错。测试：health、鉴权、IP 白名单、rooms、send message（mock controller）。开房使用精确 title；HTTP 不暴露模糊搜索成功。

**Phase 3 — 严格开房**  
`open_room_strict`。删除子串匹配 / 任意窗口成功。测试：精确匹配、mismatch、fallback 已消失。MCP 开房 / 发送 / bulk 走同一路径。

**Phase 4 — 发文件（路径版）**  
CF_HDROP + 确认对话框。`/send/file`、`/send/files`、`/send/image`（图片仍复用 CF_DIB）。HTTP 路径白名单测试。

**Phase 5 — 材料发送**  
`/send/materials`（路径版）+ `/send/materials/upload`（multipart 落盘 + 同一发送编排）。`job_id`、部分失败、非法 job_id / 文件名测试。

**Phase 6 — 队列加固**  
JobManager 在 Phase 2 已经存在。本阶段补：排队等待 → `AUTOMATION_BUSY` 且不误杀执行中 job；materials / upload 作为一个 job 不被插队；执行上限行为。

**Phase 7 — 安全 / 日志**  
文件 root、大小上限、上传落盘、脱敏日志。路径校验应在 Phase 4 已有；本阶段收口配置和文档。

**Phase 8 — README**  
安装、运行、本机测试 vs 生产 upload、Windows / KakaoTalk 要求、curl、内网部署、IP 白名单、防火墙、禁止公网映射、任务计划开机启动、job 目录清理。

Phase 2 结束后应能运行 `kakaotalk-api`。发文件等到 Phase 4。

## 17. 风险

1. 搜索无法保证 KakaoTalk 第一个结果就是目标房间。打开后在全部窗口中精确 title 校验才是安全门。
2. 某些 KakaoTalk 版本可能忽略 CF_HDROP 粘贴。返回真实失败，不假装成功。
3. UI Automation 只能证明本机发送动作，不能证明 Kakao 服务端已送达。
4. 剪贴板是全局的，发送期间会覆盖用户剪贴板。
5. 会抢前台：这台机器不宜当重度日常桌面使用。
6. MCP monitor 会和 HTTP 发送抢 UI；第一版禁用。生产只跑 API。
7. MCP 开房 / 发送会变更严（相对原来的模糊成功，这是有意的破坏性变更）。
8. 通过我们的校验后，KakaoTalk 仍可能因格式或大小拒收。
9. 生产若监听 `0.0.0.0` 却未配 IP 白名单，内网任意机器都可能打到端口（启动时强制白名单就是为了挡住这点）。
10. 第一版不信任 `X-Forwarded-For`；前面若加了反向代理，看到的会是代理 IP，需要把代理 IP 写入白名单，或后续再做受信代理。
11. 上传落盘目录会累积；第一版不自动删，需运维清理，否则磁盘占满。
12. 执行超时很难安全中断半截 UI；只能在文件边界停止后续文件，并如实返回部分失败。
13. 韩文窗口 title 若未做 NFC 正规化，可能误报 `ROOM_MISMATCH`。

## 18. controller 改动边界

允许：

- 新增 `open_room_strict`
- 搜索成功改为仅精确 title，失败返回 mismatch 信息
- 新增 `send_file_to_room` / `send_files_to_room`
- 抽出确认对话框辅助函数，给图片和文件共用

本次不允许：

- 重写窗口发现、前置窗口、发文字、CF_DIB 发图、读消息、mention
- 重新引入「只要有任意聊天窗口打开就算成功」
