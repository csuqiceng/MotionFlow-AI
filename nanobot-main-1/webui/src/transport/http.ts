export const DEFAULT_HTTP_TIMEOUT_MS = 20_000;

export type FetchImplementation = typeof fetch;

function defaultFetch(): FetchImplementation {
  if (typeof globalThis.fetch !== "function") {
    throw new Error("Fetch is not available in this runtime.");
  }
  return globalThis.fetch.bind(globalThis);
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_HTTP_TIMEOUT_MS,
  fetchImpl: FetchImplementation = defaultFetch(),
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return fetchImpl(input, init);
  }

  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const request = fetchImpl(input, { ...init, signal: controller?.signal ?? init.signal });
  const timeout = new Promise<Response>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(`Request timed out after ${timeoutMs}ms`));
      controller?.abort();
    }, timeoutMs);
  });

  try {
    return await Promise.race([request, timeout]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

export function resolveHttpUrl(input: RequestInfo | URL, baseUrl: string): RequestInfo | URL {
  if (!baseUrl || typeof input !== "string" || !input.startsWith("/")) return input;
  return `${baseUrl.replace(/\/+$/, "")}${input}`;
}
