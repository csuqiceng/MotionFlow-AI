# Robot Server 重写：阶段 1 基线与范围冻结

日期：2026-07-23
分支：`codex/robot-server-rewrite`
状态：已完成，作为阶段 2 的回归对照

本报告冻结重写开始前的行为、接口和已知质量债。它不把既有失败误报为后续迁移回归；每项失败均有归类。

## 1. 可复现检查结果

| 检查 | 结果 | 备注 |
|---|---:|---|
| Python `pytest -q --tb=short` | 4,646 passed / 24 skipped / 13 failed | Python 3.14.6；为避免用户真实会话污染，仅隔离了 `HOME`/`USERPROFILE`，未设置 `NANOBOT_HOME`。耗时 4:10。 |
| Windows 时区依赖 | 已修复 | `tzdata>=2025.2` 已加入项目依赖；修复前有 25 个 cron 用例因 Windows 缺少 IANA zoneinfo 而失败。 |
| WebUI `bun run test` | 5 failed | 均在 `src/tests/thread-shell.test.tsx`；其余套件通过。 |
| WebUI `bun run build` | 通过 | 有循环 chunk 与大于 500 kB 的提示，非构建失败。 |
| WebUI `bun run lint` | 30 errors | 既有未使用变量、`any`、Hooks 顺序等规则错误。 |
| Electron `bun run build` | 通过 | `tsc -p tsconfig.json`。 |
| 既有安装包 `verify-release.ps1` | 不通过 | 检查脚本硬编码要求 `python311.dll`，而当前构建环境为 Python 3.14；列为阶段 7 打包回归项。 |

### Python 失败分类（13 项）

| 分类 | 用例 / 数量 | 处理决定 |
|---|---|---|
| 旧 WebUI/鉴权行为 | `test_webui_automations_route_*`（2）、`test_bootstrap_password_session_cannot_create_cron_job`（1） | 保留为旧 gateway 行为债；阶段 5/6 重新以协议契约测试覆盖。 |
| 已删除或变动的内部接口 | `test_module_level_normalize_uses_default_config`（1） | 测试仍依赖已不存在的 `_DEFAULT_CONFIG_PATH`；阶段 2 不以此接口为平台契约。 |
| 配置路径隔离的测试顺序耦合 | `test_config_paths.py`（3）、`test_execution_mode_config.py`（2）、`test_login_preflight.py`（1） | 测试依赖进程级配置路径；阶段 3 前应改为显式配置夹具。 |
| 宿主工具集 / 沙箱假设 | `test_tool_loader.py`（1）、`test_gitstore.py`（1） | 前者期待完整 Codex 工具集，后者被受限环境拒绝创建 git worktree；不构成机器人行为回归。 |
| gateway 启动配置约束 | `test_gateway_webui_smoke.py`（1） | 子进程配置路径与 `NANOBOT_HOME` 不一致；正是阶段 3 要移除的 gateway 运行模型。 |

阶段 2 开始前的质量门槛：平台核心与机器人相关测试不得新增失败；上述问题不允许被“忽略”，其替代测试或删除决定必须随相应迁移提交落地。

## 2. 子系统去向确认

| 当前子系统 | 证据 / 现状 | 目标归属 | 阶段 |
|---|---|---|---|
| `robot_ai/`（backend、安全、流程、位置、命令库） | 是产品核心，但存在反向 `nanobot.*` 依赖 | `robot_platform/` | 2、8 |
| AgentLoop、Provider、Session、memory、自动压缩 | 多渠道消息对象仍在边界处出现 | `ai_runtime/` | 2.5、6、8 |
| Dream / cron / local triggers | 保留调度；不得再携带渠道投递语义 | `robot_server/scheduler` | 3、6 |
| WebUI HTTP 与 JSON WebSocket | 当前入口为 `channels/websocket.py` + `webui/ws_http.py` | `robot_server/api`、`robot_server/ws` | 3–5 |
| 用户、登录、工程师权限 | `robot_ai.library.auth` 与机器人 API 共用 | `robot_server/auth` | 3、4 |
| MCP、skills | 可选 AI 扩展，默认最小权限 | `ai_runtime` + 受控服务 API | 6 |
| email、pairing、渠道插件发现、ChannelManager | 单页面/Electron 产品未使用 | 删除，不迁移 | 8 |

未在此表或主方案中认领的子系统不得删除。

## 3. 配置迁移映射

| 当前字段 / 数据 | 目标字段 / 数据 | 迁移规则 |
|---|---|---|
| `gateway.host`、`gateway.port`、`gateway.heartbeat` | `server.host`、`server.port`、`scheduler.heartbeat` | 新服务仅使用单端口；旧字段只读兼容一次，不再写回。 |
| `channels.websocket.*` | `server.ws.*` | 迁移 token、帧大小、ping、TLS 与本地绑定；不迁移渠道身份和 `allow_from` 语义。 |
| `channels.send_progress`、`send_tool_hints`、`show_reasoning` | `agent.stream.*` | 转为 Agent 运行时事件开关。 |
| `channels` 中的各外部平台 | 无 | 迁移报告应明确标注“已删除”。 |
| `agents.defaults`、`model_presets` | `agent.defaults`、`agent.model_presets` | 保留模型、上下文、压缩、时区和会话策略；`unified_session` 改为 Web 会话策略。 |
| `providers.*` | `providers.*` | 原样迁移，密钥保持脱敏；迁移前备份。 |
| `tools.*`、`mcp_servers` | `tools.*`、`agent.mcp_servers` | 默认仅注册机器人必要工具；MCP 最小权限。 |
| `transcription`、`tts` | `agent.audio.transcription`、`agent.audio.tts` | 仅保留单页面语音输入/输出所需能力。 |
| `api.*` | `compat.openai_api.*`（可选） | 不是产品主入口；按需兼容。 |
| `robot_ai.engineer.*` | `auth.engineer.*` | 工程师认证独立于机器人模型。 |
| `tools.execution_mode`、`~/.nanobot/robot_ai/*` | `robot.safety.execution_mode`、`robot_platform` 数据目录 | 控制器写入默认关闭；命令、流程、位置、审计迁移前备份并校验。 |

每次实际迁移须产出：原配置备份、字段转换结果、未识别字段清单、数据校验结果。

## 4. 现有外部接口清单

### WebSocket（JSON 文本帧）

服务端：`nanobot/channels/websocket.py`；前端连接封装：`webui/src/lib/nanobot-client.ts` 与 `webui/src/lib/bootstrap.ts`。

| 方向 | 事件 / 帧类型 | 兼容要求 |
|---|---|---|
| 客户端 → 服务端 | `auth`、`new_chat`、`fork_chat`、`attach`、`set_workspace_scope`、`transcribe_audio`、`message` | 阶段 5 先保持字段与错误语义。 |
| 服务端 → 客户端 | `ready`、`auth_ok`、`attached`、`error`、`session_updated` | 登录、会话恢复和权限错误必须可回归。 |
| Agent 流 | `message`（`answer` / `progress` / `tool_hint`）、`delta`、`stream_end`、`reasoning_delta`、`reasoning_end`、`file_edit`、`turn_end` | 阶段 5 旧 gateway 为数据源，阶段 6 无改动切换至 `AgentRuntime`。 |
| 状态同步 | `goal_state`、`goal_status`、`runtime_model_updated` | 作为前端兼容契约，后续再版本化简化协议。 |

### HTTP 路由族

| 路由族 | 当前实现 | 前端调用入口 | 迁移去向 |
|---|---|---|---|
| `/webui/bootstrap`、静态资源、`/api/login/preflight` | `webui/ws_http.py` | `lib/bootstrap.ts` | `robot_server/app.py`、`auth` |
| `/api/auth/*`、`/api/users/*` | `robot_routes.py` + `ws_http.py` | `lib/bootstrap.ts`、`lib/users-api.ts` | `robot_server/auth`、`api/users.py` |
| `/api/robot/status`、`pending-plan`、`confirm`、`execute`、`system-action` | `robot_routes.py` | `lib/robot-api.ts`、`RobotControlPanel.tsx` | `api/status.py`、`api/execution.py` |
| `/api/robot/flow-*` | `robot_routes.py` | `lib/robot-api.ts` | `api/flows.py` |
| `/api/robot/library/*`、`executions/*` | `robot_routes.py` | `lib/robot-library-api.ts` | `api/library.py`、`api/execution.py` |
| `/api/robot/engineer/*` | `robot_routes.py` + `ws_http.py` | `lib/engineer-workbench-api.ts` | `api/engineer.py`、`api/diagnostics.py` |
| `/api/settings/*`、`/api/webui/*`、`/api/sessions/*`、`/api/commands`、`/api/workspaces`、`/api/media/*` | `webui/settings_routes.py`、`webui/ws_http.py` | `lib/api.ts` | 先兼容；阶段 6 后按产品功能裁剪 |
| `/v1/chat/completions`、`/v1/models`、`/health` | `nanobot/api/server.py` | 无产品主 UI 依赖 | `compat`（可选）、`/health`（保留） |

### 前端调用点结论

机器人页面集中在 `webui/src/lib/robot-api.ts`、`robot-library-api.ts`、`engineer-workbench-api.ts` 与 `webui/src/robot/`。通用聊天页面仍大量依赖 `webui/src/lib/api.ts`、`nanobot-client.ts` 和会话组件。因此阶段 5 必须先提供服务端兼容层，不能在同一变更中重写前端协议。

## 5. 阶段 7 打包回归清单

- 将 `GatewaySupervisor`、`nanobot_gateway.exe`、双端口环境变量替换为单一 `RobotServerSupervisor` 与 `robot_server.exe`。
- 修正 `verify-release.ps1` 的 Python DLL 版本假设，改为由实际 PyInstaller 产物或版本化清单验证。
- 保留并自动检查 WebUI `dist`、Jinja 模板、机器人默认数据、ZMotion SDK；这些均来自 `desktop/PACKAGING-ISSUES.md` 的既有风险。
- 验证首次启动、登录、模拟执行、真实只读诊断、退出后无残留子进程。
