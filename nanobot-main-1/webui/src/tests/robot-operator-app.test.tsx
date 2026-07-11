import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RobotOperatorApp } from "@/robot/pages/RobotOperatorApp";
import type { RobotDisplaySnapshot } from "@/robot/types";

const snapshot: RobotDisplaySnapshot = {
  connection: { connected: true, label: "已连接" },
  safety: { estop: "unknown", pause: "unknown", alarm: "none", cancelLatch: false },
  pose: { x: 1, y: 2, z: 3, rx: 4, ry: 5, rz: 6 },
  joints: [null, null, null, null, null, null],
  motion: { speedPct: null, progressPct: null },
  task: { current: null, mode: "idle", executionMode: "auto_after_safety_check" },
  raw: {},
};

function renderApp(overrides: Partial<React.ComponentProps<typeof RobotOperatorApp>> = {}) {
  return render(
    <RobotOperatorApp
      token="token"
      runtimeSurface="native"
      status={{ snapshot, polling: "connected", error: null }}
      onLogout={vi.fn()}
      onNativeEngineRestart={vi.fn()}
      {...overrides}
    />,
  );
}

describe("RobotOperatorApp", () => {
  it("renders the operator console without generic Nanobot shell labels", () => {
    renderApp();

    expect(screen.getByText("机械手智能控制")).toBeInTheDocument();
    expect(screen.getByText("自动执行")).toBeInTheDocument();
    expect(screen.getByText("实时状态")).toBeInTheDocument();
    expect(screen.getByText("AI 指令")).toBeInTheDocument();
    expect(screen.getByText("运行面板")).toBeInTheDocument();

    expect(screen.queryByText("Apps")).not.toBeInTheDocument();
    expect(screen.queryByText("Skills")).not.toBeInTheDocument();
    expect(screen.queryByText("Automations")).not.toBeInTheDocument();
  });

  it("moves auto mode panel from checking to executing when a command is submitted", () => {
    renderApp();

    fireEvent.change(screen.getByLabelText("机械手指令"), {
      target: { value: "移动到 A 点" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(screen.getByText("移动到 A 点")).toBeInTheDocument();
    expect(screen.getByText("正在进行安全检查")).toBeInTheDocument();
  });

  it("shows the auto-mode info card when execution mode is auto_after_safety_check", () => {
    renderApp();
    expect(screen.getByText(/自动执行模式/)).toBeInTheDocument();
  });

  it("shows the manual-mode notice when execution mode is manual_confirm", () => {
    const manualSnapshot: RobotDisplaySnapshot = {
      ...snapshot,
      task: { ...snapshot.task, executionMode: "manual_confirm" },
    };
    renderApp({ status: { snapshot: manualSnapshot, polling: "connected", error: null } });
    expect(screen.getByText(/人工确认模式已启用/)).toBeInTheDocument();
    expect(screen.getByText("人工确认")).toBeInTheDocument();
  });

  it("renders pose values from the snapshot in the left status panel", () => {
    renderApp();
    // formatPoseValue renders integers as bare strings
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("renders dashes for missing pose values", () => {
    const emptyPose: RobotDisplaySnapshot = {
      ...snapshot,
      pose: { x: null, y: null, z: null, rx: null, ry: null, rz: null },
    };
    renderApp({ status: { snapshot: emptyPose, polling: "connected", error: null } });
    // There are 6 axes, each rendering "-" — query by role-safe text
    const dashes = screen.getAllByText("-");
    expect(dashes.length).toBeGreaterThanOrEqual(6);
  });

  it("clears the input after sending a command", () => {
    renderApp();
    const input = screen.getByLabelText("机械手指令") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "go home" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(input.value).toBe("");
  });

  it("disables the send button when the input is empty", () => {
    renderApp();
    const send = screen.getByRole("button", { name: "发送" }) as HTMLButtonElement;
    expect(send).toBeDisabled();
  });

  it("dispatches logout and restart handlers from the top bar", () => {
    const onLogout = vi.fn();
    const onNativeEngineRestart = vi.fn().mockResolvedValue("ok");
    renderApp({ onLogout, onNativeEngineRestart });

    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "重启运行时" }));
    expect(onNativeEngineRestart).toHaveBeenCalledTimes(1);
  });
});
