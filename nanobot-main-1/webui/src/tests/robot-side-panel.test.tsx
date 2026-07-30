import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useRobotStatus: vi.fn(),
}));

vi.mock("@/lib/robot-api", () => ({
  robotEmergencyStop: vi.fn(),
  robotSystemAction: vi.fn(),
}));

vi.mock("@/robot/hooks/useRobotStatus", () => ({
  useRobotStatus: mocks.useRobotStatus,
}));

import { robotEmergencyStop, robotSystemAction } from "@/lib/robot-api";
import { RobotSidePanel } from "@/robot/components/RobotSidePanel";
import { useRobotStatus } from "@/robot/hooks/useRobotStatus";

const defaultSnapshot = {
  connection: { connected: true, label: "已连接" },
  safety: { estop: "ok" as const, pause: "ok" as const, alarm: "none" as const, cancelLatch: false },
  pose: { x: 0, y: 0, z: 0, rx: 0, ry: 0, rz: 0 },
  joints: [0, 0, 0, 0, 0, 0],
  motion: { speedPct: 0, progressPct: 0 },
  task: { current: null, mode: "idle", executionMode: "dry_run_only" as const },
  alarms: [],
  raw: {},
};

function setSnapshot(overrides: Partial<typeof defaultSnapshot> = {}) {
  vi.mocked(useRobotStatus).mockReturnValue({
    snapshot: {
      ...defaultSnapshot,
      ...overrides,
      safety: { ...defaultSnapshot.safety, ...overrides.safety },
      task: { ...defaultSnapshot.task, ...overrides.task },
    },
    polling: "connected",
    error: null,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

beforeEach(() => setSnapshot());

describe("RobotSidePanel safety actions", () => {
  it("runs an emergency action without browser confirms and shows lifecycle tips", async () => {
    let resolveAction: ((value: unknown) => void) | undefined;
    vi.mocked(robotEmergencyStop).mockImplementation(
      () => new Promise((resolve) => { resolveAction = resolve; }) as never,
    );
    const confirm = vi.spyOn(window, "confirm");
    const user = userEvent.setup();

    render(<RobotSidePanel token="token" userToken="user-token" />);
    await user.click(screen.getByRole("button", { name: "急停" }));

    expect(confirm).not.toHaveBeenCalled();
    expect(robotEmergencyStop).toHaveBeenCalledWith("token", "user-token");
    expect(screen.getByRole("status")).toHaveTextContent("正在执行急停");
    resolveAction?.({ ok: true, message: "done" });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("急停 已执行"));
  });

  it.each([
    ["暂停", "pause", {}],
    ["继续", "resume", { safety: { pause: "paused" as const } }],
    ["报警复位", "alarm_reset", { safety: { alarm: "active" as const } }],
    ["解除急停", "release_emergency_stop", { safety: { estop: "active" as const } }],
    ["解除取消", "release_cancel", { safety: { cancelLatch: true } }],
    ["停止当前", "stop_current", { task: { mode: "moving" } }],
  ])("runs %s without browser confirms", async (label, action, snapshot) => {
    setSnapshot(snapshot);
    vi.mocked(robotSystemAction).mockResolvedValue({ ok: true, message: "done" } as never);
    const confirm = vi.spyOn(window, "confirm");
    const user = userEvent.setup();

    render(<RobotSidePanel token="token" userToken="user-token" />);
    await user.click(screen.getByRole("button", { name: label }));

    expect(confirm).not.toHaveBeenCalled();
    expect(robotSystemAction).toHaveBeenCalledWith(
      "token",
      expect.any(String),
      action,
      "user-token",
    );
  });

  it("disables actions that the current controller state would reject", () => {
    render(<RobotSidePanel token="token" userToken="user-token" />);

    expect(screen.getByRole("button", { name: "停止当前" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "解除取消" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "解除急停" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "继续" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "报警复位" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "暂停" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "急停" })).toBeEnabled();
  });
});
