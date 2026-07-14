import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/lib/http";
import {
  EngineerConflictError,
  engineerArchiveCommand,
  engineerArchiveFlow,
  engineerCreateCommand,
  engineerCreateFlow,
  engineerPublishCommand,
  engineerPublishFlow,
  engineerStartCommandDraft,
  engineerStartFlowDraft,
  engineerUpdateCommandDraft,
  engineerUpdateFlowDraft,
  engineerValidateFlowDraft,
} from "@/lib/engineer-workbench-api";

vi.mock("@/lib/http", () => ({ fetchWithTimeout: vi.fn() }));

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
}) as unknown as Response;

const robotBodyHeader = (body: unknown) => encodeURIComponent(JSON.stringify(body));

afterEach(() => vi.mocked(fetchWithTimeout).mockReset());

describe("engineer-workbench-api", () => {
  it("creates commands with gateway and engineer tokens", async () => {
    const body = { name: "Home", component_id: "home", parameters: {} };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerCreateCommand("gateway", "engineer", body);

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/robot/engineer/commands",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        headers: expect.objectContaining({
          Authorization: "Bearer gateway",
          "X-Nanobot-User-Token": "engineer",
          "X-Nanobot-Engineer-Action": "create",
          "X-Nanobot-Robot-Body": robotBodyHeader(body),
        }),
      }),
      15_000,
    );
  });

  it("uses start-draft action and an empty robot body for command drafts", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerStartCommandDraft("gateway", "engineer", "home/one");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/engineer/commands/home%2Fone/draft");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "start-draft",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
    expect((init as RequestInit).method).toBe("GET");
  });

  it("updates command drafts with their revision payload and update action", async () => {
    const draft = {
      expected_revision: 2,
      name: "Home v2",
      component_id: "home",
      parameters: {},
    };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerUpdateCommandDraft("gateway", "engineer", "home", draft);

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/engineer/commands/home/draft");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "update-draft",
      "X-Nanobot-Robot-Body": robotBodyHeader(draft),
    });
    expect((init as RequestInit).method).toBe("GET");
  });

  it("publishes commands without an action and with an empty robot body", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerPublishCommand("gateway", "engineer", "home");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(String(url)).toBe("/api/robot/engineer/commands/home/publish");
    expect((init as RequestInit).method).toBe("GET");
    expect(headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
    expect(headers["X-Nanobot-Engineer-Action"]).toBeUndefined();
  });

  it("updates flows with its revision payload and required action", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));
    const draft = {
      expected_revision: 1,
      name: "Pick place",
      steps: [{ step_id: 1, action: "move", func_id: 1, params: {}, spd_pct: 20 }],
    };

    await engineerUpdateFlowDraft("gateway", "engineer", "pick place", draft);

    const calls = vi.mocked(fetchWithTimeout).mock.calls;
    expect(String(calls[0][0])).toBe("/api/robot/engineer/flows/pick%20place/draft");
    const init = calls[0][1] as RequestInit;
    expect(init.method).toBe("GET");
    expect(init.headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "update-draft",
      "X-Nanobot-Robot-Body": robotBodyHeader(draft),
    });
  });

  it("does not add an action to command archive routes", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerArchiveCommand("gateway", "engineer", "home");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(String(url)).toBe("/api/robot/engineer/commands/home/archive");
    expect((init as RequestInit).method).toBe("GET");
    expect(headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
    expect(headers["X-Nanobot-Engineer-Action"]).toBeUndefined();
  });

  it("creates flows with their body and create action", async () => {
    const flow = { name: "Pick", steps: [] };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerCreateFlow("gateway", "engineer", flow);

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(String(url)).toBe("/api/robot/engineer/flows");
    expect((init as RequestInit).method).toBe("GET");
    expect(headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "create",
      "X-Nanobot-Robot-Body": robotBodyHeader(flow),
    });
  });

  it("starts flow drafts with the required action and an empty robot body", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerStartFlowDraft("gateway", "engineer", "pick place");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/engineer/flows/pick%20place/draft");
    expect((init as RequestInit).method).toBe("GET");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "start-draft",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
  });

  it("archives flows with the archive action and an empty robot body", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { archived: "pick" } }));

    await engineerArchiveFlow("gateway", "engineer", "pick");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(String(url)).toBe("/api/robot/engineer/flows/pick/archive");
    expect((init as RequestInit).method).toBe("GET");
    expect(headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "archive",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
  });

  it("validates flows with the validate action and an empty robot body", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { errors: [] } }));

    await engineerValidateFlowDraft("gateway", "engineer", "pick place");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/engineer/flows/pick%20place/validate");
    expect((init as RequestInit).method).toBe("GET");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "validate",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
  });

  it("publishes flows with the publish action and an empty robot body", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await engineerPublishFlow("gateway", "engineer", "pick place");

    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/engineer/flows/pick%20place/publish");
    expect((init as RequestInit).method).toBe("GET");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer gateway",
      "X-Nanobot-User-Token": "engineer",
      "X-Nanobot-Engineer-Action": "publish",
      "X-Nanobot-Robot-Body": robotBodyHeader({}),
    });
  });

  it("raises a typed conflict error with the current revision", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(new Response(JSON.stringify({
      ok: false,
      data: { current_revision: 3 },
      error: { code: "draft_conflict", message: "reload" },
    }), { status: 409, headers: { "Content-Type": "application/json" } }));

    const rejected = engineerCreateFlow("gateway", "engineer", { name: "Pick", steps: [] });
    await expect(rejected).rejects.toBeInstanceOf(EngineerConflictError);
    await expect(rejected).rejects.toMatchObject({
      status: 409,
      code: "draft_conflict",
      currentRevision: 3,
    });
  });

  it("keeps a 409 typed when a real response body is valid JSON without an error message", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(new Response(
      JSON.stringify({ data: { current_revision: 4 } }),
      { status: 409, headers: { "Content-Type": "application/json" } },
    ));

    const rejected = engineerUpdateCommandDraft("gateway", "engineer", "home", {
      expected_revision: 3, name: "Home", component_id: "home", parameters: {},
    });
    await expect(rejected).rejects.toMatchObject({
      name: "EngineerConflictError",
      currentRevision: 4,
    });
  });

  it("keeps a 409 typed and preserves malformed real-response text", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(new Response("not-json", {
      status: 409,
      headers: { "Content-Type": "application/json" },
    }));

    await expect(engineerCreateFlow("gateway", "engineer", { name: "Pick", steps: [] }))
      .rejects.toMatchObject({ name: "EngineerConflictError", message: "not-json" });
  });

  it("includes status and server text in other non-success errors", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue({
      ok: false,
      status: 403,
      text: async () => "forbidden",
    } as unknown as Response);

    await expect(engineerCreateFlow("gateway", "engineer", { name: "Pick", steps: [] }))
      .rejects.toThrow("Engineer workbench API /api/robot/engineer/flows failed: 403 forbidden");
  });
});
