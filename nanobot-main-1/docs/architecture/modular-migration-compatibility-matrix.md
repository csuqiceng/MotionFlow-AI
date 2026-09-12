# 模块化迁移兼容性矩阵

## 基线与判定原则

本矩阵以 **2026-07-26 当前已发布的简化 WebUI** 为唯一产品基线。迁移的目标是让这些仍受支持的页面、接口和安全行为保持不变；它不是恢复历史 Nanobot 控制台或已删除功能的项目。

- 已删除的旧设置、项目/工作区选择、旧草稿/归档工作流、文件选择图片附件、复制按钮和长按语音工作流，只保留跳过测试作为历史证据，不作为回归目标。
- 任何新增或移除当前支持页面的变更，都必须先更新本矩阵并完成产品验收；架构重构本身不得改变页面语义。
- 机械手真实动作不由自动化测试触发。自动化仅验证请求形状、安全拒绝和 dry-run；硬件验证须在批准窗口按发布清单执行。

| 用户页面或旅程 | 自动测试位置 | 人工验收步骤 | 预期结果 | 迁移阶段负责人 |
|---|---|---|---|---|
| 登录与首次改密 | `tests/robot_server/test_app.py`；身份与 Cron 安全测试 | 使用首次登录账户登录、改密，再创建自动任务 | 未改密前不能创建 Cron；改密后按角色可用 | 服务端/安全 |
| 会话创建、切换与删除 | `webui/src/tests/thread-shell.test.tsx` | 创建会话、切换、删除并刷新页面 | 会话列表与当前内容一致 | WebUI 契约化 |
| 流式对话 | `tests/robot_server/test_websocket_frame_contract.py`；`webui/src/tests/useNanobotStream.test.tsx` | 发送消息并观察状态、增量文本、工具进度和结束 | 所有支持的 WS frame 都被消费，界面不崩溃 | Agent/WebUI |
| 主控制台与机器人状态 | `webui/src/tests/app-layout.test.tsx`；`tests/robot_ai/test_platform_use_cases.py` | 打开主控制台，刷新机器人状态 | 当前简化页面显示状态且无历史设置入口 | Backend/ZMotion 隔离 |
| dry-run、确认执行与急停 | `tests/robot_ai/test_execution_gate.py`；`tests/robot_ai/test_pending_plan.py` | 生成 dry-run，尝试无确认执行，再按批准流程确认 | 无确认必拒绝；真实急停保持独立安全路径 | Backend/ZMotion 隔离 |
| 流程运行 | `tests/robot_ai/test_platform_use_cases.py`；后续 `test_flow_executor.py` | 从当前流程页启动允许的流程并观察进度 | 步骤级安全检查、停止条件与回调保持 | Backend/ZMotion 隔离 |
| 工程师命令与流程编辑 | `webui/src/tests/engineer-workbench.test.tsx`；`tests/robot_server/test_app.py` | 以工程师身份创建、编辑、删除命令和流程 | 直接保存工作流与当前权限行为不变 | 服务端/WebUI |
| 资产库与位置 | 现有 robot library/position 单测；后续 robot Tool 兼容测试 | 浏览、创建和使用当前资产/位置 | 数据与工具结果兼容，不加载厂商 SDK 到 Tool Core | Robot Tool 迁移 |
| 用户管理 | `tests/robot_server/test_app.py` | 管理员管理用户，工程师/操作员分别登录 | 角色、审计和会话限制不变 | 服务端/安全 |
| Settings 与自动任务 | `webui/src/tests/app-layout.test.tsx`；Settings/automation 相关单测 | 打开 Appearance、Voice、System、工程师 Security 与 Automations | Automations 可由主侧栏访问；不恢复旧 Settings 页面 | WebUI 契约化 |
| 桌面首次启动与打包应用启动 | `desktop/electron/tests/product-manifest.test.js`；`packaged-robot-server-launch.test.js`；`npm run verifyRelease`；`npm run smokePackagedRobotServer` | 安装包首次启动、完成向导、重启 | 单一 Robot Server、数据目录、配置种子、health 路径和 loopback UI 来源不变 | Electron 产品壳 |

## 自动化门禁状态

| 门禁 | 当前状态 | 说明 |
|---|---|---|
| WebUI unit + build | 通过（有既有 warning） | `48` 测试文件、`537 passed`、`33 skipped`；Vite 构建通过。KaTeX、React `act(...)`、连接测试和 chunk-size/circular-chunk warning 已记录，不影响断言结果。 |
| WebSocket frame 契约 | 通过 | `13 passed`；fixture 覆盖当前支持的运行时 frame。 |
| 后端 registry、核心隔离与安全精选回归 | 通过 | `145 passed`；核心 import 不再加载 ZMotion，真实写入安全门禁仍被覆盖。 |
| Python 全量 | 通过（有运行时 warning） | 项目桌面虚拟环境、worktree 外临时目录：`3583 passed, 23 skipped`。两条 Windows Python 3.14 Proactor 清理 warning 不影响断言，但已列入发布清单。 |
| Electron build/package smoke | 通过（本地占位密钥构建） | `npm run build`、`npm run dist`、`npm run verifyRelease`、`npm run smokePackagedRobotServer` 均通过；正式签名与人工首启仍属于最终发布清单。 |
