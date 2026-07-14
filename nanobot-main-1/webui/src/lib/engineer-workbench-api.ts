import { fetchWithTimeout } from "./http";

const ENGINEER_WORKBENCH_TIMEOUT_MS = 15_000;

export interface EngineerApiResponse<T> {
  ok: boolean;
  data: T;
}

export interface EngineerApiErrorBody {
  error?: { code?: string; message?: string };
  data?: { current_revision?: number };
}

export class EngineerConflictError extends Error {
  readonly status = 409;
  readonly code?: string;
  readonly currentRevision?: number;

  constructor(message: string, body: EngineerApiErrorBody = {}) {
    super(message);
    this.name = "EngineerConflictError";
    this.code = body.error?.code;
    this.currentRevision = body.data?.current_revision;
  }
}

export interface EngineerCommandDraft {
  name: string;
  component_id: string;
  parameters: Record<string, unknown>;
  aliases?: string[];
  description?: string;
}

export interface EngineerCommandDraftUpdate extends EngineerCommandDraft {
  expected_revision: number;
}

export interface EngineerFlowStep {
  step_id: number;
  action: string;
  func_id: number;
  params: Record<string, unknown>;
  position_name?: string | null;
  spd_pct: number;
  description?: string;
}

export interface EngineerFlowDraft {
  name: string;
  steps: EngineerFlowStep[];
  description?: string;
  step_delay_ms?: number;
  rehearsal_spd?: number;
}

export interface EngineerFlowDraftUpdate extends EngineerFlowDraft {
  expected_revision: number;
}

export interface EngineerEntity {
  [key: string]: unknown;
}

export interface EngineerArchiveResult {
  archived: string;
}
export interface EngineerBulkArchiveResult { archived: string[]; failed: Array<{ id: string; code: string }>; }
export interface EngineerTransferReport { errors: string[]; commands: { imported: string[]; skipped: Array<{ id: string; code: string }> }; flows: { imported: string[]; skipped: Array<{ id: string; code: string }> }; }

export interface EngineerFlowValidation {
  errors: string[];
}

function parseErrorBody(text: string): EngineerApiErrorBody | undefined {
  try {
    return JSON.parse(text) as EngineerApiErrorBody;
  } catch {
    return undefined;
  }
}

async function engineerRequest<T>(
  path: string,
  gatewayToken: string,
  engineerToken: string,
  body: unknown = {},
  action?: string,
): Promise<EngineerApiResponse<T>> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${gatewayToken}`,
    "X-Nanobot-User-Token": engineerToken,
    // The gateway's GET-only transport carries JSON in a header. Percent-encode
    // it so command and flow names can safely contain Chinese and other Unicode.
    "X-Nanobot-Robot-Body": encodeURIComponent(JSON.stringify(body)),
  };
  if (action) headers["X-Nanobot-Engineer-Action"] = action;

  const response = await fetchWithTimeout(
    path,
    { method: "GET", headers, credentials: "same-origin" },
    ENGINEER_WORKBENCH_TIMEOUT_MS,
  );
  if (response.ok) return (await response.json()) as EngineerApiResponse<T>;

  let fallbackText = "";
  try {
    fallbackText = typeof response.text === "function" ? (await response.text()).trim() : "";
  } catch {
    // Preserve the response status even when an unusual Response implementation
    // refuses to expose its body.
  }
  const parsed = parseErrorBody(fallbackText);
  const message = parsed?.error?.message || fallbackText;
  if (response.status === 409) {
    throw new EngineerConflictError(message || "Engineer workbench request conflicted.", parsed);
  }
  throw new Error(`Engineer workbench API ${path} failed: ${response.status} ${message}`.trim());
}

export function engineerCreateCommand(
  gatewayToken: string,
  engineerToken: string,
  body: EngineerCommandDraft,
): Promise<EngineerApiResponse<EngineerEntity>> {
  return engineerRequest("/api/robot/engineer/commands", gatewayToken, engineerToken, body, "create");
}

export function engineerStartCommandDraft(gatewayToken: string, engineerToken: string, commandId: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/commands/${encodeURIComponent(commandId)}/draft`,
    gatewayToken, engineerToken, {}, "start-draft",
  );
}

export function engineerUpdateCommandDraft(
  gatewayToken: string, engineerToken: string, commandId: string, body: EngineerCommandDraftUpdate,
) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/commands/${encodeURIComponent(commandId)}/draft`,
    gatewayToken, engineerToken, body, "update-draft",
  );
}

export function engineerPublishCommand(gatewayToken: string, engineerToken: string, commandId: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/commands/${encodeURIComponent(commandId)}/publish`, gatewayToken, engineerToken,
  );
}

export function engineerArchiveCommand(gatewayToken: string, engineerToken: string, commandId: string) {
  return engineerRequest<EngineerArchiveResult>(
    `/api/robot/engineer/commands/${encodeURIComponent(commandId)}/archive`, gatewayToken, engineerToken,
  );
}
export function engineerBulkArchiveCommands(gatewayToken: string, engineerToken: string, ids: string[]) {
  return engineerRequest<EngineerBulkArchiveResult>("/api/robot/engineer/commands", gatewayToken, engineerToken, { ids }, "batch-archive");
}

export function engineerDuplicateCommand(gatewayToken: string, engineerToken: string, commandId: string, name: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/commands/${encodeURIComponent(commandId)}/duplicate`, gatewayToken, engineerToken, { name }, "duplicate",
  );
}

export function engineerCreateFlow(gatewayToken: string, engineerToken: string, body: EngineerFlowDraft) {
  return engineerRequest<EngineerEntity>("/api/robot/engineer/flows", gatewayToken, engineerToken, body, "create");
}

export function engineerStartFlowDraft(gatewayToken: string, engineerToken: string, flowId: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/draft`,
    gatewayToken, engineerToken, {}, "start-draft",
  );
}

export function engineerUpdateFlowDraft(
  gatewayToken: string, engineerToken: string, flowId: string, body: EngineerFlowDraftUpdate,
) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/draft`,
    gatewayToken, engineerToken, body, "update-draft",
  );
}

export function engineerValidateFlowDraft(gatewayToken: string, engineerToken: string, flowId: string) {
  return engineerRequest<EngineerFlowValidation>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/validate`,
    gatewayToken, engineerToken, {}, "validate",
  );
}

export function engineerPublishFlow(gatewayToken: string, engineerToken: string, flowId: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/publish`, gatewayToken, engineerToken, {}, "publish",
  );
}

export function engineerArchiveFlow(gatewayToken: string, engineerToken: string, flowId: string) {
  return engineerRequest<EngineerArchiveResult>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/archive`, gatewayToken, engineerToken, {}, "archive",
  );
}
export function engineerBulkArchiveFlows(gatewayToken: string, engineerToken: string, ids: string[]) {
  return engineerRequest<EngineerBulkArchiveResult>("/api/robot/engineer/flows", gatewayToken, engineerToken, { ids }, "batch-archive");
}
export function engineerExportLibrary(gatewayToken: string, engineerToken: string) {
  return engineerRequest<Record<string, unknown>>("/api/robot/engineer/library/export", gatewayToken, engineerToken);
}
export function engineerImportLibrary(gatewayToken: string, engineerToken: string, payload: Record<string, unknown>, strategy: "skip" | "rename" | "overwrite-draft-only") {
  return engineerRequest<EngineerTransferReport>("/api/robot/engineer/library/import", gatewayToken, engineerToken, { payload, strategy }, "import");
}
export interface EngineerDiagnostics { connection: { mode: string; real_device: boolean }; execution_mode?: string; position: Record<string, unknown>; io: Record<string, unknown>; alarms: string[]; task: unknown; command_echo: unknown; }
export function engineerDiagnostics(gatewayToken: string, engineerToken: string) {
  return engineerRequest<EngineerDiagnostics>("/api/robot/engineer/diagnostics", gatewayToken, engineerToken);
}
export interface EngineerAuditEvent { audit_id?: string; timestamp?: string; action?: string; [key: string]: unknown; }
export interface EngineerAuditPage { items: EngineerAuditEvent[]; next_cursor: string | null; }
export function engineerAudit(gatewayToken: string, engineerToken: string) {
  return engineerRequest<EngineerAuditPage>("/api/robot/engineer/audit", gatewayToken, engineerToken);
}

export function engineerDuplicateFlow(gatewayToken: string, engineerToken: string, flowId: string, name: string) {
  return engineerRequest<EngineerEntity>(
    `/api/robot/engineer/flows/${encodeURIComponent(flowId)}/duplicate`, gatewayToken, engineerToken, { name }, "duplicate",
  );
}
