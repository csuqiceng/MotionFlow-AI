import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductProfileSettings } from "@/components/settings/ProductProfileSettings";

const profile = {
  protocol_version: 1,
  backend_mode: "simulation",
  available_backend_modes: ["simulation", "zmotion_readonly"],
  capabilities: { protocol_version: 1, supports_state_read: true },
  tools: [
    { tool_id: "robot_arm", version: "1.0.0", risk_level: "motion" as const, required_capabilities: [], enabled: true, eligible: true, reason: null },
    { tool_id: "robot_knowledge", version: "1.0.0", risk_level: "read" as const, required_capabilities: [], enabled: false, eligible: true, reason: null },
  ],
};

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => ({ ok: true, data }) } as Response;
}

describe("ProductProfileSettings", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("saves backend and enabled Tools without rendering AI configuration", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(profile))
      .mockResolvedValueOnce(response({ ...profile, backend_mode: "zmotion_readonly" }));
    vi.stubGlobal("fetch", fetch);

    render(<ProductProfileSettings gatewayToken="gateway" userToken="engineer" />);

    await screen.findByRole("heading", { name: "机器人与 Tool 配置" });
    expect(screen.queryByText(/Provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Model/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/API key/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("机械手后端"), { target: { value: "zmotion_readonly" } });
    fireEvent.click(screen.getByLabelText(/robot_knowledge/));
    fireEvent.click(screen.getByRole("button", { name: "保存机器人与 Tool 配置" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/management/product-profile",
      expect.objectContaining({
        method: "PUT",
        headers: expect.objectContaining({
          Authorization: "Bearer gateway",
          "X-Robot-User-Token": "engineer",
        }),
        body: JSON.stringify({ backend_mode: "zmotion_readonly", enabled_tools: ["robot_arm", "robot_knowledge"] }),
      }),
    );
  });
});
