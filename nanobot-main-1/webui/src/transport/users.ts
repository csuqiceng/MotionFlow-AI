import { fetchWithTimeout } from "./http";

const USERS_API_TIMEOUT_MS = 15_000;

export type ManagedUserRole = "operator" | "engineer";

export interface ManagedUser {
  user_id: string;
  username: string;
  role: ManagedUserRole;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface UsersApiResponse<T> {
  ok: boolean;
  data: T;
}

export interface CreateUserInput {
  username: string;
  role: ManagedUserRole;
  password: string;
}

export interface UpdateUserInput {
  enabled?: boolean;
  role?: ManagedUserRole;
}

function userHeaders(gatewayToken: string, userToken: string, body?: unknown): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${gatewayToken}`,
    "X-Robot-User-Token": userToken,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return headers;
}

async function request<T>(
  path: string,
  gatewayToken: string,
  userToken: string,
  options: { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown } = {},
): Promise<UsersApiResponse<T>> {
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  const response = await fetchWithTimeout(
    path,
    {
      method: options.method ?? "GET",
      credentials: "same-origin",
      headers: userHeaders(gatewayToken, userToken, options.body),
      body,
    },
    USERS_API_TIMEOUT_MS,
  );
  if (response.ok) return (await response.json()) as UsersApiResponse<T>;
  const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
  throw new Error(payload?.error?.message || `账户管理请求失败（HTTP ${response.status}）`);
}

export function listUsers(gatewayToken: string, userToken: string) {
  return request<{ users: ManagedUser[] }>("/api/identity/users", gatewayToken, userToken);
}

export function createUser(gatewayToken: string, userToken: string, input: CreateUserInput) {
  return request<ManagedUser>("/api/identity/users", gatewayToken, userToken, { method: "POST", body: input });
}

export function updateUser(gatewayToken: string, userToken: string, userId: string, input: UpdateUserInput) {
  return request<ManagedUser>(
    `/api/identity/users/${encodeURIComponent(userId)}`, gatewayToken, userToken, { method: "PATCH", body: input },
  );
}

export function resetUserPassword(gatewayToken: string, userToken: string, userId: string, password: string) {
  return request<ManagedUser>(
    `/api/identity/users/${encodeURIComponent(userId)}/password`, gatewayToken, userToken,
    { method: "POST", body: { new_password: password } },
  );
}

export function deleteUser(gatewayToken: string, userToken: string, userId: string) {
  return request<{ deleted: string }>(
    `/api/identity/users/${encodeURIComponent(userId)}`, gatewayToken, userToken,
    { method: "DELETE" },
  );
}
