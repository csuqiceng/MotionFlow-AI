import { fetchWithTimeout } from "./http";

const LIBRARY_TIMEOUT_MS = 15_000;

export interface LibraryCommand {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  component_id: string;
  parameters: Record<string, unknown>;
  risk_level: string;
  status: string;
  version: number;
  source: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  published_at: string;
}

export interface LibraryParameterField {
  name: string;
  type: "int" | "float" | "str" | "bool";
  unit?: string;
  minimum?: number | null;
  maximum?: number | null;
  default?: unknown;
  required?: boolean;
  description?: string;
}

export interface LibraryComponent {
  id: string;
  func_num: number;
  name: string;
  description?: string;
  parameters: LibraryParameterField[];
}

export interface LibraryFlowStep {
  step_id: number;
  action: string;
  func_id: number;
  params: Record<string, unknown>;
  position_name: string | null;
  spd_pct: number;
  description: string;
}

export interface LibraryFlow {
  flow_id: string;
  name: string;
  description: string;
  steps: LibraryFlowStep[];
  step_delay_ms: number;
  rehearsal_spd: number;
  confirmed: boolean;
  version: number;
  state: string;
  current_step: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface LibraryListResponse<T> {
  ok: boolean;
  data: { items: T[]; total: number };
}

export interface LibraryDetailResponse<T> {
  ok: boolean;
  data: T;
}

export interface LibraryCommandFilters {
  component_id?: string;
  risk_level?: string;
  status?: string;
  q?: string;
}

async function libraryGet<T>(url: string, token: string): Promise<T> {
  const res = await fetchWithTimeout(
    url,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      credentials: "same-origin",
    },
    LIBRARY_TIMEOUT_MS,
  );
  if (!res.ok) {
    const text = typeof res.text === "function" ? (await res.text()).trim() : "";
    throw new Error(`Library API ${url} failed: ${res.status} ${text}`);
  }
  return (await res.json()) as T;
}

function buildQuery(filters: LibraryCommandFilters): string {
  const entries = Object.entries(filters).filter(
    ([, v]) => typeof v === "string" && v.trim() !== "",
  );
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&");
}

export function robotLibraryCommands(
  token: string,
  filters: LibraryCommandFilters = {},
): Promise<LibraryListResponse<LibraryCommand>> {
  const query = buildQuery(filters);
  return libraryGet<LibraryListResponse<LibraryCommand>>(
    `/api/robot/library/commands${query}`,
    token,
  );
}

export function robotLibraryCommand(
  token: string,
  id: string,
): Promise<LibraryDetailResponse<LibraryCommand>> {
  return libraryGet<LibraryDetailResponse<LibraryCommand>>(
    `/api/robot/library/commands/${encodeURIComponent(id)}`,
    token,
  );
}

export function robotLibraryFlows(
  token: string,
): Promise<LibraryListResponse<LibraryFlow>> {
  return libraryGet<LibraryListResponse<LibraryFlow>>("/api/robot/library/flows", token);
}

async function libraryRun<T>(url: string, token: string, userToken: string): Promise<T> {
  const res = await fetchWithTimeout(url, { method: "GET", headers: { Authorization: `Bearer ${token}`, "X-Nanobot-User-Token": userToken }, credentials: "same-origin" }, LIBRARY_TIMEOUT_MS);
  if (!res.ok) throw new Error(`Library run ${url} failed: ${res.status} ${(await res.text()).trim()}`);
  return (await res.json()) as T;
}

export interface LibraryExecutionStep {
  step_index: number;
  state: "queued" | "running" | "succeeded" | "failed" | "skipped";
  result?: Record<string, unknown>;
}

export interface LibraryExecution {
  execution_id: string;
  state: "queued" | "running" | "completed" | "failed";
  message: string;
  steps: LibraryExecutionStep[];
}

export function robotLibraryComponents(token: string): Promise<LibraryListResponse<LibraryComponent>> {
  return libraryGet<LibraryListResponse<LibraryComponent>>("/api/robot/library/components", token);
}

export function robotLibraryFlow(
  token: string,
  name: string,
): Promise<LibraryDetailResponse<LibraryFlow>> {
  return libraryGet<LibraryDetailResponse<LibraryFlow>>(
    `/api/robot/library/flows/${encodeURIComponent(name)}`,
    token,
  );
}

export function runLibraryCommand(token: string, userToken: string, id: string) { return libraryRun<{ ok: true; data: Pick<LibraryExecution, "execution_id" | "state"> }>(`/api/robot/library/commands/${encodeURIComponent(id)}/run`, token, userToken); }
export function runLibraryFlow(token: string, userToken: string, name: string) { return libraryRun<{ ok: true; data: Pick<LibraryExecution, "execution_id" | "state"> }>(`/api/robot/library/flows/${encodeURIComponent(name)}/run`, token, userToken); }
export function libraryExecution(token: string, userToken: string, executionId: string) { return libraryRun<{ ok: true; data: LibraryExecution }>(`/api/robot/library/executions/${encodeURIComponent(executionId)}`, token, userToken); }
