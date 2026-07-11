import { Send } from "lucide-react";
import { useState, type Dispatch } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { RobotDisplayAction, RobotDisplayState } from "@/robot/state/robotDisplayState";

/**
 * M1 center command panel.
 *
 * Records the operator's command and dispatches ``command_submitted`` to the
 * shared display reducer — it intentionally does NOT call the LLM yet. M3 will
 * wire the real chat stream; for now the dispatch is enough to drive the right
 * run panel from "idle" → "safetyChecking".
 */
export function RobotDialoguePanel({
  displayState,
  dispatch,
}: {
  displayState: RobotDisplayState;
  dispatch: Dispatch<RobotDisplayAction>;
}) {
  const [value, setValue] = useState("");
  const canSend = value.trim().length > 0;

  const submit = () => {
    const command = value.trim();
    if (!command) return;
    dispatch({ type: "command_submitted", command });
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
        {displayState.recent.length === 0 ? (
          <div className="rounded-md border border-dashed border-border/70 p-4 text-sm text-muted-foreground">
            等待操作员输入指令
          </div>
        ) : (
          displayState.recent.map((item) => (
            <div
              key={`${item.at}-${item.command}`}
              className="rounded-md border border-border/70 bg-muted/20 p-3 text-sm"
            >
              {item.command}
            </div>
          ))
        )}
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
          <Button
            type="button"
            onClick={submit}
            disabled={!canSend}
            className="gap-2"
          >
            <Send className="h-4 w-4" />
            发送
          </Button>
        </div>
      </div>
    </section>
  );
}
