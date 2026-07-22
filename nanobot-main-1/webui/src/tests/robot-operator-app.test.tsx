import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mock ThreadShell (complex, needs real client/session) — just verify it's embedded.
vi.mock("@/components/thread/ThreadShell", () => ({
  ThreadShell: () => <div data-testid="thread-shell-mock">ThreadShell</div>,
}));

// Mock useRobotStatus so RobotSidePanel doesn't poll.
vi.mock("@/robot/hooks/useRobotStatus", () => ({
  useRobotStatus: () => ({
    snapshot: {
      connection: { connected: true, label: "已连接" },
      safety: { estop: "unknown", pause: "unknown", alarm: "none", cancelLatch: false },
      pose: { x: 1000, y: 0, z: 800, rx: 0, ry: 90, rz: 0 },
      joints: [null, null, null, null, null, null],
      motion: { speedPct: null, progressPct: null },
      task: { current: null, mode: "idle", executionMode: "auto_after_safety_check" },
      alarms: [],
      raw: {},
    },
    polling: "connected",
    error: null,
  }),
}));

// Mock useClient (RobotOperatorApp calls client.newChat on mount).
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({
    client: { newChat: vi.fn().mockResolvedValue("chat-1") },
    token: "tok",
    modelName: null,
  }),
}));

import { RobotOperatorApp } from "@/robot/pages/RobotOperatorApp";

describe("RobotOperatorApp", () => {
  it("embeds nanobot's ThreadShell (the chat) + the robot side panel", () => {
    render(
      <RobotOperatorApp
        token="token"
        runtimeSurface="native"
        onLogout={vi.fn()}
        onNativeEngineRestart={vi.fn()}
      />,
    );

    // ThreadShell (nanobot's chat) is embedded.
    expect(screen.getByTestId("thread-shell-mock")).toBeInTheDocument();
    // Robot side panel renders v2 safety overview + pose + quick buttons.
    expect(screen.getByText("末端位姿")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^急停/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /报警复位/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /停止当前/ })).toBeInTheDocument();
    // Pose values from the mocked snapshot.
    expect(screen.getByText("1000")).toBeInTheDocument();
  });

  it("does not show generic Nanobot shell labels", () => {
    render(
      <RobotOperatorApp
        token="token"
        runtimeSurface="native"
        onLogout={vi.fn()}
        onNativeEngineRestart={vi.fn()}
      />,
    );

    expect(screen.queryByText("Apps")).not.toBeInTheDocument();
    expect(screen.queryByText("Skills")).not.toBeInTheDocument();
  });
});
