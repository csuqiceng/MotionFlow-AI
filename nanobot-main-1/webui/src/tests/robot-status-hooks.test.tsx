import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { robotStatus } from "@/lib/robot-api";
import { useRobotExecutionMode } from "@/robot/hooks/useRobotExecutionMode";
import { useRobotStatus } from "@/robot/hooks/useRobotStatus";
import { normalizeRobotStatusResult } from "@/robot/status";

vi.mock("@/lib/robot-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/robot-api")>("@/lib/robot-api");
  return {
    ...actual,
    robotStatus: vi.fn(),
  };
});

const mockedRobotStatus = vi.mocked(robotStatus);

beforeEach(() => {
  vi.useFakeTimers();
  mockedRobotStatus.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRobotStatus", () => {
  it("polls robot status and exposes normalized snapshot", async () => {
    mockedRobotStatus.mockResolvedValue({
      ok: true,
      data: {
        execution_mode: "auto_after_safety_check",
        robot_state: {
          mode: "idle",
          axes_mm: { x: 10 },
          alarms: [],
          connected_real_device: true,
          cancel_latch: false,
        },
      },
    });

    const { result, unmount } = renderHook(() =>
      useRobotStatus("token-1", { intervalMs: 3000 }),
    );

    // The first poll fires synchronously on mount; flush the awaited
    // robotStatus() promise so state settles before assertions.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.snapshot?.pose.x).toBe(10);
    expect(result.current.polling).toBe("connected");
    expect(result.current.error).toBeNull();
    expect(mockedRobotStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockedRobotStatus).toHaveBeenCalledTimes(2);

    unmount();
  });

  it("reports error state and backs off to errorIntervalMs when calls throw", async () => {
    mockedRobotStatus.mockRejectedValue(new Error("boom"));

    const { result, unmount } = renderHook(() =>
      useRobotStatus("token-err", { intervalMs: 3000, errorIntervalMs: 10000 }),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.polling).toBe("error");
    expect(result.current.error).toBe("boom");
    expect(result.current.snapshot).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });
    // still only one call — 10s backoff should not have fired yet
    expect(mockedRobotStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(10000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockedRobotStatus).toHaveBeenCalledTimes(2);

    unmount();
  });

  it("backs off to errorIntervalMs when the controller reports disconnected", async () => {
    mockedRobotStatus.mockResolvedValue({
      ok: true,
      data: {
        execution_mode: "auto_after_safety_check",
        robot_state: {
          mode: "disconnected",
          axes_mm: {},
          alarms: ["status_error: unavailable"],
          connected_real_device: false,
          cancel_latch: false,
        },
      },
    });

    const { result, unmount } = renderHook(() =>
      useRobotStatus("token-offline", { intervalMs: 3000, errorIntervalMs: 10000 }),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.polling).toBe("error");
    expect(result.current.snapshot?.connection.connected).toBe(false);

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockedRobotStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(10000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockedRobotStatus).toHaveBeenCalledTimes(2);

    unmount();
  });

  it("stops polling when disabled", async () => {
    const { result, unmount } = renderHook(() =>
      useRobotStatus("token-off", { enabled: false, intervalMs: 1000 }),
    );

    expect(result.current.snapshot).toBeNull();
    expect(result.current.polling).toBe("connecting");
    expect(mockedRobotStatus).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(mockedRobotStatus).not.toHaveBeenCalled();

    unmount();
  });
});

describe("useRobotExecutionMode", () => {
  it("maps manual_confirm mode to label and behavior flags", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      data: {
        execution_mode: "manual_confirm",
        robot_state: { mode: "idle", axes_mm: {}, alarms: [], connected_real_device: true },
      },
    });

    const mode = useRobotExecutionMode(snapshot);

    expect(mode.mode).toBe("manual_confirm");
    expect(mode.label).toBe("人工确认");
    expect(mode.requiresManualConfirm).toBe(true);
    expect(mode.autoExecutesAfterSafetyCheck).toBe(false);
    expect(mode.dryRunOnly).toBe(false);
  });

  it("returns unknown label when snapshot is null", () => {
    const mode = useRobotExecutionMode(null);

    expect(mode.mode).toBe("unknown");
    expect(mode.label).toBe("未知模式");
    expect(mode.requiresManualConfirm).toBe(false);
  });

  it("maps dry_run_only and auto_after_safety_check modes", () => {
    const dry = useRobotExecutionMode(
      normalizeRobotStatusResult({
        ok: true,
        data: {
          execution_mode: "dry_run_only",
          robot_state: { mode: "idle", axes_mm: {}, alarms: [], connected_real_device: true },
        },
      }),
    );
    expect(dry.label).toBe("只预演");
    expect(dry.dryRunOnly).toBe(true);

    const auto = useRobotExecutionMode(
      normalizeRobotStatusResult({
        ok: true,
        data: {
          execution_mode: "auto_after_safety_check",
          robot_state: { mode: "idle", axes_mm: {}, alarms: [], connected_real_device: true },
        },
      }),
    );
    expect(auto.label).toBe("自动执行");
    expect(auto.autoExecutesAfterSafetyCheck).toBe(true);
  });
});
