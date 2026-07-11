import { describe, expect, it } from "vitest";

import {
  initialRobotDisplayState,
  robotDisplayReducer,
  robotToolResultToDisplayAction,
} from "@/robot/state/robotDisplayState";

describe("robotDisplayReducer", () => {
  it("starts in idle phase with standby message", () => {
    expect(initialRobotDisplayState.run.phase).toBe("idle");
    expect(initialRobotDisplayState.run.message).toBe("系统待机, 等待指令");
    expect(initialRobotDisplayState.lastCommand).toBeNull();
    expect(initialRobotDisplayState.recent).toEqual([]);
  });

  it("records submitted command and enters checking state", () => {
    const state = robotDisplayReducer(initialRobotDisplayState, {
      type: "command_submitted",
      command: "移动到 A 点",
    });

    expect(state.lastCommand).toBe("移动到 A 点");
    expect(state.run.phase).toBe("safetyChecking");
    expect(state.run.message).toBe("正在进行安全检查");
    expect(state.run.updatedAt).not.toBeNull();
    expect(state.recent[0]).toEqual({
      command: "移动到 A 点",
      at: state.run.updatedAt,
    });
  });

  it("prepends new commands and keeps only the last 5 recent entries", () => {
    let state = initialRobotDisplayState;
    for (let i = 0; i < 6; i += 1) {
      state = robotDisplayReducer(state, {
        type: "command_submitted",
        command: `cmd-${i}`,
        at: 1000 + i,
      });
    }
    expect(state.recent).toHaveLength(5);
    expect(state.recent[0].command).toBe("cmd-5");
    expect(state.recent[4].command).toBe("cmd-1");
  });

  it("transitions to executing on auto_execution_started", () => {
    const started = robotDisplayReducer(initialRobotDisplayState, {
      type: "command_submitted",
      command: "go",
    });
    const executing = robotDisplayReducer(started, {
      type: "auto_execution_started",
    });

    expect(executing.run.phase).toBe("executing");
    expect(executing.run.message).toBe("安全检查通过, 正在执行");
  });

  it("records completed auto-mode tool result", () => {
    const started = robotDisplayReducer(initialRobotDisplayState, {
      type: "command_submitted",
      command: "移动到 A 点",
    });
    const completed = robotDisplayReducer(started, {
      type: "tool_result_received",
      ok: true,
      state: "real_motion_command_completed",
      message: "done",
    });

    expect(completed.run.phase).toBe("completed");
    expect(completed.run.state).toBe("real_motion_command_completed");
    expect(completed.run.message).toBe("done");
  });

  it("records blocked auto-mode tool result", () => {
    const blocked = robotDisplayReducer(initialRobotDisplayState, {
      type: "tool_result_received",
      ok: false,
      state: "zmotion_operator_safety_blocked",
      message: "blocked by workspace",
    });

    expect(blocked.run.phase).toBe("blocked");
    expect(blocked.run.message).toBe("blocked by workspace");
  });

  it("uses default messages for tool_result_received when not provided", () => {
    const ok = robotDisplayReducer(initialRobotDisplayState, {
      type: "tool_result_received",
      ok: true,
    });
    expect(ok.run.message).toBe("执行完成");

    const bad = robotDisplayReducer(initialRobotDisplayState, {
      type: "tool_result_received",
      ok: false,
    });
    expect(bad.run.message).toBe("执行被阻断");
  });

  it("status_poll_after_command keeps phase executing", () => {
    const started = robotDisplayReducer(initialRobotDisplayState, {
      type: "command_submitted",
      command: "go",
    });
    const polled = robotDisplayReducer(started, {
      type: "status_poll_after_command",
    });

    expect(polled.run.phase).toBe("executing");
    expect(polled.run.message).toContain("状态轮询");
  });

  it("clear_run resets to idle phase", () => {
    const started = robotDisplayReducer(initialRobotDisplayState, {
      type: "command_submitted",
      command: "go",
    });
    const cleared = robotDisplayReducer(started, { type: "clear_run" });

    expect(cleared.run.phase).toBe("idle");
    expect(cleared.lastCommand).toBeNull();
    expect(cleared.recent).toEqual([]);
  });
});

describe("robotToolResultToDisplayAction", () => {
  it("projects successful robot tool result into a display action", () => {
    expect(
      robotToolResultToDisplayAction({
        ok: true,
        state: "real_motion_command_completed",
        message: "motion done",
        data: { robot_state: { mode: "idle" } },
      }),
    ).toEqual({
      type: "tool_result_received",
      ok: true,
      state: "real_motion_command_completed",
      message: "motion done",
    });
  });

  it("projects a zmotion failure result", () => {
    expect(
      robotToolResultToDisplayAction({
        ok: false,
        state: "zmotion_operator_safety_blocked",
        message: "blocked",
      }),
    ).toEqual({
      type: "tool_result_received",
      ok: false,
      state: "zmotion_operator_safety_blocked",
      message: "blocked",
    });
  });

  it("matches a robot result by data.robot_state even when state is generic", () => {
    expect(
      robotToolResultToDisplayAction({
        ok: true,
        state: "tool_finished",
        data: { robot_state: { mode: "idle" } },
      }),
    ).toEqual({
      type: "tool_result_received",
      ok: true,
      state: "tool_finished",
      message: undefined,
    });
  });

  it("returns null when ok is missing or non-boolean", () => {
    expect(robotToolResultToDisplayAction({ state: "robot_done" })).toBeNull();
    expect(robotToolResultToDisplayAction({ ok: "true", state: "robot_done" })).toBeNull();
  });

  it("returns null when state is missing or non-string", () => {
    expect(robotToolResultToDisplayAction({ ok: true })).toBeNull();
    expect(robotToolResultToDisplayAction({ ok: true, state: 42 })).toBeNull();
  });

  it("ignores non-robot-shaped tool results", () => {
    expect(robotToolResultToDisplayAction({ value: 123 })).toBeNull();
    expect(
      robotToolResultToDisplayAction({
        ok: true,
        state: "web_search_done",
        data: { results: [] },
      }),
    ).toBeNull();
    expect(robotToolResultToDisplayAction(null)).toBeNull();
    expect(robotToolResultToDisplayAction([1, 2, 3])).toBeNull();
    expect(robotToolResultToDisplayAction("string")).toBeNull();
  });
});
