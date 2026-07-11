import type { RobotDisplaySnapshot, RobotExecutionMode } from "@/robot/types";

export interface RobotExecutionModeView {
  mode: RobotExecutionMode;
  label: "自动执行" | "人工确认" | "只预演" | "未知模式";
  /** True when the operator must confirm a pending plan before execution. */
  requiresManualConfirm: boolean;
  /** True when the backend auto-executes after the safety check passes. */
  autoExecutesAfterSafetyCheck: boolean;
  /** True when only a dry-run is permitted (no real motion). */
  dryRunOnly: boolean;
}

/**
 * Pure hook-shaped helper that reads the execution mode from a normalized
 * snapshot and projects it into a labeled view with behavior flags.
 *
 * Implemented as a hook (rather than a plain function) so panels can later add
 * memoization or derived state without changing call sites. It must remain
 * side-effect free.
 */
export function useRobotExecutionMode(snapshot: RobotDisplaySnapshot | null): RobotExecutionModeView {
  const mode = snapshot?.task.executionMode ?? "unknown";
  return {
    mode,
    label: labelForExecutionMode(mode),
    requiresManualConfirm: mode === "manual_confirm",
    autoExecutesAfterSafetyCheck: mode === "auto_after_safety_check",
    dryRunOnly: mode === "dry_run_only",
  };
}

function labelForExecutionMode(mode: RobotExecutionMode): RobotExecutionModeView["label"] {
  if (mode === "dry_run_only") return "只预演";
  if (mode === "auto_after_safety_check") return "自动执行";
  if (mode === "manual_confirm") return "人工确认";
  return "未知模式";
}
