import { useReducer } from "react";

import type { RuntimeSurface } from "@/lib/types";
import { RobotDialoguePanel } from "@/robot/components/RobotDialoguePanel";
import { RobotLeftStatusPanel } from "@/robot/components/RobotLeftStatusPanel";
import { RobotRunPanel } from "@/robot/components/RobotRunPanel";
import { RobotTopStatusBar } from "@/robot/components/RobotTopStatusBar";
import { useRobotExecutionMode } from "@/robot/hooks/useRobotExecutionMode";
import { useRobotStatus, type UseRobotStatusResult } from "@/robot/hooks/useRobotStatus";
import {
  initialRobotDisplayState,
  robotDisplayReducer,
} from "@/robot/state/robotDisplayState";

/**
 * Robot operator console shell.
 *
 * Composes the status hook + execution-mode view + display-state reducer and
 * lays out the three operator columns (left status | center dialogue | right
 * run). The optional ``status`` prop lets tests inject a frozen snapshot
 * instead of polling the backend.
 */
export function RobotOperatorApp({
  token,
  runtimeSurface,
  status,
  onLogout,
  onNativeEngineRestart,
}: {
  token: string;
  runtimeSurface: RuntimeSurface;
  status?: UseRobotStatusResult;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const liveStatus = useRobotStatus(token, { enabled: status == null });
  const effectiveStatus = status ?? liveStatus;
  const executionMode = useRobotExecutionMode(effectiveStatus.snapshot);
  const [displayState, dispatch] = useReducer(robotDisplayReducer, initialRobotDisplayState);

  return (
    <div
      data-runtime-surface={runtimeSurface}
      className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground"
    >
      <RobotTopStatusBar
        snapshot={effectiveStatus.snapshot}
        executionMode={executionMode}
        onLogout={onLogout}
        onNativeEngineRestart={onNativeEngineRestart}
      />
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <RobotLeftStatusPanel snapshot={effectiveStatus.snapshot} />
        <RobotDialoguePanel displayState={displayState} dispatch={dispatch} />
        <RobotRunPanel displayState={displayState} executionMode={executionMode} />
      </main>
    </div>
  );
}
