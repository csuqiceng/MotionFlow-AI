# AgentLoop 渠道耦合清单与去渠道化改造方案

日期：2026-07-23
对应计划：`2026-07-23-robot-server-rewrite.md` 阶段 2.5

## 结论

**Spike 通过。** `AgentLoop` 可由只依赖 `MessageBus` 的最小 Web 适配器独立驱动；不需要启动、导入或模拟 `ChannelManager`、`BaseChannel` 或外部聊天渠道。验证覆盖单轮、流式、工具调用、取消和错误返回，测试位于 `tests/agent/test_web_runtime_spike.py`。

这不是“所有渠道字段已经消失”的结论。当前 Agent 运行时仍复用 `InboundMessage`/`OutboundMessage` 的路由字段；因此阶段 6 应先替换消息契约和 WebUI 特化分支，再删除渠道实现，不能直接删目录。

## 实测边界

| 能力 | 最小 Web 适配器做法 | 结果 |
|---|---|---|
| 单轮和会话历史 | 投递固定 `channel="web"`、稳定 `chat_id`、`session_key_override="web:<id>"` 的 `InboundMessage` | 通过；会话键独立且稳定 |
| 流式输出 | 传入 `_wants_stream`，订阅 `StreamDeltaEvent`、`StreamedResponseEvent` | 通过 |
| 工具调用 | 订阅最终响应，AgentLoop 在内部调用 ToolRegistry | 通过 |
| 取消 | 用会话键调用现有 `_cancel_active_tasks` | 通过 |
| 错误返回 | 运行时异常被 `_dispatch` 规范化为用户可见错误响应 | 通过 |

## 耦合清单和处置

| 位置 | 当前耦合 | 阶段 6 处置 |
|---|---|---|
| `nanobot.bus.events.InboundMessage` | `channel`、`sender_id`、`chat_id` 是必填字段；`session_key` 默认拼接渠道和会话 ID | 新建面向运行时的 `RuntimeRequest(origin, actor_id, conversation_id, content, metadata)`；过渡期由适配器转换为现有消息 |
| `nanobot.bus.events.OutboundMessage` | `channel`、`chat_id` 负责回路由；`reply_to`、`buttons`、`media` 属于聊天表达能力 | 新建 `RuntimeEvent`；Web 端以事件订阅替代回路由，聊天专属表达留在已隔离的 legacy adapter |
| `AgentLoop` | 流式事件复制 `channel/chat_id`；唯一显式渠道分支是 `cli` 空回复、`system` 消息、Slack system 格式 | 将 CLI/system 变为运行时来源枚举和内部事件；移除 Slack 特例到 legacy adapter |
| `nanobot.session.webui_turns` | 多处硬编码 `channel == "websocket"`、`metadata["webui"]` | 阶段 6 改为订阅 `RuntimeEventBus`，不以 transport 名称判断 WebUI 行为 |
| `nanobot.agent.tools.message` | `websocket` 被当作消息工具默认目标 | Robot Server 不注册跨渠道 MessageTool；需要通知时使用显式 UI/runtime 事件 |
| `nanobot.command.builtin` | pairing 命令和回复均沿用聊天渠道字段 | 阶段 6 删除 pairing 命令，普通命令改为 Robot Server API / RuntimeEvent |
| `metadata` | `_wants_stream` 是运行时能力；线程 ID、`message_id`、`context_chat_id`、`origin_message_id` 是渠道元数据；自动化字段混在同一 dict | 将 `_wants_stream` 升为 `RuntimeRequest.stream`; 将聊天元数据收进 `LegacyTransportContext`; 自动化使用有类型的 internal metadata |

## 过渡期兼容策略

1. 阶段 3–5 保持现有 `InboundMessage`/`OutboundMessage`，Robot Server 的 Web 适配器固定 `channel="web"`，并始终提供 `session_key_override="web:<conversation_id>"`。
2. 阶段 5 的兼容层先连接旧 gateway 的 Agent 事件流；阶段 6 接入 `AgentRuntime` 后只更换事件来源，不改前端协议。
3. 阶段 6 引入 `RuntimeRequest` 与 `RuntimeEvent`，在单一 adapter 处完成双向转换；不要让新的机器人代码读取 `channel == "websocket"` 或任意聊天专用 metadata。
4. 仅当 WebUI、取消和会话历史均改用运行时事件契约后，才删除 `session.webui_turns` 的渠道判断、pairing 和聊天 channels。

## 目标运行时事件契约

```text
RuntimeRequest
  conversation_id, actor_id, content, attachments, stream, request_id

RuntimeEvent
  conversation_id, request_id, kind
  kind = delta | tool_progress | final | error | run_status | session_updated
  payload = JSON-serializable, transport-neutral
```

安全相关的 `tool_progress` 只能报告状态，不能绕开 `RobotPlatform.execute_confirmed_plan` 的确认、工作区和急停校验；急停仍是独立平台用例，不是 Agent 事件的副作用。

## 阶段 6 输入与门槛

阶段 6 必须以本文为实施输入，完成以下修改后才可进入遗留渠道删除：

1. `AgentRuntime` 只暴露上述 RuntimeRequest/RuntimeEvent，不暴露 `ChannelManager`。
2. WebUI 以 `RuntimeEvent` 订阅接收 delta、工具进度、final、error、取消状态。
3. 用集成测试证明会话历史、流式、工具进度、错误和取消均不依赖 `websocket` 字符串。
4. pairing / DM 审批不迁入 Robot Server；机械手安全确认由 `RobotPlatform` 保留并审计。
