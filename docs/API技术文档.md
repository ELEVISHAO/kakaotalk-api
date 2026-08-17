# KakaoTalk Agent HTTP API 技术文档

KakaoTalk Windows Agent 提供 HTTP 接口，供业务系统（Django / Celery / n8n 等）调用，实现对本机 KakaoTalk PC 的自动化控制：发消息、发文件、发图片、打开聊天室等。

> 底层通过 Win32 API 操作本机已登录的 KakaoTalk 客户端，**不依赖任何 LLM / MCP 客户端**。

---

## 1. 基础信息

| 项目 | 说明 |
|------|------|
| Base URL | `http://<agent_ip>:<port>` |
| 默认端口 | `8765` |
| 鉴权方式 | Header `X-API-Key` |
| 数据格式 | `application/json` |
| 响应编码 | UTF-8（中文/韩文） |

### 启动方式

在 Windows 上启动 Agent：

```powershell
set KAKAO_AGENT_API_KEY=你的密钥
set KAKAO_AGENT_HOST=127.0.0.1
set KAKAO_AGENT_PORT=8765
kakaotalk-api
```

或使用运维面板 `run_gui.py` 填写配置后点击「启动服务」。

---

## 2. 鉴权说明

所有接口都必须携带 API Key：

```
X-API-Key: <你的密钥>
```

| 情况 | HTTP 状态码 | 返回 |
|------|-------------|------|
| 缺少 / 错误的 API Key | `401` | `success: false, error_code: INVALID_API_KEY` |
| 来源 IP 不在白名单 | `403` | `success: false, error_code: IP_NOT_ALLOWED` |
| 业务失败（房间不存在等） | `200` | `success: false, error_code: ROOM_NOT_FOUND` 等 |

> **注意**：业务失败大多返回 **HTTP 200 + `success: false`**，不要只判断 HTTP 状态码，必须检查响应体里的 `success` 字段。

---

## 3. 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（KakaoTalk 是否在运行） |
| GET | `/rooms` | 已打开的聊天窗口列表 |
| POST | `/rooms/open` | 打开聊天室（严格精确标题匹配） |
| POST | `/send/message` | 发送文字消息 |
| POST | `/send/image` | 发送图片 |
| POST | `/send/file` | 发送单个附件 |
| POST | `/send/files` | 发送多个附件（首败即停） |
| POST | `/send/materials` | 发送文字 + 附件（生产主用，JSON 路径版） |
| POST | `/send/materials/upload` | 发送文字 + 附件（multipart 上传版） |

---

## 4. 接口详细说明

### 4.1 健康检查 GET /health

检查 KakaoTalk 客户端是否在本机运行。

**请求示例：**
```bash
curl.exe http://127.0.0.1:8765/health -H "X-API-Key: test-key-123"
```

**正确返回（KakaoTalk 运行中）：**
```json
{
  "success": true,
  "kakaotalk_running": true,
  "pid": 9876
}
```

**错误返回（KakaoTalk 未运行）：**
```json
{
  "success": true,
  "kakaotalk_running": false,
  "pid": null
}
```

> `/health` 始终返回 `success: true`（接口本身存活），用 `kakaotalk_running` 判断 KakaoTalk 状态。

---

### 4.2 聊天室列表 GET /rooms

获取当前 **已经打开** 的聊天窗口列表。

**请求示例：**
```bash
curl.exe http://127.0.0.1:8765/rooms -H "X-API-Key: test-key-123"
```

**正确返回：**
```json
{
  "success": true,
  "rooms": [
    { "title": "测试1", "hwnd": 20060056 },
    { "title": "客服群", "hwnd": 20060057 }
  ]
}
```

**错误返回（KakaoTalk 未运行）：**
```json
{
  "success": false,
  "error_code": "KAKAOTALK_NOT_RUNNING",
  "error": "KakaoTalk is not running"
}
```

---

### 4.3 打开聊天室 POST /rooms/open

搜索并打开聊天室。采用**严格精确标题匹配**，不会误匹配相似名称。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称（需精确匹配） |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/rooms/open \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1"}'
```

**正确返回（房间已打开）：**
```json
{
  "success": true,
  "hwnd": 20060056,
  "room_name": "测试1",
  "message": "Chat room '测试1' already open"
}
```

**正确返回（新打开的房间）：**
```json
{
  "success": true,
  "hwnd": 20060056,
  "room_name": "测试1",
  "message": "Opened chat room '测试1'"
}
```

**错误返回（找不到房间）：**
```json
{
  "success": false,
  "error_code": "ROOM_NOT_FOUND",
  "expected_room": "测试1",
  "error": "Chat room '测试1' not found after search"
}
```

**错误返回（打开了别的房间，名称不匹配）：**
```json
{
  "success": false,
  "error_code": "ROOM_MISMATCH",
  "expected_room": "测试1",
  "actual_room": "测试2",
  "error": "Opened '测试2' but expected '测试1'"
}
```

---

### 4.4 发送文字消息 POST /send/message

向指定聊天室发送一条文字消息。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `message` | string | 是 | 消息内容，不能为空 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/message \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1","message":"测试消息"}'
```

**正确返回：**
```json
{
  "success": true,
  "room_name": "测试1",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**错误返回（房间不存在）：**
```json
{
  "success": false,
  "error_code": "ROOM_NOT_FOUND",
  "expected_room": "测试1",
  "error": "Chat room '测试1' not found after search"
}
```

**错误返回（消息为空）：**
```json
{
  "success": false,
  "error_code": "INVALID_REQUEST",
  "error": "Message cannot be empty"
}
```

**错误返回（KakaoTalk 未运行）：**
```json
{
  "success": false,
  "error_code": "KAKAOTALK_NOT_RUNNING",
  "error": "KakaoTalk is not running"
}
```

> `automation_success: true` + `verification: UI_ACTION_COMPLETED` 表示 UI 操作已完成。
> **注意**：响应只表示发送动作完成，**没有** `delivered`（已读）字段。

---

### 4.5 发送图片 POST /send/image

向聊天室发送图片（支持 JPG / PNG / GIF / BMP / WebP）。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `image_path` | string | 是 | 图片的绝对路径，必须在允许目录内 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/image \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1","image_path":"C:/KakaoAgent/jobs/test001/photo.jpg"}'
```

**正确返回：**
```json
{
  "success": true,
  "room_name": "测试1",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**错误返回（文件不在允许目录）：**
```json
{
  "success": false,
  "error_code": "FILE_PATH_NOT_ALLOWED",
  "error": "File path not allowed",
  "path": "C:/Users/admin/photo.jpg"
}
```

**错误返回（文件不存在）：**
```json
{
  "success": false,
  "error_code": "FILE_NOT_FOUND",
  "error": "File not found: C:/KakaoAgent/jobs/test001/photo.jpg"
}
```

---

### 4.6 发送单个附件 POST /send/file

向聊天室发送一个附件文件。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `file_path` | string | 是 | 文件的绝对路径，必须在允许目录内 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/file \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1","file_path":"C:/KakaoAgent/jobs/test001/HZ (2).jpg"}'
```

**正确返回：**
```json
{
  "success": true,
  "room_name": "测试1",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**错误返回（文件不存在）：**
```json
{
  "success": false,
  "error_code": "FILE_NOT_FOUND",
  "error": "File not found: C:/KakaoAgent/jobs/test001/xxx.pdf"
}
```

---

### 4.7 发送多个附件 POST /send/files

一次性发送多个附件，**首个失败即停止**。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `file_paths` | array[string] | 是 | 文件绝对路径数组，均需在允许目录内 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/files \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1","file_paths":["C:/KakaoAgent/jobs/test001/a.pdf","C:/KakaoAgent/jobs/test001/b.jpg"]}'
```

**正确返回：**
```json
{
  "success": true,
  "room_name": "测试1",
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**错误返回（file_paths 为空）：**
```json
{
  "success": false,
  "error_code": "INVALID_REQUEST",
  "error": "file_paths cannot be empty"
}
```

---

### 4.8 发送文字 + 附件 POST /send/materials（生产主用）

同时发送一段文字和多个附件，使用 `job_id` 关联业务单号。文件为**本机路径**形式。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `job_id` | string | 是 | 业务单号，仅字母数字 `-` `_`，1-64 位 |
| `message` | string | 否 | 文字内容，可空（与 files 至少填一项） |
| `files` | array[string] | 否 | 附件路径数组，均需在允许目录内 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/materials \
  -H "X-API-Key: test-key-123" -H "Content-Type: application/json" \
  -d '{"room_name":"测试1","job_id":"TEST-001","message":"测试文字","files":["C:/KakaoAgent/jobs/test001/HZ (2).jpg"]}'
```

**正确返回（文字 + 文件全部成功）：**
```json
{
  "success": true,
  "job_id": "TEST-001",
  "room_name": "测试1",
  "message_sent": true,
  "files": [
    { "file": "HZ (2).jpg", "success": true }
  ],
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**正确返回（只发文件，无文字）：**
```json
{
  "success": true,
  "job_id": "TEST-001",
  "room_name": "测试1",
  "message_sent": false,
  "files": [
    { "file": "a.pdf", "success": true }
  ],
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

**错误返回（文件不存在）：**
```json
{
  "success": false,
  "error_code": "FILE_NOT_FOUND",
  "error": "File not found: C:/KakaoAgent/jobs/test001/xxx.pdf",
  "job_id": "TEST-001",
  "room_name": "测试1"
}
```

**错误返回（job_id 非法）：**
```json
{
  "success": false,
  "error_code": "INVALID_JOB_ID",
  "error": "Invalid job_id",
  "job_id": "TEST-001!"
}
```

**错误返回（部分文件发送失败）：**
```json
{
  "success": false,
  "job_id": "TEST-001",
  "room_name": "测试1",
  "message_sent": false,
  "error_code": "FILE_SEND_FAILED",
  "completed_files": 1,
  "failed_file": "b.pdf",
  "files": [
    { "file": "a.pdf", "success": true },
    { "file": "b.pdf", "success": false }
  ]
}
```

**错误返回（房间不存在）：**
```json
{
  "success": false,
  "error_code": "ROOM_NOT_FOUND",
  "expected_room": "测试1",
  "error": "Chat room '测试1' not found after search",
  "job_id": "TEST-001"
}
```

---

### 4.9 发送文字 + 附件（上传版）POST /send/materials/upload

与 4.8 功能相同，但附件通过 **multipart/form-data** 上传，文件不需要提前放在 Agent 机器上。

**请求参数（multipart form）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `room_name` | string | 是 | 聊天室名称 |
| `job_id` | string | 是 | 业务单号，仅字母数字 `-` `_`，1-64 位 |
| `message` | string | 否 | 文字内容，可空 |
| `files` | file | 否 | 可多个，每个文件一个 `files` 字段 |

**请求示例：**
```bash
curl.exe -X POST http://127.0.0.1:8765/send/materials/upload \
  -H "X-API-Key: test-key-123" \
  -F "room_name=测试1" \
  -F "job_id=GM-123456" \
  -F "message=新开通资料请查收" \
  -F "files=@C:\Users\admin\Documents\passport.pdf" \
  -F "files=@C:\Users\admin\Documents\application.jpg"
```

**正确返回：**
```json
{
  "success": true,
  "job_id": "GM-123456",
  "room_name": "测试1",
  "message_sent": true,
  "files": [
    { "file": "passport.pdf", "success": true },
    { "file": "application.jpg", "success": true }
  ],
  "automation_success": true,
  "verification": "UI_ACTION_COMPLETED"
}
```

---

## 5. 错误码汇总

| error_code | 说明 |
|------------|------|
| `KAKAOTALK_NOT_RUNNING` | KakaoTalk 客户端未运行 |
| `ROOM_NOT_FOUND` | 搜索后未找到该聊天室 |
| `ROOM_MISMATCH` | 打开的房间标题与期望不符 |
| `EDIT_CONTROL_NOT_FOUND` | 聊天窗口内未找到输入框 |
| `FILE_NOT_FOUND` | 文件不存在 |
| `FILE_PATH_NOT_ALLOWED` | 文件路径不在允许根目录内 |
| `FILE_TOO_LARGE` | 文件超过大小上限 |
| `FILE_SEND_FAILED` | 附件发送失败 |
| `IMAGE_SEND_FAILED` | 图片发送失败 |
| `MESSAGE_SEND_FAILED` | 文字发送失败 |
| `INVALID_API_KEY` | API Key 错误或缺失（HTTP 401） |
| `IP_NOT_ALLOWED` | 来源 IP 不在白名单（HTTP 403） |
| `INVALID_REQUEST` | 请求参数不合法（如 message 为空） |
| `INVALID_JOB_ID` | job_id 格式不合法 |
| `AUTOMATION_BUSY` | 队列忙，上一个任务未完成（等待超时） |
| `JOB_EXEC_TIMEOUT` | 单次任务执行超时 |
| `INTERNAL_ERROR` | 服务端内部错误 |

> **422 Unprocessable Entity**：请求体不是合法 JSON 或缺少必填字段。FastAPI 返回的 `detail` 里会标明具体是哪个字段问题（如 `room_name: Field required`）。

---

## 6. 环境变量说明

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `KAKAO_AGENT_API_KEY` | （必填） | API 访问密钥 |
| `KAKAO_AGENT_HOST` | `127.0.0.1` | 监听地址 |
| `KAKAO_AGENT_PORT` | `8765` | 监听端口 |
| `KAKAO_AGENT_ALLOW_IPS` | 本机可空 | 逗号分隔的来源 IP 白名单；非本机监听必填 |
| `KAKAO_ALLOWED_FILE_ROOT` | `C:\KakaoAgent\jobs` | HTTP 文件允许根目录 |
| `KAKAO_MAX_FILE_SIZE_MB` | `100` | 单文件大小上限（MB） |
| `KAKAO_JOB_WAIT_TIMEOUT_SEC` | `60` | 排队等待超时（→ AUTOMATION_BUSY） |
| `KAKAO_JOB_EXEC_TIMEOUT_SEC` | `300` | 单次任务执行上限（→ JOB_EXEC_TIMEOUT） |
| `KAKAO_AGENT_WEBHOOK_URL` | 空 | 企业微信 Webhook，失败时推送告警 |

---

## 7. 注意事项

1. **业务失败不一定是 HTTP 错误**：业务失败多返回 HTTP 200 + `success: false`，务必检查 `success` 字段。
2. **聊天室名称需精确**：`room_name` 必须与 KakaoTalk 中聊天室标题完全一致，可用 `GET /rooms` 确认。
3. **文件必须在允许目录内**：`/send/image`、`/send/file`、`/send/files`、`/send/materials` 的路径必须在 `KAKAO_ALLOWED_FILE_ROOT` 内，否则返回 `FILE_PATH_NOT_ALLOWED`。
4. **发送需 KakaoTalk 登录运行**：所有发送接口都要求本机 KakaoTalk 已登录并运行。
5. **发送动作完成 ≠ 对方已读**：响应无 `delivered` 字段，仅表示 UI 操作完成。
6. **路径建议使用正斜杠**：Windows 路径用 `C:/...` 格式，避免反斜杠转义问题。
7. **上传文件会落盘**：`/send/materials/upload` 会把上传的文件保存到允许目录下，需定期清理过期文件。
8. **安全**：禁止把 8765 端口映射到公网；建议防火墙只放行业务服务器 IP。
