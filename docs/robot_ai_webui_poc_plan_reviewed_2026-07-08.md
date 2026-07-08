# Robot AI WebUI POC 计划 — 评审 + 修订版

> 日期:2026-07-08
> 评审对象:`robot_ai_webui_poc_plan_2026-07-08.md`(用户原始计划)
> 评审依据:实际读了 `loader.py` / `runner.py` / `context.py` + 已完成的 Phase 1-3 + 真机测试结果

## 一、总体评审结论

**计划整体成立,分阶段合理,架构原则正确。** 与已建成的 `robot_ai`(安全门禁 + V5.0 协议 + 流程引擎)+ 已封口的 LLM 工具面(dry-run only、alarm_reset 不暴露)完全一致。可执行性高。

关键判断:
- **Phase 0(产品边界)最容易且杠杆最高** —— 框架原生支持,先做。
- **Phase 4(执行门禁接 WebUI)是最难也是真执行的关键路径** —— session 透传有现成机制(`set_context(ctx)`),但 pending-plan + 后端确认码要新建。
- **stop_current idle 防护** 独立、不依赖控制器,且已造成过锁死 —— 提前到第一批。
- **真机小步执行(Phase 5 步 8)** 仍卡在控制器死锁(LONG36 bit5 取消锁存),需先断电重启。

## 二、逐阶段评审(可行性和集成点)

### Phase 0 — 机器人模式工具白名单 ✅ 可行,容易
**集成点**:`loader.py` 的 `load()` 已有三个过滤钩子:
- `tool_cls.enabled(ctx)` —— 工具按 ctx 决定是否注册(**最干净**,ctx 带 robot-mode 标志即可)。
- `tool_cls._scopes` —— `load(scope="robot")` 按 scope 过滤。
- `_plugin_discoverable = False` —— 单个工具类关闭发现。

**建议**:用 `enabled(ctx)` + ctx 读 `NANOBOT_ROBOT_MODE`。非机器人工具的 `enabled()` 在 robot 模式返回 False。无需删代码,纯配置驱动。测试用 `ToolLoader().discover()` + 过滤后断言只含 robot_*。

### Phase 1 — 知识库迁移 ✅ 可行
**集成点**:`ContextBuilder.build_system_prompt()`(context.py:66)+ `BOOTSTRAP_FILES=[AGENTS.md, SOUL.md, USER.md]`。
**建议**:
- 静态摘要写进 `SOUL.md` 或 `AGENTS.md`(机器人领域提示)。
- 动态知识(错误码/位置/流程说明)用只读 `robot_knowledge` 工具按需查 —— 比"全量塞 system prompt"更省 token。
- 迁移脚本读旧 `data/*.json` → `~/.nanobot/robot_ai/knowledge.json`,保留 source/version。
**风险**:旧知识 JSON 形状各异,迁移要逐个适配(我读过 position_registry/controller_error_map,形状 OK;assistant_knowledge_base 需核实)。

### Phase 2 — 位置库迁移 ✅ 可行
**集成点**:`robot_arm` 工具加 `position` 参数 → 查 `positions.json` → 解析成 target_pose。
**建议**:
- `robot_ai/positions/registry.py`(照旧 `position_registry.json` 结构)。
- `robot_position` 只读工具(list/get/resolve)。
- `robot_arm linear_move` 加可选 `position` 名字参数;有 position 就解析成 pose(与 target_pose 二选一)。
- 保存位置 = operator-only(WebUI 后端按钮,不进 LLM)。
**已验证**:旧 position_registry 有 A/B/C/HOME/rest_pose,坐标已知。

### Phase 3 — 流程库迁移 ✅ 可行(已有基础)
**现状**:`robot_flow` 已建(register/list/get/delete/confirm/run + dry-run 强制 + alarm_reset 步骤拒绝)。
**要补**:
- 导入旧 `flow_registry.json`/`flows.json`(迁移脚本)。
- `flow_phrase_aliases.json` 支持("执行上料流程" → flow 名)。
- 步骤白名单:func_id ∈ {108,104,110,120};104 的 action ∈ {急停/解除急停/暂停/继续/停止当前/解除取消},**排除 alarm_reset**(已做)。
**注意**:旧流程步骤可能是自由文本(依赖旧 NLP 解析),新系统用结构化 step;迁移时只导入结构化的,自由文本的标注为"需重新教学"。

### Phase 4 — 执行门禁接 WebUI ⚠️ 可行但最重,是关键路径
**集成点**:
- `runner.py` 的 run 带 `session_key`/`channel`/`sender_id` —— **session 身份已能透传到 agent**。
- 工具经 `set_context(ctx)` 拿到 ctx —— **工具能读 session**。
- 所以 `_run_safety_gate` 能从 ctx 拿 session → 查 session_gate。

**要新建**:
1. `robot_ai/execution/session_gate.py` —— session 状态(登录/操作员权限/唤醒词/pending plan id/dry-run 过/确认过)。
2. `robot_ai/execution/pending_plan.py` —— plan 暂存(plan id → plan + 参数哈希 + dry-run 时间 + 过期 + 确认状态)。
3. 后端确认接口(bridge 的 `operator_*` 扩展):WebUI 点确认 → 后端校验 session+plan+哈希 → 生成确认码 → 执行同一 plan。
4. `_run_safety_gate` 改:从 session_gate 取 `has_wake_word`/`permission_ok`/`confirmed`,不再硬编码。

**风险/要点**:
- 确认码**后端生成**(plan id 派生),LLM 传的 `EXECUTE_ZMOTION_REAL` 在 LLM 路径**无效**(robot_arm/robot_flow 都强制 dry-run,根本不读确认码)。
- dry-run 与 execute 参数哈希一致 —— 防止"dry-run A,execute B"。
- 这是 Phase 5"确认后执行同一 plan"的前置。

### Phase 5 — WebUI 聊天 dry-run E2E ✅ 大部分已验证
**已验证**:聊天 → LLM 调 robot_arm → dry-run plan + 安全检查 + blockers 解释(干净 session 实测 LLM 报告正确)。
**未做**:"用户确认后执行同一 plan" —— 依赖 Phase 4。
**清理项**:计划里 `verify_zmotion_control.py --help` 那段描述混乱 —— 该脚本是 operator CLI(system/linear-move 子命令),`--help` 正常显示用法;矩阵是 `verify_zmotion_motion_matrix.py`。验收工具用 `verify_zmotion_control.py` + `verify_zmotion_readonly.py` 即可。

### Phase 7 — stop_current idle 防护 ✅ 可行,独立,高优先
**集成点**:`run_zmotion_operator_command` 已读 `state`(mode + alarms)。在 `_build_plan` 的 system 分支前加:
- `stop_current` + mode==idle → 拒绝(`stop_current_not_allowed_when_idle`)。
- `release_cancel` + 无 cancel latch(bit27/system_state bit5 都为 0)→ 拒绝。
**已造成过锁死**,优先做。

### Phase 8 — 状态面板 ✅ 前端工作,依赖 Phase 4
bridge 已有 `health`/`get_robot_state`/`operator_*`。加 React 组件读这些 + pending-plan 确认按钮。先只读 + 确认按钮。

### Phase 9 — 删除无关功能 ⚠️ 最后做,先别物理删
Phase 0 已"禁用"。物理删除 nanobot 内置工具/渠道有破坏框架风险。建议:**Phase 0 禁用即可,Phase 9 物理删除推迟到机器人模式长期稳定后**,且只删渠道(Telegram 等),工具保留(禁用)。

## 三、计划缺失/风险补充

1. **控制器死锁**:当前 LONG36 bit5 取消锁存,所有运动 comp=3。Phase 5 步 8(真机小步执行) blocked,需先断电重启。**不阻塞 Phase 0/1/2/3/4/7(都不真写)**。
2. **pose-convergence 已修但未在干净控制器复验**:控制器重启后重跑矩阵确认。
3. **HOME→REST 直连 comp=3**:运动学/路径问题,要么查可达性,要么走中间点(旧项目多段)。Phase 5 步 9 注意。
4. **Phase 0 的 ctx 要带 robot-mode 标志**:需把 `NANOBOT_ROBOT_MODE` 环境变量读进 AgentContext/gateway 启动,再传给 `enabled(ctx)`。这是 Phase 0 的隐藏前置。
5. **知识注入用 hook 还是 SOUL.md**:建议摘要进 SOUL.md(静态、版本可控),动态查询用 robot_knowledge 工具。不把全量知识塞 system prompt(费 token)。
6. **测试得用 venv python 跑**:`.venv-robot-desktop\Scripts\python.exe -m pytest`(loguru 门控测试才执行)。CI/验收命令统一用这个。

## 四、修订执行顺序(带依赖)

```
第一批(不依赖控制器,立即做):
  A. Phase 0   机器人模式工具白名单(enabled(ctx) + NANOBOT_ROBOT_MODE)
  B. Phase 7   stop_current idle 防护(+ release_cancel latch 检查)
  C. Phase 1   知识库迁移 + robot_knowledge 只读工具
  D. Phase 2   位置库迁移 + robot_position 只读工具 + robot_arm 位置解析

第二批(数据层完,做真执行关键路径):
  E. Phase 3   流程库迁移 + phrase aliases + 步骤白名单(增强 robot_flow)
  F. Phase 4   session_gate + pending_plan + 后端确认接口 + _run_safety_gate 接 session

第三批(控制器重启后,真执行验收):
  G. Phase 5   聊天→dry-run→确认→执行 同一 plan 的 E2E(依赖 F)
  H. 真机小步执行复验(依赖控制器重启)

第四批(UI + 收尾):
  I. Phase 8   状态面板 + 确认按钮(依赖 F 的 pending-plan)
  J. Phase 9   物理删除无关渠道(稳定后,只删渠道,工具保留禁用)
```

## 五、建议的第一批(A+B+C+D)具体动作

**A. Phase 0(产品边界)**:
- `nanobot/agent/tools/base.py` 的 `Tool.enabled(ctx)` 默认实现读 ctx 的 robot-mode;非 robot 工具在 robot 模式 `enabled` 返回 False。
- 或:新增 `NANOBOT_ROBOT_MODE` 环境变量 → gateway 启动读进 ctx → `ToolLoader.load(ctx)` 时非 robot 工具被 `enabled(ctx)` 拒绝。
- 测试:robot 模式下 `ToolLoader().discover()` 过滤后只含 `robot_arm`/`robot_flow`/`robot_knowledge`/`robot_position`。

**B. Phase 7(stop_current 防护)**:
- `zmotion_operator_control._build_plan`:system 分支前检查 state;`stop_current`+idle 拒绝;`release_cancel`+无 latch 拒绝。
- 测试:4 个用例(idle+stop→拒、executing+stop→允、无 latch+release→拒、有 latch+release→允)。

**C. Phase 1(知识库)**:
- `robot_ai/knowledge/{models,loader,query,migration}.py` + 迁移脚本。
- `~/.nanobot/robot_ai/knowledge.json`。
- `robot_knowledge` 只读工具(query: safety/operation/error_code/flow/position)。
- 摘要进 SOUL.md。

**D. Phase 2(位置库)**:
- `robot_ai/positions/registry.py` + 迁移 `position_registry.json` → `~/.nanobot/robot_ai/positions.json`。
- `robot_position` 工具(list/get/resolve)。
- `robot_arm` 加 `position` 参数(resolve → target_pose)。

**这四件都不依赖控制器重启,做完产品边界 + 旧知识入口 + 真机风险就稳了。** 然后第二批做 Phase 3/4(真执行关键路径)。

## 六、一句话

计划成立,顺序合理。**第一批做 Phase 0 + 7 + 1 + 2**(不依赖控制器,封边界 + 防 lockup + 迁知识/位置);**第二批做 Phase 3 + 4**(流程增强 + 真执行门禁,是"确认后执行"的关键路径);**控制器重启后做 Phase 5 真执行复验**;UI 面板和物理删除最后。
