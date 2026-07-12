import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";

vi.mock("@/robot/hooks/useRobotLibrary", () => ({
  useRobotLibrary: vi.fn(),
}));

import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";
import { CommandLibraryPage } from "@/robot/library/CommandLibraryPage";
import { FlowDetail } from "@/robot/library/FlowDetail";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

function renderPage() {
  return render(
    <I18nextProvider i18n={i18n}>
      <CommandLibraryPage token="tok" />
    </I18nextProvider>,
  );
}

afterEach(() => vi.mocked(useRobotLibrary).mockReset());

describe("CommandLibraryPage", () => {
  it("renders the commands tab with list items and switches to flows", async () => {
    vi.mocked(useRobotLibrary).mockImplementation((_token, tab) => ({
      items: tab === "commands"
        ? [{ id: "home", name: "home", component_id: "linear_move" } as LibraryCommand]
        : [{ name: "PickPlace", steps: [] } as LibraryFlow],
      loading: false,
      error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(),
      selectedId: null,
      select: vi.fn(),
      detail: null,
      detailLoading: false,
      detailError: null,
    }));
    renderPage();
    expect(screen.getByTestId("command-library-page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "home" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Flows/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "PickPlace" })).toBeInTheDocument(),
    );
  });

  it("renders the empty state", () => {
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [], loading: false, error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: null, select: vi.fn(),
      detail: null, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText(/No items/i)).toBeInTheDocument();
  });

  it("renders the error state", () => {
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [], loading: false, error: "boom",
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: null, select: vi.fn(),
      detail: null, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it("renders command detail when selected", () => {
    const cmd = {
      id: "home", name: "home", component_id: "linear_move",
      parameters: { target_z: 1270.0 }, aliases: ["回零"], description: "go home",
      risk_level: "high", status: "published", version: 1, source: "legacy-import",
      created_by: "", created_at: "", updated_at: "", published_at: "",
    } as LibraryCommand;
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [cmd], loading: false, error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: "home", select: vi.fn(),
      detail: cmd, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText("target_z")).toBeInTheDocument();
    expect(screen.getByText("1270")).toBeInTheDocument();
  });
});

describe("FlowDetail", () => {
  it("renders steps with duplicate step_ids without key conflicts", () => {
    // Real flows migrated from legacy data can have step_id default to 0 for
    // every step — the step list must still render all of them (keyed by index).
    const flow = {
      name: "X",
      description: "",
      steps: [
        { step_id: 0, action: "move-a", func_id: 108, params: {}, position_name: null, spd_pct: 50, description: "" },
        { step_id: 0, action: "delay-b", func_id: 110, params: {}, position_name: null, spd_pct: 50, description: "" },
        { step_id: 0, action: "io-c", func_id: 120, params: {}, position_name: null, spd_pct: 50, description: "" },
      ],
      step_delay_ms: 1000,
      rehearsal_spd: 20,
      confirmed: false,
      version: 1,
      state: "idle",
      current_step: 0,
      created_by: "",
      created_at: "",
      updated_at: "",
    } as LibraryFlow;
    render(
      <I18nextProvider i18n={i18n}>
        <FlowDetail flow={flow} />
      </I18nextProvider>,
    );
    expect(screen.getByText("move-a")).toBeInTheDocument();
    expect(screen.getByText("delay-b")).toBeInTheDocument();
    expect(screen.getByText("io-c")).toBeInTheDocument();
    expect(screen.getAllByText(/func=/)).toHaveLength(3);
  });
});
