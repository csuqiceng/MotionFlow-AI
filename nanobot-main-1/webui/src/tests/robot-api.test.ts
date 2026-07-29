import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/transport/http";
import { robotConfirm, robotPendingPlan, robotStatus, robotSystemAction } from "@/lib/robot-api";
import { robotExecute as transportRobotExecute } from "@/transport/robot";

vi.mock("@/transport/http", () => ({ fetchWithTimeout: vi.fn() }));

const response = (body: unknown) => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: async () => body,
}) as unknown as Response;

afterEach(() => vi.mocked(fetchWithTimeout).mockReset());

describe("robot-api", () => {
  it("uses the robot-server REST plan contract", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(response({ plan_id: "plan-1" }));
    await robotPendingPlan("gateway", "chat-1", "linear_move", { speed_pct: 20 }, "user-token");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/robot/plans",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "chat-1", command: "linear_move", parameters: { speed_pct: 20 } }),
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Robot-User-Token": "user-token",
        }),
      }),
      30_000,
    );
  });

  it("uses a plan-specific confirm route", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(response({ confirm_code: "RC-test" }));
    await robotConfirm("gateway", "chat-1", "plan/1", true, true, "user-token");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/robot/plans/plan%2F1/confirm",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          session_id: "chat-1", confirm_work_area_clear: true, confirm_estop_ready: true,
        }),
        headers: expect.objectContaining({ "X-Robot-User-Token": "user-token" }),
      }),
      30_000,
    );
  });

  it("keeps system actions inside the full confirmation chain", async () => {
    vi.mocked(fetchWithTimeout)
      .mockResolvedValueOnce(response({ plan_id: "plan-system" }))
      .mockResolvedValueOnce(response({ confirm_code: "RC-system" }))
      .mockResolvedValueOnce(response({ ok: true, state: "completed", message: "done", data: {}, errors: [] }));

    await robotSystemAction("gateway", "side-panel", "pause", "user-token");

    const calls = vi.mocked(fetchWithTimeout).mock.calls;
    expect(calls.map(([url]) => String(url))).toEqual([
      "/api/robot/plans",
      "/api/robot/plans/plan-system/confirm",
      "/api/robot/plans/plan-system/execute",
    ]);
  });

  it("reads status without sending a retired gateway body header", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(response({ ok: true, data: {} }));
    await robotStatus("gateway");

    const [, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe("/api/robot/status");
    expect((init as RequestInit).method).toBe("GET");
    expect((init as RequestInit).headers).not.toHaveProperty("X-Nanobot-Robot-Body");
  });

  it("exposes the same safe execution contract from transport", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(response({ ok: true, data: {} }));

    await transportRobotExecute("gateway", "chat-1", "plan/1", "RC-test", "user-token");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/robot/plans/plan%2F1/execute",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "chat-1", confirm_code: "RC-test" }),
        headers: expect.objectContaining({ "X-Robot-User-Token": "user-token" }),
      }),
      30_000,
    );
  });
});
