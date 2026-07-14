import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LibraryExecution } from "@/lib/robot-library-api";
import { ExecutionMonitor } from "@/robot/workbench/ExecutionMonitor";

const pausedExecution: LibraryExecution = {
  execution_id: "run-1",
  kind: "flow",
  source_id: "delay-flow",
  state: "paused",
  message: "",
  steps: [{ step_index: 1, state: "succeeded" }, { step_index: 2, state: "queued" }],
  allowed_actions: ["resume", "step", "stop"],
};

describe("ExecutionMonitor", () => {
  it("shows only server-approved paused controls and forwards the chosen action", async () => {
    const onControl = vi.fn();
    render(<ExecutionMonitor execution={pausedExecution} onControl={onControl} />);
    expect(screen.getByRole("button", { name: "继续" })).toBeVisible();
    expect(screen.getByRole("button", { name: "单步" })).toBeVisible();
    expect(screen.getByRole("button", { name: "停止" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "暂停" })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "单步" }));
    expect(onControl).toHaveBeenCalledWith("step");
  });
});
