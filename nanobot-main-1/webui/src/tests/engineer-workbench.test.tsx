import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/robot/hooks/useRobotLibrary", () => ({ useRobotLibrary: vi.fn() }));
vi.mock("@/lib/robot-library-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/robot-library-api")>();
  return { ...actual,
    robotLibraryComponents: vi.fn().mockReturnValue(new Promise(() => {})),
    libraryExecutions: vi.fn().mockReturnValue(new Promise(() => {})),
    runLibraryCommand: vi.fn(), libraryExecution: vi.fn(), libraryExecutionControl: vi.fn(),
  };
});
vi.mock("@/lib/engineer-workbench-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/engineer-workbench-api")>();
  return { ...actual,
    engineerStartCommandDraft: vi.fn(), engineerStartFlowDraft: vi.fn(),
    engineerCreateCommand: vi.fn(), engineerCreateFlow: vi.fn(),
    engineerUpdateCommandDraft: vi.fn(), engineerUpdateFlowDraft: vi.fn(),
    engineerValidateFlowDraft: vi.fn(), engineerPublishCommand: vi.fn(),
    engineerPublishFlow: vi.fn(), engineerArchiveCommand: vi.fn(), engineerArchiveFlow: vi.fn(),
    engineerDuplicateCommand: vi.fn(), engineerDuplicateFlow: vi.fn(),
  };
});

import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";
import { CommandDraftEditor } from "@/robot/workbench/CommandDraftEditor";
import { FlowDraftEditor } from "@/robot/workbench/FlowDraftEditor";
import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";
import i18n from "@/i18n";
import { EngineerConflictError, engineerArchiveCommand, engineerArchiveFlow, engineerCreateCommand, engineerCreateFlow, engineerDuplicateCommand, engineerPublishCommand, engineerPublishFlow, engineerStartCommandDraft, engineerStartFlowDraft, engineerUpdateCommandDraft, engineerValidateFlowDraft } from "@/lib/engineer-workbench-api";
import { libraryExecution, libraryExecutionControl, libraryExecutions, runLibraryCommand } from "@/lib/robot-library-api";

const command = { id: "home", name: "Home", aliases: [], description: "", component_id: "linear_move", parameters: {}, risk_level: "low", status: "published", version: 1, source: "", created_by: "", created_at: "", updated_at: "", published_at: "" };
const flow = { flow_id: "pick_place", name: "Pick Place", description: "", steps: [{ step_id: 1, action: "pick", func_id: 101, params: {}, position_name: null, spd_pct: 50, description: "" }], step_delay_ms: 0, rehearsal_spd: 100, confirmed: false, version: 1, state: "idle", current_step: 0, created_by: "", created_at: "", updated_at: "" };
const library = () => ({ items: [command], loading: false, error: null, filters: { q: "", component_id: "", risk_level: "", status: "" }, setFilters: vi.fn(), selectedId: "home", select: vi.fn(), detail: command, detailLoading: false, detailError: null, refresh: vi.fn() });

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage("en");
  });
  vi.clearAllMocks();
  vi.mocked(libraryExecutions).mockReturnValue(new Promise(() => {}));
});

describe("EngineerWorkbench", () => {
  it("adds a flow step by selecting a published command template", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<FlowDraftEditor draft={{ name: "Routine", steps: [] }} commands={[command]} onSave={onSave} />);
    await user.selectOptions(screen.getByLabelText("Available commands"), "home");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByText("1. Home")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ steps: [expect.objectContaining({ action: "Home", func_id: 108, params: {} })] }));
  });
  it("creates a command with a selected component and typed parameter fields", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<CommandDraftEditor
      draft={{ name: "Wait", aliases: [], description: "", component_id: "", parameters: {} }}
      components={[{ id: "delay", func_num: 110, name: "Delay", parameters: [{ name: "delay_sec", type: "float", default: 1, required: true }] }]}
      onSave={onSave}
    />);
    await user.selectOptions(screen.getByLabelText("Command type"), "delay");
    await user.clear(screen.getByLabelText("delay_sec"));
    await user.type(screen.getByLabelText("delay_sec"), "2");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ component_id: "delay", parameters: { delay_sec: 2 } }));
  });
  it("renders engineer authoring controls in Chinese when zh-CN is active", async () => {
    await act(async () => {
      await i18n.changeLanguage("zh-CN");
    });
    vi.mocked(useRobotLibrary).mockReturnValue(library());

    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    expect(screen.getByRole("button", { name: "新建命令" })).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "新建命令" }));
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeVisible();
  });

  it("shows New command only to engineers", () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    expect(screen.getByRole("button", { name: "New command" })).toBeVisible();
  });

  it("does not expose authoring actions to operators", () => {
    render(<EngineerWorkbench role="operator" gatewayToken="gateway" userToken="operator" />);
    expect(screen.queryByRole("button", { name: "New command" })).not.toBeInTheDocument();
  });

  it("starts a draft with both tokens then confirms before publishing", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    vi.mocked(engineerStartCommandDraft).mockResolvedValue({ ok: true, data: { draft: { ...command, revision: 1 } } });
    vi.mocked(engineerPublishCommand).mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    await user.click(screen.getByRole("button", { name: "Edit draft" }));
    await waitFor(() => expect(engineerStartCommandDraft).toHaveBeenCalledWith("gateway", "engineer", "home"));
    await user.click(screen.getByRole("button", { name: "Publish command" }));
    expect(screen.getByText("Publish command?")).toBeVisible();
    expect(engineerPublishCommand).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(engineerPublishCommand).toHaveBeenCalledWith("gateway", "engineer", "home"));
  });

  it("preserves full flow-step fields through add, reorder, remove, and save", async () => {
    const user = userEvent.setup(); const onSave = vi.fn();
    render(<FlowDraftEditor draft={{ name: "Pick", steps: [
      { step_id: 1, action: "pick", func_id: 101, params: { grip: true }, position_name: "P1", spd_pct: 50, description: "grab" },
      { step_id: 2, action: "place", func_id: 102, params: { release: true }, position_name: "P2", spd_pct: 60, description: "drop" },
    ] }} onSave={onSave} />);
    await user.click(screen.getByRole("button", { name: "Add step" }));
    await user.click(screen.getByRole("button", { name: "Move step 2 up" }));
    await user.click(screen.getByRole("button", { name: "Remove step 3" }));
    await user.clear(screen.getByRole("spinbutton", { name: "Step 1 id" }));
    await user.type(screen.getByRole("spinbutton", { name: "Step 1 id" }), "22");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ steps: [
      expect.objectContaining({ step_id: 2, action: "place", func_id: 102, spd_pct: 60, params: { release: true }, position_name: "P2", description: "drop" }),
      expect.objectContaining({ action: "pick", params: { grip: true }, position_name: "P1", description: "grab" }),
    ] }));
  });

  it("shows a draft conflict and refreshes the library after a successful command save", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    vi.mocked(engineerStartCommandDraft).mockResolvedValue({ ok: true, data: { draft: { ...command, revision: 1 } } });
    vi.mocked(engineerUpdateCommandDraft).mockResolvedValue({ ok: true, data: { draft: { ...command, revision: 2 } } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    await user.click(screen.getByRole("button", { name: "Edit draft" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(engineerUpdateCommandDraft).toHaveBeenCalledWith("gateway", "engineer", "home", expect.objectContaining({ expected_revision: 1 })));
    await waitFor(() => expect(vi.mocked(useRobotLibrary).mock.calls.length).toBeGreaterThan(1));
  });

  it("validates an edited flow using both tokens", async () => {
    vi.mocked(useRobotLibrary).mockImplementation((_token, tab) => tab === "flows" ? ({ ...library(), items: [flow], selectedId: "pick_place", detail: flow }) : library());
    vi.mocked(engineerStartFlowDraft).mockResolvedValue({ ok: true, data: { draft: { ...flow, revision: 1 } } });
    vi.mocked(engineerValidateFlowDraft).mockResolvedValue({ ok: true, data: { errors: [] } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    await user.click(screen.getByRole("tab", { name: "Flows" }));
    await user.click(screen.getByRole("button", { name: "Edit draft" }));
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(engineerStartFlowDraft).toHaveBeenCalledWith("gateway", "engineer", "pick_place"));
    await waitFor(() => expect(engineerValidateFlowDraft).toHaveBeenCalledWith("gateway", "engineer", "pick_place"));
    expect(screen.getByText("Validation passed.")).toBeVisible();
  });

  it("keeps a conflict error visible", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    vi.mocked(engineerStartCommandDraft).mockRejectedValue(new EngineerConflictError("Draft revision mismatch", { data: { current_revision: 7 } }));
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    await user.click(screen.getByRole("button", { name: "Edit draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Current revision: 7");
  });

  it("offers an actionable detail draft control before publishing", () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    expect(screen.getByRole("button", { name: "Edit draft" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run command" })).toBeEnabled();
  });

  it("controls a paused execution from the engineer workbench", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    vi.mocked(runLibraryCommand).mockResolvedValue({ ok: true, data: { execution_id: "run-1", state: "queued" } });
    vi.mocked(libraryExecution).mockResolvedValue({ ok: true, data: {
      execution_id: "run-1", state: "paused", message: "", steps: [], allowed_actions: ["resume", "step", "stop"],
    } });
    vi.mocked(libraryExecutionControl).mockResolvedValue({ ok: true, data: {
      execution_id: "run-1", state: "running", message: "", steps: [], allowed_actions: ["pause", "stop"],
    } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "Run command" }));
    await screen.findByRole("button", { name: "继续" });
    await user.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() => expect(libraryExecutionControl).toHaveBeenCalledWith("gateway", "engineer", "run-1", "resume"));
  });

  it("shows a saved execution history entry for the engineer", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(library());
    vi.mocked(libraryExecutions).mockResolvedValue({ ok: true, data: { items: [{
      execution_id: "history-1", kind: "flow", source_id: "delay-flow", state: "completed", message: "", steps: [],
    }], total: 1 } });
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);
    expect(await screen.findByText("Execution history")).toBeVisible();
    expect(screen.getByRole("button", { name: /delay-flow/ })).toBeVisible();
  });

  it("keeps a newly created command draft open through an in-place refresh and publishes that draft", async () => {
    const current = library();
    vi.mocked(useRobotLibrary).mockReturnValue(current);
    vi.mocked(engineerCreateCommand).mockResolvedValue({ ok: true, data: { command_id: "new-home", draft: { revision: 1 } } });
    vi.mocked(engineerPublishCommand).mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "New command" }));
    await user.type(screen.getByRole("textbox", { name: "Command name" }), "New home");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(engineerCreateCommand).toHaveBeenCalled());
    expect(current.refresh).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Publish command" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Publish command" }));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(engineerPublishCommand).toHaveBeenCalledWith("gateway", "engineer", "new-home"));
  });

  it("keeps a newly created flow draft open through an in-place refresh and publishes that draft", async () => {
    const current = library();
    vi.mocked(useRobotLibrary).mockImplementation((_token, tab) => tab === "flows" ? ({ ...current, items: [flow], selectedId: "pick_place", detail: flow }) : current);
    vi.mocked(engineerCreateFlow).mockResolvedValue({ ok: true, data: { flow_id: "new_pick", draft: { revision: 1 } } });
    vi.mocked(engineerPublishFlow).mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("tab", { name: "Flows" }));
    await user.click(screen.getByRole("button", { name: "New flow" }));
    await user.type(screen.getByRole("textbox", { name: "Flow name" }), "New pick");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(engineerCreateFlow).toHaveBeenCalled());
    expect(current.refresh).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Publish flow" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Publish flow" }));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(engineerPublishFlow).toHaveBeenCalledWith("gateway", "engineer", "new_pick"));
  });

  it("confirms and archives a command without invoking robot execution", async () => {
    const current = library();
    vi.mocked(useRobotLibrary).mockReturnValue(current);
    vi.mocked(engineerArchiveCommand).mockResolvedValue({ ok: true, data: { archived: "home" } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "Archive command" }));
    expect(screen.getByText("Archive command?")).toBeVisible();
    expect(engineerArchiveCommand).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(engineerArchiveCommand).toHaveBeenCalledWith("gateway", "engineer", "home"));
    expect(current.refresh).toHaveBeenCalled();
  });

  it("confirms and archives a flow without invoking robot execution", async () => {
    const current = library();
    vi.mocked(useRobotLibrary).mockImplementation((_token, tab) => tab === "flows" ? ({ ...current, items: [flow], selectedId: "pick_place", detail: flow }) : current);
    vi.mocked(engineerArchiveFlow).mockResolvedValue({ ok: true, data: { archived: "pick_place" } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("tab", { name: "Flows" }));
    await user.click(screen.getByRole("button", { name: "Archive flow" }));
    expect(screen.getByText("Archive flow?")).toBeVisible();
    expect(engineerArchiveFlow).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(engineerArchiveFlow).toHaveBeenCalledWith("gateway", "engineer", "pick_place"));
    expect(current.refresh).toHaveBeenCalled();
  });

  it("creates an editable command copy with the chosen name", async () => {
    const current = library();
    vi.mocked(useRobotLibrary).mockReturnValue(current);
    vi.mocked(engineerDuplicateCommand).mockResolvedValue({ ok: true, data: {
      command_id: "home-copy", draft: { ...command, name: "Home copy", revision: 1 },
    } });
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "Save as" }));
    await user.clear(screen.getByRole("textbox", { name: "Copy name" }));
    await user.type(screen.getByRole("textbox", { name: "Copy name" }), "Home copy");
    await user.click(screen.getByRole("button", { name: "Create copy" }));

    await waitFor(() => expect(engineerDuplicateCommand).toHaveBeenCalledWith("gateway", "engineer", "home", "Home copy"));
    expect(current.refresh).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Publish command" })).toBeVisible();
  });
});
