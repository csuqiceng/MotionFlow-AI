import { fetchWithTimeout } from "./http";

export interface ProductToolProfile {
  tool_id: string;
  version: string;
  risk_level: "read" | "motion" | "system";
  required_capabilities: string[];
  enabled: boolean;
  eligible: boolean;
  reason: string | null;
}

export interface ProductProfile {
  protocol_version: number;
  backend_mode: string;
  available_backend_modes: string[];
  capabilities: Record<string, unknown>;
  tools: ProductToolProfile[];
}

async function request<T>(path: string, gatewayToken: string, engineerToken: string, init: RequestInit = {}) {
  const response = await fetchWithTimeout(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${gatewayToken}`,
      "X-Robot-User-Token": engineerToken,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!response.ok) throw new Error(`产品配置请求失败：${response.status}`);
  return (await response.json()) as { ok: boolean; data: T };
}

export function getProductProfile(gatewayToken: string, engineerToken: string) {
  return request<ProductProfile>("/api/management/product-profile", gatewayToken, engineerToken);
}

export function saveProductProfile(
  gatewayToken: string,
  engineerToken: string,
  body: Pick<ProductProfile, "backend_mode"> & { enabled_tools: string[] },
) {
  return request<ProductProfile>("/api/management/product-profile", gatewayToken, engineerToken, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
