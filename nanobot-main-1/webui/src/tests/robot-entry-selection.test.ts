import { describe, expect, it } from "vitest";

import {
  readShellRoute,
  shellRouteHash,
  type ShellRoute,
} from "@/App";

// Slice ② (F3): shell selection is now driven by the authenticated user's
// role (operator → operator console incl. RobotSidePanel + #/operator routing;
// engineer → standard #/new, #/chat, #/settings shell), not by the legacy
// shouldUseRobotOperatorApp(surface, hash) helper (removed in F3). These tests
// cover the operator-style routing that the operator role still triggers via
// shellRouteHash(route, operator=true).
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

  it("non-operator (engineer) chat hash is unchanged (#/chat/<key>)", () => {
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
