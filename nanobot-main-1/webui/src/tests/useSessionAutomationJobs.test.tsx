import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionAutomationJobs } from "@/hooks/useSessionAutomationJobs";
import * as api from "@/lib/api";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchSessionAutomations: vi.fn(),
  };
});

function wrap({ token, userToken }: { token: string; userToken: string }) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={{} as unknown as import("@/lib/nanobot-client").NanobotClient}
        token={token}
        userToken={userToken}
      >
        {children}
      </ClientProvider>
    );
  };
}

describe("useSessionAutomationJobs", () => {
  beforeEach(() => {
    vi.mocked(api.fetchSessionAutomations).mockReset();
  });

  it("forwards userToken from useClient as the 2nd arg to fetchSessionAutomations", async () => {
    vi.mocked(api.fetchSessionAutomations).mockResolvedValue({ jobs: [] });

    renderHook(
      ({ open, sessionKey, token }) =>
        useSessionAutomationJobs(open, token, sessionKey),
      {
        initialProps: { open: true, sessionKey: "websocket:chat-1", token: "ws" },
        wrapper: wrap({ token: "ws", userToken: "user-auto" }),
      },
    );

    await waitFor(() => expect(api.fetchSessionAutomations).toHaveBeenCalled());
    expect(api.fetchSessionAutomations).toHaveBeenCalledWith("ws", "user-auto", "websocket:chat-1");
  });
});
