import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// --- Mocks: useClient returns a fake client (newChat resolves); useNanobotStream
// returns a controllable {messages, isStreaming, send, stop} the test drives. ---

const fakeClient = { newChat: vi.fn().mockResolvedValue("chat-1") };
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: fakeClient, token: "tok", modelName: null }),
}));

let streamMessages: unknown[] = [];
let streamIsStreaming = false;
const streamSend = vi.fn();
const streamStop = vi.fn();
vi.mock("@/hooks/useNanobotStream", () => ({
  useNanobotStream: () => ({
    messages: streamMessages,
    isStreaming: streamIsStreaming,
    send: streamSend,
    stop: streamStop,
  }),
}));

import { useRobotOperatorChat } from "@/robot/hooks/useRobotOperatorChat";

function userMsg(turnId: string, content: string) {
  return { id: `u-${turnId}`, role: "user", content, turnId, createdAt: 0 };
}
function traceMsg(turnId: string, event: Record<string, unknown>) {
  return { id: `t-${turnId}`, role: "tool", kind: "trace", turnId, toolEvents: [event], createdAt: 0 };
}

describe("useRobotOperatorChat", () => {
  beforeEach(() => {
    streamMessages = [];
    streamIsStreaming = false;
    streamSend.mockClear();
    fakeClient.newChat.mockResolvedValue("chat-1");
  });

  it("creates a session on mount and exposes chatId", async () => {
    const { result } = renderHook(() => useRobotOperatorChat(vi.fn()));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.chatId).toBe("chat-1");
    expect(result.current.isInitializing).toBe(false);
    expect(result.current.initError).toBeNull();
  });

  it("dispatches auto_execution_started when isStreaming turns true after a command", async () => {
    const onAction = vi.fn();
    const { rerender } = renderHook(() => useRobotOperatorChat(onAction));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    streamMessages = [userMsg("turn-1", "移动到 A 点")];
    streamIsStreaming = true;
    rerender();
    await act(async () => {
      await Promise.resolve();
    });

    expect(onAction).toHaveBeenCalledWith({ type: "auto_execution_started" });
  });

  it("dispatches tool_result_received on a robot_arm end event", async () => {
    const onAction = vi.fn();
    const { rerender } = renderHook(() => useRobotOperatorChat(onAction));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    streamMessages = [
      userMsg("turn-1", "移动到 A 点"),
      traceMsg("turn-1", {
        name: "robot_arm",
        phase: "end",
        call_id: "c1",
        result: { ok: true, state: "real_motion_command_completed", message: "已移动" },
      }),
    ];
    streamIsStreaming = false;
    rerender();
    await act(async () => {
      await Promise.resolve();
    });

    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "tool_result_received",
        ok: true,
        state: "real_motion_command_completed",
        message: "已移动",
      }),
    );
  });

  it("does not re-dispatch the same result on re-render (de-dup by call_id)", async () => {
    const onAction = vi.fn();
    const { rerender } = renderHook(() => useRobotOperatorChat(onAction));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    streamMessages = [
      userMsg("turn-1", "移动到 A 点"),
      traceMsg("turn-1", { name: "robot_arm", phase: "end", call_id: "c1", result: { ok: true } }),
    ];
    rerender();
    await act(async () => {
      await Promise.resolve();
    });
    const callsBefore = onAction.mock.calls.filter(
      (c) => c[0]?.type === "tool_result_received",
    ).length;
    rerender();
    await act(async () => {
      await Promise.resolve();
    });
    const callsAfter = onAction.mock.calls.filter(
      (c) => c[0]?.type === "tool_result_received",
    ).length;
    expect(callsAfter).toBe(callsBefore);
  });

  it("ignores a robot_arm result whose turnId differs from the active turn", async () => {
    const onAction = vi.fn();
    const { rerender } = renderHook(() => useRobotOperatorChat(onAction));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Active turn is turn-2 (last user message). A late result for turn-1 must be ignored.
    streamMessages = [
      userMsg("turn-1", "第一条"),
      userMsg("turn-2", "第二条"),
      traceMsg("turn-1", { name: "robot_arm", phase: "end", call_id: "stale", result: { ok: true } }),
    ];
    rerender();
    await act(async () => {
      await Promise.resolve();
    });

    const resultCalls = onAction.mock.calls.filter((c) => c[0]?.type === "tool_result_received");
    expect(resultCalls.length).toBe(0);
  });

  it("calls streamSend when send is invoked with a ready session", async () => {
    const { result } = renderHook(() => useRobotOperatorChat(vi.fn()));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => {
      result.current.send("移动到 A 点");
    });
    expect(streamSend).toHaveBeenCalledWith("移动到 A 点");
  });
});
