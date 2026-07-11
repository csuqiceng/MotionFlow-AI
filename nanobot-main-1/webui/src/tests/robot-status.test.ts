import { describe, expect, it } from "vitest";

import { formatPoseValue, normalizeRobotStatusResult, ROBOT_POSE_AXES } from "@/robot/status";
import { isRobotExecutionMode } from "@/robot/types";

describe("normalizeRobotStatusResult", () => {
  it("maps status payload with execution mode and pose", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      state: "status_report",
      message: "",
      errors: [],
      data: {
        execution_mode: "auto_after_safety_check",
        robot_state: {
          mode: "idle",
          axes_mm: { x: 1, y: 2, z: 3, rx: 4, ry: 5, rz: 6 },
          alarms: [],
          connected_real_device: true,
          cancel_latch: false,
        },
      },
    });

    expect(snapshot.connection.connected).toBe(true);
    expect(snapshot.connection.label).toBe("已连接");
    expect(snapshot.task.executionMode).toBe("auto_after_safety_check");
    expect(snapshot.pose.x).toBe(1);
    expect(snapshot.safety.alarm).toBe("none");
    expect(snapshot.joints).toEqual([null, null, null, null, null, null]);
    expect(snapshot.task.mode).toBe("idle");
    expect(snapshot.raw).toEqual({
      ok: true,
      state: "status_report",
      message: "",
      errors: [],
      data: {
        execution_mode: "auto_after_safety_check",
        robot_state: {
          mode: "idle",
          axes_mm: { x: 1, y: 2, z: 3, rx: 4, ry: 5, rz: 6 },
          alarms: [],
          connected_real_device: true,
          cancel_latch: false,
        },
      },
    });
  });

  it("keeps unknown or missing fields honest", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      state: "status_report",
      message: "",
      errors: [],
      data: {
        execution_mode: "strange",
        robot_state: {
          mode: "disconnected",
          axes_mm: {},
          alarms: ["status_error: RuntimeError"],
          connected_real_device: false,
          cancel_latch: true,
        },
      },
    });

    expect(snapshot.connection.connected).toBe(false);
    expect(snapshot.connection.label).toBe("离线");
    expect(snapshot.task.executionMode).toBe("unknown");
    expect(snapshot.pose.x).toBeNull();
    expect(snapshot.pose.rz).toBeNull();
    expect(snapshot.safety.alarm).toBe("active");
    expect(snapshot.safety.cancelLatch).toBe(true);
    expect(snapshot.joints).toEqual([null, null, null, null, null, null]);
  });

  it("maps disconnected backend (no data field) to offline label without faking safety", () => {
    const snapshot = normalizeRobotStatusResult({ ok: true });

    expect(snapshot.connection.connected).toBe(false);
    expect(snapshot.connection.label).toBe("离线");
    expect(snapshot.pose.x).toBeNull();
    expect(snapshot.safety.estop).toBe("unknown");
    expect(snapshot.safety.pause).toBe("unknown");
    expect(snapshot.safety.alarm).toBe("none");
    expect(snapshot.safety.cancelLatch).toBe(false);
    expect(snapshot.task.executionMode).toBe("unknown");
    expect(snapshot.task.mode).toBe("unknown");
  });

  it("flags estop and paused safety values", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      data: {
        execution_mode: "manual_confirm",
        robot_state: {
          mode: "paused",
          axes_mm: {},
          alarms: ["ESTOP pressed"],
          connected_real_device: true,
        },
      },
    });

    expect(snapshot.safety.estop).toBe("active");
    expect(snapshot.safety.pause).toBe("paused");
    expect(snapshot.safety.alarm).toBe("active");
    expect(snapshot.task.executionMode).toBe("manual_confirm");
  });

  it("reports ok for estop/pause when connected and not active", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      data: {
        robot_state: {
          mode: "idle",
          axes_mm: {},
          alarms: [],
          connected_real_device: true,
          cancel_latch: false,
        },
      },
    });

    expect(snapshot.connection.connected).toBe(true);
    expect(snapshot.safety.estop).toBe("ok");
    expect(snapshot.safety.pause).toBe("ok");
    expect(snapshot.safety.alarm).toBe("none");
  });

  it("keeps pause unknown when alarmed (PAUSED bit hidden behind alarm)", () => {
    const snapshot = normalizeRobotStatusResult({
      ok: true,
      data: {
        robot_state: {
          mode: "alarm",
          axes_mm: {},
          alarms: ["controller_alarm", "emergency_stop"],
          connected_real_device: true,
          cancel_latch: true,
        },
      },
    });

    expect(snapshot.safety.estop).toBe("active"); // emergency_stop alarm present
    expect(snapshot.safety.pause).toBe("unknown"); // ALARM hides PAUSED bit
    expect(snapshot.safety.alarm).toBe("active");
  });

  it("exposes pose axes constant and pose formatter", () => {
    expect(ROBOT_POSE_AXES).toEqual(["x", "y", "z", "rx", "ry", "rz"]);
    expect(formatPoseValue(null)).toBe("-");
    expect(formatPoseValue(10)).toBe("10");
    expect(formatPoseValue(1.5)).toBe("1.500");
  });

  it("isRobotExecutionMode narrows known modes", () => {
    expect(isRobotExecutionMode("auto_after_safety_check")).toBe(true);
    expect(isRobotExecutionMode("manual_confirm")).toBe(true);
    expect(isRobotExecutionMode("dry_run_only")).toBe(true);
    expect(isRobotExecutionMode("unknown")).toBe(false);
    expect(isRobotExecutionMode("strange")).toBe(false);
    expect(isRobotExecutionMode(undefined)).toBe(false);
  });
});
