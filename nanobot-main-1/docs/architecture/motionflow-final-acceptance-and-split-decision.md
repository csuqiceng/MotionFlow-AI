# MotionFlow 最终验收与物理拆包判定

日期：2026-07-29  
范围：解耦、组件化、扩展边界、兼容与发布准备。

## 1. 软件验收结论

> **APPROVE（软件解耦与组件化验收通过）。**
> 持久化 Tool 操作账本、Flow v2 产品执行链、可信审批、Feature Policy、
> 身份收紧、审计防篡改、唯一组合根和 Electron 产品壳边界均已通过新鲜门禁，
> 第十三轮全新独立评审未发现剩余 P1/P2。

单仓“模块化单体 + 稳定契约 + 显式插件”目标验收清单：

- 唯一 Composition Root 构造 Backend、Application、Tool Runtime、Agent Provider 和 Server Container；
- HTTP、AI Tool、Flow、CLI 与兼容入口共享安全边界，不存在第二条真实写入通道；
- Backend、Tool、AgentEngine、Flow Event 均有 vendor/SDK-neutral 合同与复用测试套件；
- Simulation、Dummy、ZMotion 通过统一 Backend contract；Nanobot、Fake、Scripted Provider 证明 AgentEngine 可替换；
- WebUI 通过 `@/robot` feature public API 接入，transport v1 保持兼容；Electron 产品默认、路径、图标、健康检查和 Server Command 只从 ProductManifest 取得；
- runtime migration rehearsal 只复制到空 scratch，保留 legacy/canonical 原数据，可生成机器可读报告；
- 公开 manifest/event fixture、依赖门禁、负向安全矩阵、WebUI/Electron build/smoke test 已纳入回归。
- v2 Flow 节点图已由 staged production execution 直接消费；条件/审批/超时控制真实派发，并行硬件副作用与物理动作自动重试在 schema 边界拒绝。
- Tool timeout 使用受监督 worker；物理调用超时后共享资源锁保持到 worker 真正结束，结果进入 unresolved scope，任何幂等键均不能自动重试。
- Backend deadline/cancellation 从 Tool worker 传播到 Platform、Backend call context 与 ZMotion 写入/轮询；deadline 后返回会把 Backend 标记为 `ERROR` 且上层保持 outcome unknown。
- 同一 Product Feature Policy 同时约束 Tool、Application port、HTTP catalog、Flow/Platform 和兼容入口，覆盖 arm、flow、knowledge、position、library 与 cron。

本轮新鲜自动化证据：Python 全部测试经隔离分片完整覆盖，合计 `3961 passed, 23 skipped, 1 deselected`（仅 2 个已知 Windows asyncio transport 清理 warning）；架构门禁 `90 passed`；WebUI lint、`554 passed, 33 skipped` 与 production build 通过；Electron TypeScript build 与 4 项 ProductManifest/controlled-injection/trusted-origin contract test 通过；compileall 与 `git diff --check` 通过。当前状态为 `GATES_PASSED / THIRTEENTH_REVIEW_APPROVED / APPROVE`。

第二次独立复审发现的 effect fingerprint session 绕过、重复 node ID、停止后补偿、非读 Tool 无幂等账本、unknown 无 reconcile 生命周期、Flow Port 协议缺失和公开 hash 可重算问题均已整改：设备级 effect fingerprint 不含 actor/session/request key；全图 node ID 强制唯一；所有 stop/cancel/timeout/unknown 均不可自动补偿；非读 Tool 双层强制 request idempotency；新增工程师授权且绑定服务端控制器读回证据的 reconcile API；审计改为日志目录外密钥的 HMAC-SHA256 链，并在启动、追加、读取时验证。

第三次独立复审进一步发现并关闭两项：reconcile 账本现持久化 controller ID、规范化 effect payload 与操作专属 readback predicate，服务器根据控制器证据计算可证明结论，调用方提交相反结论不会解除 embargo；所有新审计 append 均强制目录外 HMAC key，禁止同目录 key 配置，audit/migration ID 去重只信任已验签记录，未签名 legacy 行不能伪造已落盘事件。

第四次独立复审发现的公开 SHA 伪认证前缀与非原子去重已关闭：任何存在 `_audit_hash` 的记录必须声明并通过 `hmac-sha256`，纯历史 SHA 文件只会原样隔离为 untrusted evidence 后建立新 HMAC 恢复点；统一 `_audit_append_once` 在同一锁内完成验签、签名 ID 查询和条件追加，migration/command/flow/user outbox 均复用，16 路并发同一 ID 只有一次实际追加。

第五次独立复审所覆盖的坏 legacy SHA、Tool 参数噪声/别名与跨进程审计竞态已整改：legacy 隔离前完整重算 sequence/prev/hash；Tool 专属 canonical effect contract 统一 fingerprint、持久 payload 与 readback predicate；审计所有关键操作受跨进程文件锁保护。第六次复审随后发现其 legacy 判定仍遗漏“未链前缀 + 后续公开 SHA”混合格式，因此第五次结论不能单独作为最终关闭依据。

第六次独立复审的 legacy public-SHA 问题已关闭：隔离只接受从第一条开始、每条均带完整 seq/prev/hash 的纯公开 SHA 历史链，混合未链前缀一律原地 fail closed。该轮最初把 Runtime correlation ID 误写成 controller dispatch ID；这一不准确表述已撤回，并由第七轮的 Tool effect 状态机整改取代。

第七次独立复审的 unknown 生命周期与 named-position TOCTOU 已关闭：状态机为 `prepared → dispatch_claimed → terminal`，claim 前取消产生 `confirmed_tool_effect_not_started`，明确终态回执先于 terminal audit 和 result commit 持久化；Tool 执行消费首次冻结的 canonical payload，动态命名位置只解析一次。第八次复审随后证明跨进程 effect claim、anti-rollback、全部副作用 Tool canonical contract 与审计防截尾仍需加强，故第七次表述不作为最终批准依据。

第八次独立复审的 4 个 P1/2 个 P2 已完成整改、当时等待第九次全新复审确认：Tool store `begin` 在同一跨进程事务内原子检查 request key 与 unresolved effect fingerprint；schema v3 使用目录外 HMAC 单调 generation/sealed head，正常启动拒绝 unsigned v1/v2、旧有效快照、文件删除和 head 不匹配。审计链同样增加目录外 sealed head，删除最后记录、全部认证记录或恢复旧合法前缀均 fail closed。RobotArm/Flow/Cron/Library 均提供动作级 canonical contract，Flow alias 冻结为 name+snapshot hash，Cron 默认 name/timezone/schedule 和 Library 数字/别名归一；副作用 Tool 必须是受控 Application-only adapter 且显式提供 canonical contract。reconcile schema 只使用 `confirmed_tool_effect_completed/not_started`，不再声称 controller 物理执行；真实写入仍只允许 plan/confirm/permit/Application/Backend 链。

第十次复审补充关闭了存活 owner 的延迟恢复、canonical exception fail-open、Tool/audit 首次提交 genesis crash、reconciliation final audit 双写和 Cron concrete service 依赖：operation store 每次事务重新判断 owner PID，canonicalization 异常在 begin/dispatch 前失败；store/audit 都以 generation 0 sealed head 覆盖首次提交崩溃窗口；Cron Tool 只依赖 neutral Application port/DTO。

第十一次复审确认的 reconciliation outbox 与 Electron origin 两项 P2 已关闭：deterministic final-audit outbox 与 completed result 放进同一 HMAC store 事务，启动/访问自动 drain、append-once 后 ack，并为旧 completed 记录回填 outbox；Electron 麦克风权限绑定随机端口 exact origin 与唯一 mainWindow webContents，renderer 启用 sandbox，跨 origin 导航与所有新窗口均被拦截，只有 `http/https` 外链交由系统浏览器。第十二次复审继续发现 mixed-template 打包绕过和 Cron hidden composition，现已改为下述受控注入例外与显式 composition wiring，等待第十三次复审。

### 1.1 初版客户端内置 API 密钥临时例外

当前初版安装包按产品要求内置一个可直接使用的 API 密钥。这是**明确接受但必须受控的临时风险**：安装包或已安装客户端中的密钥可以被提取，不能视为秘密存储。

- Git 仓库与模板禁止真实密钥；模板必须且只能在 `providers.dashscope.apiKey` 保留唯一占位符。
- 受控打包环境必须从 `NANOBOT_ORGANIZATION_API_KEY` 取得密钥；缺失时打包失败。脚本解析 JSON 后只赋值该字段，禁止全文替换。
- 注入前后递归检查 provider credential 字段；混合密钥、第二占位符、其他非空凭据、非法类型或占位符拼接全部 fail closed；错误和日志不得包含密钥值。
- 正式使用必须配置**独立专用、限额、限流、可监控、可随时吊销**的密钥，不得复用开发者或其他产品凭据。此前进入版本历史的旧密钥必须在供应商侧吊销轮换。
- 服务端代理上线后必须删除客户端注入逻辑与内置密钥，切换为服务端代管，并立即吊销初版客户端专用旧密钥；该项是临时例外的退出标准。

## 2. 外部验收执行单

以下项目必须由受控工位负责人填写证据 ID，自动化测试不得冒充现场签核：

| 项目 | 当前状态 | 通过证据 |
|---|---|---|
| 初版专用 Key 限额/限流/监控/吊销配置 | `READY_NOT_VERIFIED` | 供应商侧策略截图、Key ID（不得记录值）、告警与吊销演练 ID |
| 历史泄露 Key 吊销轮换 | `REQUIRED_NOT_VERIFIED` | 供应商侧吊销事件 ID、新专用 Key ID（不得记录值） |
| 服务端代理退出客户端内置 Key | `PLANNED` | 代理上线证据、客户端注入删除 commit、初版专用 Key 吊销事件 ID |
| 脱敏生产 runtime 迁移/回滚演练 | `READY_NOT_RUN` | `runtime-migration-rehearsal.json`、源目录哈希、回滚计时 |
| ZMotion 只读连接与状态一致性 | `READY_NOT_RUN` | 控制器编号、固件、只读 smoke 报告 |
| dry-run 与计划快照核对 | `READY_NOT_RUN` | plan/snapshot hash、操作者签字 |
| 最小真实动作 | `READY_NOT_RUN` | 工位隔离记录、permit/audit/SDK 写入矩阵 |
| 急停、暂停、复位、断线恢复 | `READY_NOT_RUN` | 急停时延、状态位回读、审计 ID |
| 正式签名安装包首启/升级/回滚 | `READY_NOT_RUN` | 安装包哈希、签名、升级和回滚报告 |
| 第二个真实产品或独立使用方 | `NOT_AVAILABLE` | 产品负责人、独立配置与升级记录 |

执行前必须：隔离工位、清空无关人员、确认急停可达、备份 runtime、记录控制器固件与软件 commit；任何 `OUTCOME_UNKNOWN` 立即停止自动重试并进入人工 reconcile。

## 3. 推荐命令

```powershell
# 离线、只复制的迁移演练
.\desktop\.build-venv\Scripts\python.exe tools\rehearse_runtime_migration.py `
  --source-runtime D:\redacted-runtime `
  --scratch-root D:\migration-rehearsal\run-001

# 无写入 ZMotion 验证
.\desktop\.build-venv\Scripts\python.exe tools\verify_zmotion_readonly.py --host <controller-ip>

# WebUI / Electron 软件门禁
Set-Location webui; npm run lint; npm test -- --run; npm run build
Set-Location ..\desktop; npm run build
node electron\tests\product-manifest.test.js
node electron\tests\before-pack.test.js
node electron\tests\packaged-robot-server-launch.test.js
node electron\tests\trusted-origin-policy.test.js
```

真实动作只允许使用发布清单中的受控验收程序和一次性执行许可；不得从 REPL、原始 SDK、Flow 文件编辑器或 AI prompt 直接触发。

## 4. 物理拆包判定

结论：**NO-GO（暂不物理拆仓/拆 wheel/npm 包）**。

原因不是软件边界失败，而是主方案规定的两个外部门槛尚未满足：

1. 尚无本次变更后的受控真机完整签核；
2. 尚无第二个真实产品/独立使用方的跨项目升级证据。

因此保留当前模块化单体。Dummy Backend 与 Scripted Provider 只证明扩展合同可用，不能冒充第二个真实产品。取得上述证据后，只需重新执行本文件的外部验收表和主方案第 13 节门槛，不需要推翻现有架构。
