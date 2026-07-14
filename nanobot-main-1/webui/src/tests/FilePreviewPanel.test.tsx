import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import * as api from "@/lib/api";
import { setAppLanguage } from "@/i18n";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFilePreview: vi.fn(),
  };
});

describe("FilePreviewPanel", () => {
  beforeEach(async () => {
    vi.mocked(api.fetchFilePreview).mockReset();
    await setAppLanguage("en");
  });

  it("forwards userToken from useClient as the 2nd arg to fetchFilePreview", async () => {
    vi.mocked(api.fetchFilePreview).mockResolvedValue({
      path: "/tmp/project/hook.py",
      display_path: "hook.py",
      project_path: "/tmp/project",
      language: "python",
      content: "print('hi')",
      size: 12,
      truncated: false,
    });

    render(
      <ClientProvider
        client={{} as unknown as import("@/lib/nanobot-client").NanobotClient}
        token="ws"
        userToken="user-preview"
      >
        <FilePreviewPanel
          sessionKey="websocket:chat-1"
          path="/tmp/project/hook.py"
          token="ws"
          onClose={() => {}}
        />
      </ClientProvider>,
    );

    await waitFor(() => expect(api.fetchFilePreview).toHaveBeenCalled());
    expect(api.fetchFilePreview).toHaveBeenCalledWith(
      "ws",
      "user-preview",
      "websocket:chat-1",
      "/tmp/project/hook.py",
    );
  });
});
