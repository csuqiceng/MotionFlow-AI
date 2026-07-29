import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/robot-api", () => ({
  robotSystemAction: vi.fn(),
}));

vi.mock("@/robot/hooks/useRobotStatus", () => ({
  useRobotStatus: () => ({
    snapshot: {
      connection: { connected: true, label: "已连接" },
      safety: { estop: "ok", pause: "ok", alarm: "none", cancelLatch: false },
      pose: { x: 0, y: 0, z: 0, rx: 0, ry: 0, rz: 0 },
      joints: [0, 0, 0, 0, 0, 0],
      motion: { speedPct: 0, progressPct: 0 },
      task: { current: null, mode: "idle", executionMode: "dry_run_only" },
      alarms: [],
      raw: {},
    },
    polling: "connected",
    error: null,
  }),
}));

import { robotSystemAction } from "@/lib/robot-api";
import { RobotSidePanel } from "@/robot/components/RobotSidePanel";

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("RobotSidePanel safety actions", () => {
  it("runs an emergency action without browser confirms and shows lifecycle tips", async () => {
    let resolveAction: ((value: unknown) => void) | undefined;
    vi.mocked(robotSystemAction).mockImplementation(
      () => new Promise((resolve) => { resolveAction = resolve; }) as never,
    );
    const confirm = vi.spyOn(window, "confirm");
    const user = userEvent.setup();

    render(<RobotSidePanel token="token" userToken="user-token" />);
    await user.click(screen.getByRole("button", { name: "急停" }));

    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("正在执行急停");
    resolveAction?.({ ok: true, message: "done" });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("急停 已执行"));
  });

  it.each([
    ["急停", "emergency_stop"],
    ["暂停", "pause"],
    ["继续", "resume"],
    ["报警复位", "alarm_reset"],
    ["解除急停", "release_emergency_stop"],
    ["解除取消", "release_cancel"],
    ["停止当前", "stop_current"],
  ])("runs %s without browser confirms", async (label, action) => {
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
});
