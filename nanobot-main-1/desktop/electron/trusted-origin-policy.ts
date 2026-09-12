const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);
const EXTERNAL_PROTOCOLS = new Set(["http:", "https:"]);

export function trustedLoopbackOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" || !LOOPBACK_HOSTS.has(url.hostname)) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

export function hasExactOrigin(value: string, trustedOrigin: string | null): boolean {
  if (trustedOrigin === null) return false;
  try {
    return new URL(value).origin === trustedOrigin;
  } catch {
    return false;
  }
}

export function mayOpenInSystemBrowser(value: string): boolean {
  try {
    return EXTERNAL_PROTOCOLS.has(new URL(value).protocol);
  } catch {
    return false;
  }
}
