import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RobotSafetyBar } from "@/robot/components/RobotSafetyBar";

const { emergencyStop, refresh } = vi.hoisted(() => ({
  emergencyStop: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("@/lib/robot-api", () => ({
  robotEmergencyStop: emergencyStop,
}));

vi.mock("@/robot/hooks/useRobotStatus", () => ({
  useRobotStatus: () => ({
    snapshot: {
      connection: { connected: false, label: "控制器离线" },
      safety: { estop: "ok", alarm: "none", pause: "ok", cancelLatch: false },
      pose: { x: null, y: null, z: null, rx: null, ry: null, rz: null },
      alarms: [],
      joints: [],
      motion: { speedPct: null, progressPct: null },
      task: { current: null, mode: "idle", executionMode: "unknown" },
      raw: {},
    },
    polling: false,
    error: null,
    refresh,
  }),
}));

describe("RobotSafetyBar", () => {
  beforeEach(() => {
    emergencyStop.mockReset();
    refresh.mockReset();
  });

  it("shows the controller state and uses the dedicated emergency-stop action", async () => {
    emergencyStop.mockResolvedValue({});

    render(<RobotSafetyBar token="robot-token" userToken="user-token" />);

    expect(screen.getByText("控制器离线")).toBeInTheDocument();
    expect(screen.getByText("急停正常")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "急停" }));

    await waitFor(() => {
      expect(emergencyStop).toHaveBeenCalledWith("robot-token", "user-token");
      expect(refresh).toHaveBeenCalled();
    });
  });
});
