# Robotic Arm AI Platform

面向通用机械手的本地 AI 控制模板。产品只有一个本地 `robot_server`、一个单页控制
界面和一个 Electron 桌面壳；不包含聊天渠道、聊天网关或 DM 审批流程。

## 架构

```text
Electron / browser
        │ HTTP + WebSocket（单一 localhost 端口）
robot_server            # API、单页 UI、会话与服务进程
        │
ai_runtime              # 与传输层无关的 AgentRuntime 事件契约
        │
robot_platform          # 厂商无关的机器人平台与安全边界
        │
robot_platform/backends # simulation、ZMotion，以及未来厂商适配器
```

`nanobot/` 目前只保留 Agent 引擎的过渡性实现，不能作为产品入口或新业务模块的依赖。
新代码应依赖 `ai_runtime`、`robot_platform` 或 `robot_server` 的公开接口。

## 安全不变量

- 真实写入默认关闭；开发和新厂商接入先使用 simulation 或只读模式。
- 运动必须经过“规划 → 明确确认 → 执行”安全闸门，确认码与当前会话绑定。
- 急停始终通过独立 API/平台用例执行，不能被 Agent 的普通对话流程替代。
- 服务默认只绑定回环地址。若绑定到非回环地址，必须显式设置访问令牌。

## 本地启动

要求 Python 3.11+：

```powershell
python -m pip install -e ".[api]"
robot-server --port 8765
```

随后访问 `http://127.0.0.1:8765/`。开发阶段也可运行
`python -m robot_server.cli --port 8765`。

Electron 桌面端：

```powershell
cd desktop
npm install
npm run dev
```

桌面端会启动同一份 `robot_server`，不会再拉起第二个 gateway 进程。

## 管理命令

```powershell
robot-admin engineer set-password
robot-admin users set-bootstrap-password --username operator
```

密码从安全终端提示输入，不接受命令行明文密码。

## HTTP 接口边界

- `/api/robot/*`：状态、规划、确认、执行、急停和流程运行。
- `/api/library/*`：组件、已发布动作和流程的只读查询；草稿不会暴露给操作员。
- `/api/library/*` 还提供已发布动作/流程的受跟踪执行、进度查询与暂停/恢复/单步/停止/重置控制；执行记录按用户隔离。
- `/api/identity/*`：本地 operator/engineer 登录、登出、会话与工程师用户管理。
- `/api/management/*`：仅工程师可用的动作/流程草稿、校验、发布、复制、批量归档、库导入导出、位置清理与审计查询。

身份令牌通过 `X-Robot-User-Token` 传递；它与可选的服务访问令牌分离。首次身份
登录会初始化禁用的账户记录，必须先运行 `robot-admin` 设置密码后才能使用。
真实执行必须由调用方提供确认码与两项现场确认，服务端不会替客户端填入确认凭据。

## 测试

```powershell
desktop\.build-venv\Scripts\python.exe -m pytest tests\robot_ai tests\robot_server -q
```

详尽的重构计划和阶段验收记录见
[`docs/superpowers/plans/2026-07-23-robot-server-rewrite.md`](../docs/superpowers/plans/2026-07-23-robot-server-rewrite.md)。

## 新厂商接入

在 `robot_platform/backends/<vendor>/` 实现厂商适配器，并只通过 `RobotPlatform` 的公开用例
暴露：`get_status`、`plan_motion`、`execute_confirmed_plan`、`emergency_stop` 和
`run_flow`。不要让 UI、AgentRuntime 或 HTTP 路由直接调用厂商 SDK。
