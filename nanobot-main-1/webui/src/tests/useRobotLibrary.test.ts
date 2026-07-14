import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/robot-library-api", () => ({
  robotLibraryCommands: vi.fn(),
  robotLibraryCommand: vi.fn(),
  robotLibraryFlows: vi.fn(),
  robotLibraryFlow: vi.fn(),
}));

import {
  robotLibraryCommand,
  robotLibraryCommands,
  robotLibraryFlow,
  robotLibraryFlows,
  type LibraryCommand,
  type LibraryFlow,
} from "@/lib/robot-library-api";
import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";

afterEach(() => {
  vi.mocked(robotLibraryCommands).mockReset();
  vi.mocked(robotLibraryCommand).mockReset();
  vi.mocked(robotLibraryFlows).mockReset();
  vi.mocked(robotLibraryFlow).mockReset();
});

describe("useRobotLibrary", () => {
  it("loads the command list for the commands tab", async () => {
    vi.mocked(robotLibraryCommands).mockResolvedValue({
      ok: true, data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it("loads the flow list for the flows tab", async () => {
    vi.mocked(robotLibraryFlows).mockResolvedValue({
      ok: true, data: { items: [{ name: "PickPlace" } as LibraryFlow], total: 1 },
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "flows"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(robotLibraryFlows).toHaveBeenCalledWith("tok");
    expect(result.current.items[0]).toMatchObject({ name: "PickPlace" });
  });

  it("loads detail when an item is selected", async () => {
    vi.mocked(robotLibraryCommands).mockResolvedValue({
      ok: true, data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
    });
    vi.mocked(robotLibraryCommand).mockResolvedValue({
      ok: true, data: { id: "home", name: "home", component_id: "linear_move" } as LibraryCommand,
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.select("home"));
    await waitFor(() => expect(result.current.detail).not.toBeNull());
    expect(robotLibraryCommand).toHaveBeenCalledWith("tok", "home");
    expect(result.current.detail).toMatchObject({ id: "home" });
  });

  it("refreshes the selected detail after a published version changes", async () => {
    vi.mocked(robotLibraryCommands).mockResolvedValue({
      ok: true, data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
    });
    vi.mocked(robotLibraryCommand)
      .mockResolvedValueOnce({ ok: true, data: { id: "home", name: "home", version: 1 } as LibraryCommand })
      .mockResolvedValueOnce({ ok: true, data: { id: "home", name: "home", version: 2 } as LibraryCommand });
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.select("home"));
    await waitFor(() => expect(result.current.detail).toMatchObject({ version: 1 }));

    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.detail).toMatchObject({ version: 2 }));
    expect(robotLibraryCommand).toHaveBeenCalledTimes(2);
  });

  it("exposes a list error", async () => {
    vi.mocked(robotLibraryCommands).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.items).toEqual([]);
  });

  it("filters flows client-side by q (name/description)", async () => {
    vi.mocked(robotLibraryFlows).mockResolvedValue({
      ok: true,
      data: {
        items: [
          { name: "PickPlace", description: "pick and place", steps: [] } as LibraryFlow,
          { name: "Rest", description: "go to rest pose", steps: [] } as LibraryFlow,
          { name: "Home", description: "", steps: [] } as LibraryFlow,
        ],
        total: 3,
      },
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "flows"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(3);

    act(() => result.current.setFilters({ q: "pick" }));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect((result.current.items[0] as LibraryFlow).name).toBe("PickPlace");

    // matches description too
    act(() => result.current.setFilters({ q: "rest pose" }));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect((result.current.items[0] as LibraryFlow).name).toBe("Rest");

    // clearing q restores all
    act(() => result.current.setFilters({ q: "" }));
    await waitFor(() => expect(result.current.items).toHaveLength(3));
  });
});

it("clears stale items when the tab switches before the new fetch resolves", async () => {
  vi.mocked(robotLibraryCommands).mockResolvedValue({
    ok: true,
    data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
  });
  // flows fetch never resolves — simulates the pending window after a tab switch.
  vi.mocked(robotLibraryFlows).mockImplementation(() => new Promise(() => {}));
  const { result, rerender } = renderHook(
    ({ tab }) => useRobotLibrary("tok", tab),
    { initialProps: { tab: "commands" as const } },
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.items).toHaveLength(1);

  rerender({ tab: "flows" as const });
  // Stale commands must NOT remain rendered under the flows tab.
  expect(result.current.items).toEqual([]);
  expect(result.current.loading).toBe(true);
});
