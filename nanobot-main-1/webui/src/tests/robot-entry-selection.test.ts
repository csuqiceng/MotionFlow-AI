import { describe, expect, it } from "vitest";

import {
  readShellRoute,
  shellRouteHash,
  shouldUseRobotOperatorApp,
  type ShellRoute,
} from "@/App";

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

describe("operator route hash (stays on #/operator, doesn't jump to #/chat)", () => {
  it("parses #/operator as chat view with no active session", () => {
    window.history.replaceState(null, "", "/#/operator");
    expect(readShellRoute()).toEqual({
      view: "chat",
      activeKey: null,
      settingsSection: "overview",
    });
  });

  it("parses #/operator?chat=<key> and preserves the active session", () => {
    const key = "websocket:abc-123";
    window.history.replaceState(null, "", `/#/operator?chat=${encodeURIComponent(key)}`);
    expect(readShellRoute()).toEqual({
      view: "chat",
      activeKey: key,
      settingsSection: "overview",
    });
  });

  it("operator chat hash carries the session as ?chat= (not #/chat/<key>)", () => {
    const key = "websocket:abc-123";
    const route: ShellRoute = {
      view: "chat",
      activeKey: key,
      settingsSection: "overview",
    };
    expect(shellRouteHash(route, true)).toBe(
      `#/operator?chat=${encodeURIComponent(key)}`,
    );
  });

  it("operator chat hash with no session is #/operator (not #/new)", () => {
    const route: ShellRoute = {
      view: "chat",
      activeKey: null,
      settingsSection: "overview",
    };
    expect(shellRouteHash(route, true)).toBe("#/operator");
  });

  it("non-operator chat hash is unchanged (#/chat/<key>)", () => {
    const key = "websocket:abc-123";
    const route: ShellRoute = {
      view: "chat",
      activeKey: key,
      settingsSection: "overview",
    };
    expect(shellRouteHash(route, false)).toBe(`#/chat/${encodeURIComponent(key)}`);
  });

  it("readShellRoute -> shellRouteHash round-trips an operator session", () => {
    const key = "websocket:abc-123";
    window.history.replaceState(null, "", `/#/operator?chat=${encodeURIComponent(key)}`);
    const route = readShellRoute();
    expect(shellRouteHash(route, true)).toBe(
      `#/operator?chat=${encodeURIComponent(key)}`,
    );
  });
});
