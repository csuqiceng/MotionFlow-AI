import { describe, expect, it } from "vitest";

import { shouldUseRobotOperatorApp } from "@/App";

describe("shouldUseRobotOperatorApp", () => {
  it("uses operator app for native runtime by default", () => {
    expect(shouldUseRobotOperatorApp("native", "")).toBe(true);
  });

  it("keeps engineer shell reachable", () => {
    expect(shouldUseRobotOperatorApp("native", "#/engineer")).toBe(false);
  });

  it("allows browser opt-in with hash route", () => {
    expect(shouldUseRobotOperatorApp("browser", "#/operator")).toBe(true);
  });

  it("defaults browser runtime to the engineer shell", () => {
    expect(shouldUseRobotOperatorApp("browser", "")).toBe(false);
  });
});
