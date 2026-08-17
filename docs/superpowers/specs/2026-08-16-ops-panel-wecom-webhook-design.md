# Kakao Agent 运维面板 + 企业微信 Webhook 设计

**日期:** 2026-08-16  
**状态:** 已批准（对话确认：A tkinter + 面板与 webhook 一起）

## 目标

目标 Windows 机器上用简单窗口启停 HTTP Agent、改配置并落盘；业务/鉴权失败时异步推企业微信群机器人。

## 运维面板（tkinter）

- 普通小窗口：状态（Agent / KakaoTalk）、Host、Port、API Key、Allow IPs、Webhook URL
- 按钮：保存配置、启动、停止、刷新状态
- 配置文件：可执行文件（或项目）旁 `agent.env`；保存后下次启动自动读
- 启动 = 子进程运行 `python -m kakao_mcp.api`（打包后为同目录逻辑）；停止 = 结束该子进程
- 约每 3 秒请求本机 `/health` 刷新指示（仅展示，不做探活告警）
- 改配置后若 Agent 在跑：提示需停止再启动后生效

## 企业微信 Webhook

- 配置：`KAKAO_AGENT_WEBHOOK_URL`（env / agent.env）；空 = 关闭
- 触发：HTTP **401/403/5xx**，或 JSON body `success: false`（含业务失败）
- 格式：企业微信 `msgtype: markdown`
- 异步发送，失败不影响 API 响应；超时短（约 5s）
- 不因 `/health` 成功轮询而推送

## 非目标（本版不做）

- 托盘图标、发送测试台、服务器侧探活实现、PyInstaller 一键脚本可后补说明

## 文件

- `src/kakao_mcp/config.py` — `webhook_url`
- `src/kakao_mcp/envfile.py` — 读写 `agent.env`
- `src/kakao_mcp/webhook.py` — 企业微信通知
- `src/kakao_mcp/api.py` — 失败中间件
- `src/kakao_mcp/panel.py` — tkinter UI
- `pyproject.toml` — `kakaotalk-panel` 入口
