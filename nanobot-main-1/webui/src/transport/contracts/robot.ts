/** Versioned wire shapes owned by the robot transport boundary. */
export interface RobotStatusResult {
  ok: boolean;
  state?: string;
  message?: string;
  data?: Record<string, unknown>;
  errors?: unknown[];
}
