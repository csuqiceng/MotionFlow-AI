import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/robot/hooks/useRobotLibrary", () => ({ useRobotLibrary: vi.fn() }));
vi.mock("@/lib/robot-library-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/robot-library-api")>();
  return {
    ...actual,
    robotLibraryComponents: vi.fn(),
    runLibraryCommand: vi.fn(),
    runLibraryFlow: vi.fn(),
    libraryExecution: vi.fn(),
    libraryExecutionControl: vi.fn(),
  };
});
vi.mock("@/lib/engineer-workbench-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/engineer-workbench-api")>();
  return {
    ...actual,
    engineerCreateCommand: vi.fn(),
    engineerUpdateCommand: vi.fn(),
    engineerDeleteCommand: vi.fn(),
    engineerCreateFlow: vi.fn(),
    engineerUpdateFlow: vi.fn(),
    engineerDeleteFlow: vi.fn(),
  };
});

import { EngineerWorkbench } from "@/robot/workbench/EngineerWorkbench";
import { CommandDraftEditor } from "@/robot/workbench/CommandDraftEditor";
import { FlowDraftEditor } from "@/robot/workbench/FlowDraftEditor";
import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";
import i18n from "@/i18n";
import {
  engineerCreateCommand,
  engineerDeleteCommand,
  engineerUpdateCommand,
} from "@/lib/engineer-workbench-api";
import { robotLibraryComponents } from "@/lib/robot-library-api";

const command = {
  id: "home",
  name: "Home",
  aliases: [],
  description: "",
  component_id: "linear_move",
  parameters: {},
  risk_level: "low",
  status: "published",
  version: 1,
  source: "",
  created_by: "",
  created_at: "",
  updated_at: "",
  published_at: "",
};

const component = {
  id: "delay",
  func_num: 110,
  name: "Delay",
  parameters: [{ name: "delay_sec", type: "float", default: 1, required: true }],
};

function commandLibrary() {
  return {
    items: [command],
    loading: false,
    error: null,
    filters: { q: "", component_id: "", risk_level: "", status: "" },
    setFilters: vi.fn(),
    selectedId: "home",
    select: vi.fn(),
    detail: command,
    detailLoading: false,
    detailError: null,
    refresh: vi.fn(),
  };
}

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage("en");
  });
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.mocked(robotLibraryComponents).mockResolvedValue({ data: { items: [component] } } as never);
});

describe("EngineerWorkbench", () => {
  it("adds a flow step from a published command and saves the current flow form", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<FlowDraftEditor draft={{ name: "Routine", steps: [] }} commands={[command]} onSave={onSave} />);

    await user.selectOptions(screen.getByLabelText("Available commands"), "home");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByText("1. Home")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "保存流程" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        steps: [expect.objectContaining({ action: "Home", func_id: 108, params: {} })],
      }),
    );
  });

  it("creates a command from the selected component and typed parameters", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <CommandDraftEditor
        draft={{ name: "Wait", aliases: [], description: "", component_id: "", parameters: {} }}
        components={[component]}
        onSave={onSave}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Command type"), "delay");
    await user.clear(screen.getByLabelText("delay_sec"));
    await user.type(screen.getByLabelText("delay_sec"), "2");
    await user.click(screen.getByRole("button", { name: "保存命令" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ component_id: "delay", parameters: { delay_sec: 2 } }),
    );
  });

  it("exposes the current authoring surface only to engineers", () => {
    vi.mocked(useRobotLibrary).mockReturnValue(commandLibrary() as never);

    const { rerender } = render(
      <EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />,
    );
    expect(screen.getByRole("button", { name: "新建命令" })).toBeVisible();
    expect(screen.getByRole("button", { name: "编辑" })).toBeVisible();
    expect(screen.getByRole("button", { name: "删除" })).toBeVisible();

    rerender(<EngineerWorkbench role="operator" gatewayToken="gateway" userToken="operator" />);
    expect(screen.queryByRole("button", { name: "新建命令" })).not.toBeInTheDocument();
  });

  it("creates a command through the current direct-save workflow", async () => {
    vi.mocked(useRobotLibrary).mockReturnValue(commandLibrary() as never);
    vi.mocked(engineerCreateCommand).mockResolvedValue({ ok: true, data: {} } as never);
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "新建命令" }));
    await user.type(screen.getByRole("textbox", { name: "Command name" }), "Wait");
    await user.selectOptions(screen.getByLabelText("Command type"), "delay");
    await user.click(screen.getByRole("button", { name: "保存命令" }));

    await waitFor(() =>
      expect(engineerCreateCommand).toHaveBeenCalledWith(
        "gateway",
        "engineer",
        expect.objectContaining({ name: "Wait", component_id: "delay" }),
      ),
    );
  });

  it("edits and deletes the selected command through the current direct workflow", async () => {
    const current = commandLibrary();
    vi.mocked(useRobotLibrary).mockReturnValue(current as never);
    vi.mocked(engineerUpdateCommand).mockResolvedValue({ ok: true, data: {} } as never);
    vi.mocked(engineerDeleteCommand).mockResolvedValue({ ok: true, data: {} } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<EngineerWorkbench role="engineer" gatewayToken="gateway" userToken="engineer" />);

    await user.click(screen.getByRole("button", { name: "编辑" }));
    await user.click(screen.getByRole("button", { name: "保存命令" }));
    await waitFor(() =>
      expect(engineerUpdateCommand).toHaveBeenCalledWith(
        "gateway",
        "engineer",
        "home",
        expect.objectContaining({ name: "Home" }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(engineerDeleteCommand).toHaveBeenCalledWith("gateway", "engineer", "home"));
    expect(current.refresh).toHaveBeenCalled();
  });
});
