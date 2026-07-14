import { describe, expect, it } from "vitest";
import { cloneFlowStep, moveFlowStep, removeFlowStep } from "@/robot/workbench/flow-steps";

const steps = [
  { step_id: 1, action: "home", func_id: 108, params: { x: 0 }, position_name: null, spd_pct: 100, description: "" },
  { step_id: 2, action: "close", func_id: 120, params: { value: 1 }, position_name: null, spd_pct: 100, description: "" },
];

describe("flow step editing", () => {
  it("moves and renumbers steps", () => {
    expect(moveFlowStep(steps, 0, 1).map((step) => step.action)).toEqual(["close", "home"]);
    expect(moveFlowStep(steps, 0, 1).map((step) => step.step_id)).toEqual([1, 2]);
  });
  it("copies parameters without sharing the source object", () => {
    const cloned = cloneFlowStep(steps, 0);
    expect(cloned).toHaveLength(3);
    expect(cloned[1].params).toEqual({ x: 0 });
    expect(cloned[1].params).not.toBe(cloned[0].params);
  });
  it("removes only the requested step", () => {
    expect(removeFlowStep(steps, 0).map((step) => step.step_id)).toEqual([1]);
  });
});
