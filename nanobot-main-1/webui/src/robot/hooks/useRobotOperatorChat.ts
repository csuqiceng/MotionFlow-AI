import { useCallback, useEffect, useRef, useState } from "react";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import type { UIMessage } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";
import type { RobotDisplayAction } from "@/robot/state/robotDisplayState";

export interface RobotOperatorChatResult {
  /** null until newChat resolves; UI disables send while null. */
  chatId: string | null;
  /** True while the session is being created. */
  isInitializing: boolean;
  /** LLM messages for the dialogue panel (user + assistant + trace rows). */
  messages: UIMessage[];
  isStreaming: boolean;
  /** Send a command. No-op if chatId not ready or a turn is in flight. */
  send: (command: string) => void;
  stop: () => void;
  /** Session-creation error, if newChat rejected/timed out. */
  initError: string | null;
}

/**
 * The operator console's single bridge to the nanobot chat stream.
 *
 * Owns one chat session (created on mount via ``client.newChat``), wraps
 * :func:`useNanobotStream`, and extracts ``robot_arm`` tool results correlated
 * by ``turnId`` so a late result for command N-1 can never clobber command N's
 * run-panel state. Discovered results + turn lifecycle drive the shared
 * ``robotDisplayReducer`` via the ``onAction`` callback (the component passes
 * its ``dispatch``).
 *
 * State machine (auto mode):
 *   command_submitted (component, on send)
 *     -> auto_execution_started (hook, when isStreaming flips true)
 *     -> tool_result_received   (hook, when robot_arm end/error event arrives)
 *   or, if the turn ends with no robot_arm result:
 *     -> tool_result_received { ok: false }  (hook, via onTurnEnd)
 */
export function useRobotOperatorChat(
  onAction: (action: RobotDisplayAction) => void,
): RobotOperatorChatResult {
  const { client } = useClient();
  const [chatId, setChatId] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [initError, setInitError] = useState<string | null>(null);

  // De-dup / correlation refs.
  const lastDispatchedResultKey = useRef<string | null>(null);
  const autoStartForTurn = useRef<Set<string>>(new Set());
  const turnEndHandledFor = useRef<string | null>(null);
  const resultDispatchedForTurn = useRef<Set<string>>(new Set());
  const lastUserTurnIdRef = useRef<string | null>(null);
  const onActionRef = useRef(onAction);
  onActionRef.current = onAction;

  // Mount: create one operator chat session. No workspace scope needed.
  useEffect(() => {
    let cancelled = false;
    setIsInitializing(true);
    setInitError(null);
    client
      .newChat(60_000)
      .then((id) => {
        if (cancelled) return;
        setChatId(id);
        setIsInitializing(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setInitError(e instanceof Error ? e.message : String(e));
        setIsInitializing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  // onTurnEnd: finalize a turn that produced no robot_arm result.
  const handleTurnEnd = useCallback(() => {
    const activeTurnId = lastUserTurnIdRef.current;
    if (!activeTurnId) return;
    if (turnEndHandledFor.current === activeTurnId) return;
    turnEndHandledFor.current = activeTurnId;
    if (!resultDispatchedForTurn.current.has(activeTurnId)) {
      onActionRef.current({
        type: "tool_result_received",
        ok: false,
        message: "本轮未产生机械手执行结果",
      });
    }
  }, []);

  const { messages, isStreaming, send: streamSend, stop } = useNanobotStream(
    chatId,
    [],
    false,
    handleTurnEnd,
  );

  // Keep the ref in sync (declared after useNanobotStream so `messages` exists).
  useEffect(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUserTurnIdRef.current = messages[i].turnId ?? null;
        return;
      }
    }
    lastUserTurnIdRef.current = null;
  }, [messages]);

  // State machine: auto_execution_started + robot_arm tool_result_received.
  useEffect(() => {
    if (!chatId) return;
    // Active turn = the last user message's turnId. Single-command-at-a-time
    // (send is disabled while streaming), so this is unambiguous.
    let activeTurnId: string | null = null;
    let lastUserIdx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        activeTurnId = messages[i].turnId ?? null;
        lastUserIdx = i;
        break;
      }
    }
    if (!activeTurnId) return;

    // 1. LLM picked up the command -> executing.
    if (isStreaming && !autoStartForTurn.current.has(activeTurnId)) {
      autoStartForTurn.current.add(activeTurnId);
      onActionRef.current({ type: "auto_execution_started" });
    }

    // 2. Scan the active turn's messages (after the last user message) for a
    //    robot_arm end/error event. Match by event.name (exact, not substring).
    for (let i = lastUserIdx + 1; i < messages.length; i++) {
      const m = messages[i];
      // Skip messages belonging to a different turn — a late result for command
      // N-1 arriving after command N was submitted must not clobber command N.
      if (m.turnId && activeTurnId && m.turnId !== activeTurnId) continue;
      if (m.role !== "tool" || m.kind !== "trace" || !m.toolEvents) continue;
      for (const ev of m.toolEvents) {
        if (ev.name !== "robot_arm") continue;
        if (ev.phase !== "end" && ev.phase !== "error") continue;
        const key = ev.call_id ?? `${activeTurnId}|${m.id}`;
        if (lastDispatchedResultKey.current === key) break;
        lastDispatchedResultKey.current = key;
        resultDispatchedForTurn.current.add(activeTurnId);
        if (ev.phase === "end") {
          const r = ev.result as { ok?: boolean; state?: string; message?: string } | undefined;
          onActionRef.current({
            type: "tool_result_received",
            ok: !!r?.ok,
            state: r?.state,
            message: r?.message,
          });
        } else {
          const errMsg = typeof ev.error === "string" ? ev.error : "工具执行出错";
          onActionRef.current({ type: "tool_result_received", ok: false, message: errMsg });
        }
        break;
      }
    }
  }, [messages, isStreaming, chatId]);

  const send = useCallback(
    (command: string) => {
      if (!chatId || isStreaming) return;
      if (!command.trim()) return;
      streamSend(command);
    },
    [chatId, isStreaming, streamSend],
  );

  return { chatId, isInitializing, messages, isStreaming, send, stop, initError };
}
