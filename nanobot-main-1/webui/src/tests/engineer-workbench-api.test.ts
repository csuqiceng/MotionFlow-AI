import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/lib/http";
import {
  EngineerConflictError,
  engineerCommandEntities,
  engineerCreateCommand,
  engineerCreateFlow,
  engineerStartCommandDraft,
  engineerUpdateFlowDraft,
  engineerValidateFlowDraft,
} from "@/lib/engineer-workbench-api";

vi.mock("@/lib/http", () => ({ fetchWithTimeout: vi.fn() }));

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
}) as unknown as Response;

afterEach(() => vi.mocked(fetchWithTimeout).mockReset());

describe("engineer-workbench-api", () => {
  it("uses the robot-server REST contract for command creation", async () => {
    const body = { name: "Home", component_id: "home", parameters: {} };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerCreateCommand("gateway", "engineer", body);

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/management/commands",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(body),
        credentials: "same-origin",
        headers: expect.objectContaining({
          Authorization: "Bearer gateway",
          "X-Robot-User-Token": "engineer",
          "Content-Type": "application/json",
        }),
      }),
      15_000,
    );
  });

  it("uses GET and the new identity header for engineer command lists", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { entities: [] } }));

    await engineerCommandEntities("gateway", "engineer");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/management/commands",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ "X-Robot-User-Token": "engineer" }),
      }),
      15_000,
    );
  });

  it("maps draft operations to POST and PUT routes", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));
    await engineerStartCommandDraft("gateway", "engineer", "home/one");
    await engineerUpdateFlowDraft("gateway", "engineer", "pick place", {
      expected_revision: 1,
      name: "Pick place",
      steps: [{ step_id: 1, action: "move", func_id: 1, params: {}, spd_pct: 20 }],
    });

    expect(fetchWithTimeout).toHaveBeenNthCalledWith(1,
      "/api/management/commands/home%2Fone/draft", expect.objectContaining({ method: "POST" }), 15_000);
    expect(fetchWithTimeout).toHaveBeenNthCalledWith(2,
      "/api/management/flows/pick%20place/draft", expect.objectContaining({ method: "PUT" }), 15_000);
  });

  it("uses POST for flow validation", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { errors: [] } }));
    await engineerValidateFlowDraft("gateway", "engineer", "pick place");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/management/flows/pick%20place/validate",
      expect.objectContaining({ method: "POST" }),
      15_000,
    );
  });

  it("preserves typed conflict details from robot-server", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(new Response(JSON.stringify({
      ok: false,
      data: { current_revision: 3 },
      error: { code: "draft_conflict", message: "reload" },
    }), { status: 409, headers: { "Content-Type": "application/json" } }));

    await expect(engineerCreateFlow("gateway", "engineer", { name: "Pick", steps: [] }))
      .rejects.toMatchObject({ name: EngineerConflictError.name, currentRevision: 3 });
  });
});
