import { useEffect, useRef, useState } from "react";

import { robotStatus } from "@/lib/robot-api";
import { normalizeRobotStatusResult } from "@/robot/status";
import type { RobotDisplaySnapshot } from "@/robot/types";

export type RobotPollingState = "connecting" | "connected" | "error";

export interface UseRobotStatusOptions {
  /** Healthy poll interval (ms). Defaults to 3000. */
  intervalMs?: number;
  /** Backoff interval after an error or disconnected status. Defaults to 10000. */
  errorIntervalMs?: number;
  /** Skip polling entirely when false. Defaults to true. */
  enabled?: boolean;
}

export interface UseRobotStatusResult {
  snapshot: RobotDisplaySnapshot | null;
  polling: RobotPollingState;
  error: string | null;
}

/**
 * Polls ``/api/robot/status`` and exposes a normalized display snapshot.
 *
 * Polling runs on a ``setTimeout`` chain (rather than ``setInterval``) so the
 * next call can adapt its delay based on the latest result: 3s when healthy,
 * 10s on error or when the controller reports disconnected. The token is read
 * through a ref so token refreshes do not reset the polling cadence.
 */
export function useRobotStatus(
  token: string,
  options: UseRobotStatusOptions = {},
): UseRobotStatusResult {
  const intervalMs = options.intervalMs ?? 3000;
  const errorIntervalMs = options.errorIntervalMs ?? 10000;
  const enabled = options.enabled ?? true;
  const latestToken = useRef(token);
  const [snapshot, setSnapshot] = useState<RobotDisplaySnapshot | null>(null);
  const [polling, setPolling] = useState<RobotPollingState>("connecting");
  const [error, setError] = useState<string | null>(null);

  latestToken.current = token;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      let failed = false;
      try {
        const result = await robotStatus(latestToken.current);
        if (cancelled) return;
        const normalized = normalizeRobotStatusResult(result);
        setSnapshot(normalized);
        setError(null);
        // A successful API call still means the controller is offline when the
        // payload reports ``connected: false`` — surface that as the error
        // state so the operator sees "离线" rather than a healthy green.
        failed = !normalized.connection.connected;
        setPolling(normalized.connection.connected ? "connected" : "error");
      } catch (e) {
        failed = true;
        if (!cancelled) {
          setPolling("error");
          setError((e as Error).message);
        }
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, failed ? errorIntervalMs : intervalMs);
        }
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, errorIntervalMs, intervalMs]);

  return { snapshot, polling, error };
}
