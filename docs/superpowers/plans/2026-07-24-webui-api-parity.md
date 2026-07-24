# 保留 WebUI 的直连接口完整迁移清单

目标：保留现有 React/Electron 页面与交互，不恢复 gateway、聊天渠道或 DM 审批；每个页面直接由 `robot_server` 提供同进程 HTTP/WebSocket 服务。

## 已完成

| 页面/能力 | 新直连接口 |
|---|---|
| 登录及 AI 连通性检查 | `/webui/bootstrap`、`/api/auth/*`、`/api/login/preflight` |
| AI 对话流 | `/webui` WebSocket → `AgentRuntime` |
| 机器人状态、命令库、执行记录 | `/api/robot/status`、`/api/library/*` |
| 工程师命令/流程/审计/诊断 | `/api/management/*` |
| 账户管理 | `/api/identity/*` |

| 会话侧栏、搜索、删除、消息历史 | `/api/sessions/*` | 本地 Agent 会话与 WebUI 转录存储 |
| 自动任务 | `/api/webui/automations/*` | 同进程 `nanobot.cron` 适配器；新模板默认向 AI 开放 `cron` 工具 |
| 设置（模型、Provider、搜索、网络安全、图像、转录） | `/api/settings/*` | 本地配置读写；敏感字段只写不回显 |
| CLI 应用与 MCP | `/api/settings/cli-apps/*`、`/api/settings/mcp-presets/*` | 本地应用管理与完整 12 项 MCP 内置目录 |
| 技能目录、工作区、侧栏偏好 | `/api/webui/skills/*`、`/api/workspaces`、`/api/webui/sidebar-state/*` | 本地只读投影与每用户偏好 |
| 文件预览、签名媒体、Slash 命令 | `/api/sessions/*/file-preview`、`/api/media/*`、`/api/commands` | 工作区受限读取、本地签名与运行时命令清单 |
| 语音录制转写 | `/webui` WebSocket 的 `transcribe_audio` 帧 | 保留原请求/响应协议；登录页只做安全的本地配置就绪检查 |
| 手动机器人流程 | `/api/robot/flow-*` | 三段式计划—确认—执行；旧 `/flows/run` 仅保留 dry-run，不能绕过确认链 |

## 验收记录（2026-07-24，最终回归）

- 后端接口验收：`33 passed`（含设置、自动任务、MCP 目录、语音协议、旧侧边栏状态接口与流程安全门）。
- 页面路由契约：`tests/robot_server/test_app.py` 覆盖保留页面所需的登录、会话、设置、自动任务、命令库、工程师工作台和机器人操作路由；当前 `28 passed`。删除任一直接服务端路由会在测试中失败，而不会留到 Electron 页面中才暴露为 404。
- 前端全量回归：所有测试文件通过；生产 WebUI 构建成功。
- 桌面端：TypeScript 编译、启动器测试和打包启动参数测试均通过；开发模式已重启，直连 `robot_server` 的 `/health` 返回 `ok`。
- 原页面交互回归：侧边栏搜索、跨会话搜索弹窗、会话偏好、项目选择、工作区访问、图片附件、设置、自动任务和命令库均保留；不重写 WebUI 页面。
- 兼容性：会话自动任务继续使用原 `X-Nanobot-User-Token` 请求头；侧边栏状态同时保留旧的 `/api/webui/sidebar-state/update?state=...` 入口和新的 JSON POST 入口。
- 语音服务只有在设置页配置可用转写 Provider 后才显示为可用；这不会影响文本 AI 对话。

## 迁移不变量

- 任何真实机械手写操作必须继续经过计划、两项现场确认、服务端确认码与平台安全门。
- 不把 API Key、密码、OAuth 凭据或本地绝对路径泄露给浏览器。
- 不恢复 `nanobot.gateway`、`nanobot.channels` 或多渠道路由。
- 每项迁移必须有接口测试和对应页面的回归测试；完成后从本表移到“已完成”。
