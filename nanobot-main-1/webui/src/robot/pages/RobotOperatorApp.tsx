import { useEffect, useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import type { ChatSummary, RuntimeSurface } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";
import { RobotSidePanel } from "@/robot/components/RobotSidePanel";
import type { UseRobotStatusResult } from "@/robot/hooks/useRobotStatus";

/**
 * Robot operator console: nanobot's ThreadShell (the chat — reused, not
 * rewritten) in the center + a right-side robot panel (live safety/pose +
 * quick-action buttons 急停/暂停/继续/解除取消/停止当前/报警复位).
 *
 * One chat session is created on mount and reused. The ThreadShell handles
 * all chat/streaming/message-rendering — we don't re-implement it.
 */
export function RobotOperatorApp({
  token,
  runtimeSurface,
}: {
  token: string;
  runtimeSurface: RuntimeSurface;
  status?: UseRobotStatusResult;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const { client } = useClient();
  const [session, setSession] = useState<ChatSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .newChat(60_000)
      .then((chatId) => {
        if (cancelled) return;
        setSession({
          key: `robot-server:${chatId}`,
          channel: "websocket",
          chatId,
          createdAt: null,
          updatedAt: null,
          title: "操作台",
          preview: "",
        });
      })
      .catch(() => {
        // Session creation failure — ThreadShell shows its own empty state.
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div
      data-runtime-surface={runtimeSurface}
      className="flex h-full w-full overflow-hidden bg-background text-foreground"
    >
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <ThreadShell
          session={session}
          title="操作台"
          onToggleSidebar={() => {}}
          onNewChat={() => setSession(null)}
          onCreateChat={async () => {
            const id = await client.newChat(60_000);
            setSession({
              key: `websocket:${id}`,
              channel: "websocket",
              chatId: id,
              createdAt: null,
              updatedAt: null,
              title: "操作台",
              preview: "",
            });
            return id;
          }}
          hideSidebarToggleForHostChrome
        />
      </div>
      <RobotSidePanel token={token} />
    </div>
  );
}
