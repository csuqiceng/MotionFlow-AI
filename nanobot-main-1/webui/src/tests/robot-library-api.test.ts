import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/lib/http";
import {
  robotLibraryCommand,
  robotLibraryCommands,
  robotLibraryFlow,
  robotLibraryFlows,
  type LibraryCommand,
  type LibraryFlow,
} from "@/lib/robot-library-api";

vi.mock("@/lib/http", () => ({
  fetchWithTimeout: vi.fn(),
}));

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: async () => body,
}) as unknown as Response;

afterEach(() => {
  vi.mocked(fetchWithTimeout).mockReset();
});

describe("robot-library-api", () => {
  it("lists commands with filters encoded as query params", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(
      okResponse({ ok: true, data: { items: [], total: 0 } }),
    );
    await robotLibraryCommands("tok", { q: "home", risk_level: "high" });
    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/library/commands?q=home&risk_level=high");
    expect((init as RequestInit).method).toBe("GET");
    expect(((init as RequestInit).headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer tok",
    );
  });

  it("fetches a single command by id", async () => {
    const cmd: LibraryCommand = {
      id: "home", name: "home", component_id: "linear_move", parameters: {},
      aliases: [], description: "", risk_level: "high", status: "published",
      version: 1, source: "legacy-import", created_by: "", created_at: "",
      updated_at: "", published_at: "",
    };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: cmd }));
    const result = await robotLibraryCommand("tok", "home");
    expect(result.data.id).toBe("home");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/commands/home",
    );
  });

  it("lists flows", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(
      okResponse({ ok: true, data: { items: [], total: 0 } }),
    );
    await robotLibraryFlows("tok");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/flows",
    );
  });

  it("fetches a single flow by name (url-encoded)", async () => {
    const flow: LibraryFlow = {
      name: "休息姿态", description: "", steps: [], step_delay_ms: 1000,
      rehearsal_spd: 20, confirmed: false, version: 1, state: "idle",
      current_step: 0, created_by: "", created_at: "", updated_at: "",
    };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: flow }));
    const result = await robotLibraryFlow("tok", "休息姿态");
    expect(result.data.name).toBe("休息姿态");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/flows/" + encodeURIComponent("休息姿态"),
    );
  });

  it("throws on non-ok response", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue({
      ok: false, status: 404, text: async () => "not found",
    } as unknown as Response);
    await expect(robotLibraryCommand("tok", "nope")).rejects.toThrow();
  });
});
