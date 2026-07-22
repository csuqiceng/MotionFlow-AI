import { Send } from "lucide-react";
import { useState, type Dispatch } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { RobotOperatorChatResult } from "@/robot/hooks/useRobotOperatorChat";
import type { RobotDisplayAction } from "@/robot/state/robotDisplayState";

/**
 * Center dialogue panel. Sends the operator's command through the chat stream
 * (``chat.send``) AND dispatches ``command_submitted`` so the run panel flips to
 * "safetyChecking" instantly. Renders the live conversation (user / assistant /
 * tool-trace rows) from ``chat.messages``.
 */
export function RobotDialoguePanel({
  dispatch,
  chat,
}: {
  dispatch: Dispatch<RobotDisplayAction>;
  chat: RobotOperatorChatResult;
}) {
  const [value, setValue] = useState("");
  const canSend =
    value.trim().length > 0 &&
    !!chat.chatId &&
    !chat.isInitializing &&
    !chat.isStreaming &&
    !chat.initError;

  const submit = () => {
    const command = value.trim();
    if (!command || !canSend) return;
    dispatch({ type: "command_submitted", command });
    chat.send(command);
    setValue("");
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col border-r border-border/70 bg-background">
      <div className="border-b border-border/70 p-4">
        <h2 className="text-sm font-semibold">AI 指令</h2>
        <p className="text-xs text-muted-foreground">
          输入机械手动作指令, 当前阶段会同步右侧运行状态。
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-4">
        {chat.initError ? (
          <div className="status-pill status-pill--danger p-3 text-sm">
            会话建立失败: {chat.initError}
          </div>
        ) : chat.isInitializing ? (
          <div className="text-sm text-muted-foreground">正在建立会话…</div>
        ) : chat.messages.length === 0 ? (
          <div className="soft-card border-dashed border-border/70 p-4 text-sm text-muted-foreground">
            等待操作员输入指令
          </div>
        ) : (
          chat.messages.map((m) => {
            if (m.role === "user") {
              return (
                <div
                  key={m.id}
                  className="self-end rounded-lg border border-border/70 bg-muted/20 p-3 text-sm"
                >
                  {m.content}
                </div>
              );
            }
            if (m.role === "assistant" && m.kind !== "trace") {
              return (
                <div
                  key={m.id}
                  className="soft-card bg-background p-3 text-sm"
                >
                  {m.reasoning ? (
                    <details className="mb-1 text-xs text-muted-foreground">
                      <summary>思考过程</summary>
                      {m.reasoning}
                    </details>
                  ) : null}
                  {m.content}
                </div>
              );
            }
            if (m.role === "tool" && m.kind === "trace") {
              const robotEvent = m.toolEvents?.find(
                (e) => e.name === "robot_arm" && (e.phase === "end" || e.phase === "error"),
              );
              const summary = robotEvent
                ? robotEvent.phase === "end"
                  ? ((robotEvent.result as { message?: string } | undefined)?.message ??
                    "工具执行完成")
                  : typeof robotEvent.error === "string"
                    ? robotEvent.error
                    : "工具执行出错"
                : m.content;
              return (
                <div
                  key={m.id}
                  className="self-start rounded-lg border border-border/40 bg-muted/10 p-2 data-mono text-xs text-muted-foreground"
                >
                  {summary}
                </div>
              );
            }
            return null;
          })
        )}
        {chat.isStreaming ? (
          <div className="self-start text-xs text-muted-foreground">执行中…</div>
        ) : null}
      </div>

      <div className="border-t border-border/70 p-4">
        <label className="sr-only" htmlFor="robot-command-input">
          机械手指令
        </label>
        <div className="flex items-end gap-2">
          <Textarea
            id="robot-command-input"
            aria-label="机械手指令"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="例如: 移动到 A 点并保持安全速度"
            className="min-h-20 resize-none"
          />
          <Button type="button" onClick={submit} disabled={!canSend} className="btn-primary gap-2">
            <Send className="h-4 w-4" />
            发送
          </Button>
        </div>
      </div>
    </section>
  );
}
