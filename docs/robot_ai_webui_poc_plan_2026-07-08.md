# Robot AI WebUI POC 计划(原始版)

> 日期:2026-07-08
> 来源:用户制定
> 状态:待评审 → 见 `robot_ai_webui_poc_plan_reviewed_2026-07-08.md`

## 总体目标

把旧项目里"机械手知识库 + 指令解析 + 流程 + 安全门禁 + ZMotion 真机协议"迁移到当前 `nanobot-main-1`,但前端继续用现有 React WebUI + Nanobot gateway/WebSocket。第一阶段不做语音、不做 pywebview、不打包 exe,先跑通:

`WebUI 聊天 -> LLM -> robot tool -> planner -> dry-run -> 用户确认 -> ZMotion 真机执行`

## 架构原则

- LLM 只能生成计划和调用受限工具,不能直接真写控制器。
- 真执行必须由 WebUI 后端确认接口或人工 CLI 触发。
- `alarm_reset` 保留 CLI/planner 人工恢复用,不暴露给 LLM/WebUI。
- 第一阶段 WebUI 只用聊天窗口;第二阶段再加状态面板。
- 旧项目数据不硬塞进 Nanobot 通用 memory,单独建 `robot_ai` 的机器人知识/流程/位置/安全数据层。

## 旧项目迁移映射

| 旧项目数据/模块 | 迁移目标 | 用途 |
|---|---|---|
| `assistant_knowledge_base.json` | `robot_ai/knowledge/base.py` + `~/.nanobot/robot_ai/knowledge.json` | 问答知识、安全边界、操作说明 |
| `operator_agent_knowledge.json` | `robot_ai/knowledge/operator.py` | 机器人领域系统提示 |
| `operator_agent_skills.json` | `robot_ai/knowledge/skills.py` | 可执行能力说明,不直接位姿收敛 |
| `agent_memory.sqlite3` / `operator_agent_execution_memory.jsonl` | 暂缓,只迁移摘要/高价值记录 | 不先引入自动学习复杂度 |
| `voice_wake_words.json` | 文本唤醒词门禁 | 暂不做语音,但可复用唤醒词文本 |

## 阶段 0:先封住产品边界

目标:当前 WebUI 里 LLM 只能看到机器人相关工具。

要做:
- 修改 `ToolLoader` 或新增机器人模式配置,例如 `NANOBOT_ROBOT_MODE=1`。
- robot 模式只注册:`robot_arm`、`robot_flow`、可选只读 `robot_knowledge`、可选只读 `robot_position`。
- 禁用通用工具:`exec`、`apply_patch`、`web_search`、`web_fetch`、`generate_image`、`cron`、`spawn`、`read_file/write_file/edit_file` 等。
- 加测试:机器人模式下工具列表不包含任何非机械手工具。

验收命令:
```powershell
.\.venv-robot-desktop\Scripts\python.exe -m pytest tests/robot_ai -q
```

## 阶段 1:迁移知识库

目标:让 AI 回答和规划时能用旧项目知识,但不让知识库直接变成可执行权限。

要做:
- 新建 `robot_ai/knowledge/`:`models.py`、`loader.py`、`query.py`、`migration.py`。
- 写迁移脚本:读取旧项目 `data/*.json` → 转成 `~/.nanobot/robot_ai/knowledge.json`,保留来源字段、版本、更新时间。
- Nanobot 启动时把机器人知识摘要注入 system prompt。
- 增加只读工具 `robot_knowledge`,查询:安全边界、操作说明、错误码、流程说明、位置说明。

验收:
- 输入"机械手有哪些安全限制",AI 能基于旧知识库回答。
- 输入"报警码 ALARM_ACTIVE 是什么",AI 返回旧项目错误解释。
- 不产生任何 ZMotion 写入计划。

## 阶段 2:迁移位置库

目标:支持"移动到 A 点 / 查询 A 点坐标 / 保存当前位置为 A 点"。第一阶段先做查询和移动,不做 LLM 保存真实位置。

要做:
- 新建 `robot_ai/positions/registry.py`。
- 迁移旧 `position_registry.json` 到 `~/.nanobot/robot_ai/positions.json`。
- 加只读/受限工具:`robot_position list`、`robot_position get`、`robot_position resolve`。
- `robot_arm linear_move` 支持由命名位置解析成 108 target_pose。
- 保存当前位置先放到 WebUI 后端按钮,不让 LLM 自动保存。

验收:
- "查询位置 A 坐标"只返回坐标。
- "移动到位置 A"生成 108 dry-run plan。
- 如果位置不存在,AI 不能编造坐标,必须提示未找到。

## 阶段 3:迁移流程库

目标:完整支持旧项目流程:注册、查询、确认、dry-run、人工执行。

当前 `robot_flow` 已有基础,继续增强:
- 导入旧 `flow_registry.json` / `flows.json`。
- 支持 `flow_phrase_aliases.json`,例如"执行上料流程"解析为具体 flow。
- 流程步骤只允许:104 特殊动作(急停/暂停/继续/解除急停/解除取消/停止当前)、108 直线插补、110 延时、120 IO。
- 禁止 `alarm_reset` 进入流程。
- LLM 路径永远 dry-run。
- 真执行由 WebUI 后端确认接口触发。

验收:
- "列出流程"返回旧流程。
- "预演上料流程"逐步 dry-run。
- "执行上料流程"如果没有 WebUI 确认,只能返回待确认计划。
- 流程里出现 `alarm_reset` 必须拒绝。

## 阶段 4:执行门禁接 WebUI

这是"骨架"要补实。

要做:
- 新增 `robot_ai/execution/session_gate.py`。
- WebUI 每个 session 记录:用户是否登录、是否操作员权限、最近一次唤醒词是否有效、当前 pending plan id、当前 plan 是否已 dry-run、用户是否点了确认按钮。
- `_run_safety_gate()` 不再硬编码 `has_wake_word/permission_ok/bounds_ok/safety_ok=True`,改成来自 WebUI session / pending plan / safety result。
- 真执行必须满足:同一 session、同一 plan id、plan 未过期、dry-run 与 execute 参数哈希一致、用户确认工作区清空、用户确认急停可用、用户输入或按钮确认、后端生成确认码(不由 LLM 生成)。

验收:
- 未登录不能真执行。
- 没唤醒词不能真执行。
- 没 dry-run 不能真执行。
- LLM 伪造 `EXECUTE_ZMOTION_REAL` 无效。
- 改参数后旧确认失效。

## 阶段 5:WebUI 第一阶段,只用聊天跑通

目标:不做复杂控制台,先跑核心链路。

流程:
1. WebUI 启动。
2. 输入:"机械手移动到 x=900 y=0 z=999 rx=0 ry=0 rz=0"。
3. LLM 调 `robot_arm linear_move`。
4. 后端读取真机状态。
5. 生成 108 dry-run plan。
6. 返回:目标位姿、当前位姿、安全检查、写入 VR/IEEE 摘要、blockers 解释、"未执行真实运动"。
7. 用户确认后,WebUI 后端执行同一个 plan。

验收命令:
```powershell
.\.venv-robot-desktop\Scripts\python.exe tools\verify_zmotion_readonly.py --read-only-diagnostics --host 10.168.3.21 --json
```

> 注:原计划此处提到 `verify_zmotion_control.py --help` 行为异常,需先补安全参数再作为正式验收工具。

## 阶段 7:stop_current idle 防护

优先级很高,已经出现过锁存。

要做:
- 在 operator 层判断当前状态。
- 如果控制器 idle 且没有正在执行的 Func,拒绝 `stop_current`。
- `release_cancel` 只在 cancel latch 存在时允许。
- 加测试:idle 下 stop_current 拒绝、executing 下允许、无 latch 下 release_cancel 拒绝、有 latch 下允许。

## 阶段 8:WebUI 第二阶段状态面板

聊天链路跑通后再加:连接状态、当前位姿、急停/暂停/报警状态、最近一次计划、dry-run/execute 状态、执行日志、pending plan 确认按钮、急停按钮固定可见。先做只读状态 + 确认执行按钮,不做复杂编辑器。

## 阶段 9:删除无关功能

等机器人模式稳定后再物理删除:非 WebUI 渠道(Telegram/飞书/微信/Slack/Discord/Email 等)、非机器人工具(shell/文件编辑/搜索/图片生成/cron/spawn)。语音/STT/TTS 暂缓;pywebview/桌面壳暂缓;exe 打包暂缓。文档和测试也按模块裁剪。

## 当前最合理的执行顺序

1. 机器人模式工具白名单。
2. 旧知识库/位置库/流程库迁移脚本。
3. `robot_knowledge` / `robot_position` 只读能力。
4. WebUI session 执行门禁。
5. pending plan + 确认执行接口。
6. stop_current idle 防护。
7. WebUI 聊天 dry-run E2E。
8. 真机小步执行。
9. 连续插补、IO、延时、系统动作。
10. 状态面板。
11. 删除无关模块。

建议下一步先做 **1 + 2 + stop_current 防护**:这三件事不依赖控制器重启,却能把产品边界、旧知识迁移入口和真机风险先稳住。
