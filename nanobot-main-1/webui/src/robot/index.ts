/** Public API of the robot feature; host shells must not import feature internals. */
export { RobotSidePanel } from "./components/RobotSidePanel";
export { CommandLibraryPage } from "./library/CommandLibraryPage";
export { RobotOperatorApp } from "./pages/RobotOperatorApp";
export {
  formatPoseValue,
  normalizeRobotState,
  normalizeRobotStatusResult,
  ROBOT_POSE_AXES,
} from "./status";
export type {
  RobotDisplaySnapshot,
  RobotExecutionMode,
} from "./types";
export {
  robotConfirm,
  robotExecute,
  robotFlowConfirm,
  robotFlowExecute,
  robotFlowPendingPlan,
  robotPendingPlan,
  robotStatus,
} from "../transport/robot";
export type { RobotResult, RobotStatusResult } from "../transport/robot";
