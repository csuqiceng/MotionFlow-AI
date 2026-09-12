import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("robot feature public boundary", () => {
  it("exposes a barrel and the application shell imports only that barrel", () => {
    const root = resolve(process.cwd(), "src");
    const barrel = readFileSync(resolve(root, "robot", "index.ts"), "utf8");
    const app = readFileSync(resolve(root, "App.tsx"), "utf8");

    expect(barrel).toContain("RobotSidePanel");
    expect(barrel).toContain("CommandLibraryPage");
    expect(app).toContain('from "@/robot"');
    expect(app).not.toMatch(/from "@\/robot\//);
  });
});
