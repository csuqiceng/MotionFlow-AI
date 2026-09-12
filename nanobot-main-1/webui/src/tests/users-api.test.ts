import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/transport/http";
import {
  createUser,
  listUsers,
  resetUserPassword,
  updateUser,
} from "@/lib/users-api";
import { deleteUser as transportDeleteUser } from "@/transport/users";

vi.mock("@/transport/http", () => ({ fetchWithTimeout: vi.fn() }));

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
}) as unknown as Response;

afterEach(() => vi.mocked(fetchWithTimeout).mockReset());

describe("users-api", () => {
  it("lists accounts with both authenticated tokens", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { users: [] } }));

    await listUsers("gateway", "engineer");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/identity/users",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer gateway",
          "X-Robot-User-Token": "engineer",
        }),
      }),
      15_000,
    );
  });

  it("sends create, update, and reset-password payloads through REST bodies", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: {} }));

    await createUser("gateway", "engineer", { username: "alice", role: "operator", password: "pass" });
    await updateUser("gateway", "engineer", "u-1", { enabled: false, role: "engineer" });
    await resetUserPassword("gateway", "engineer", "u-1", "next-pass");

    const calls = vi.mocked(fetchWithTimeout).mock.calls;
    expect(calls[0][0]).toBe("/api/identity/users");
    expect(calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ username: "alice", role: "operator", password: "pass" }) });
    expect(calls[1][0]).toBe("/api/identity/users/u-1");
    expect(calls[1][1]).toMatchObject({ method: "PATCH", body: JSON.stringify({ enabled: false, role: "engineer" }) });
    expect(calls[2][0]).toBe("/api/identity/users/u-1/password");
    expect(calls[2][1]).toMatchObject({ method: "POST", body: JSON.stringify({ new_password: "next-pass" }) });
  });

  it("exposes authenticated deletion from transport", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: { deleted: "u-1" } }));
    await transportDeleteUser("gateway", "engineer", "u/1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/api/identity/users/u%2F1",
      expect.objectContaining({ method: "DELETE", headers: expect.objectContaining({ "X-Robot-User-Token": "engineer" }) }),
      15_000,
    );
  });
});
