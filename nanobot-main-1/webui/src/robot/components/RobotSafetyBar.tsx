import { Loader2, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { robotEmergencyStop } from "@/lib/robot-api";
import { useRobotStatus } from "@/robot/hooks/useRobotStatus";

export function RobotSafetyBar({ token, userToken }: { token: string; userToken: string }) {
  const { snapshot, polling, refresh } = useRobotStatus(token);
  const [stopping, setStopping] = useState(false);

  const connected = snapshot?.connection.connected === true;
  const estopActive = snapshot?.safety.estop === "active";
  const alarmActive = snapshot?.safety.alarm === "active";
  const pauseActive = snapshot?.safety.pause === "paused";

  const controllerLabel = connected ? "控制器在线" : "控制器离线";
  const controllerTone = connected ? "bg-emerald-500" : "bg-slate-400";
  const safetyLabel = estopActive ? "急停已触发" : "急停正常";
  const safetyTone = estopActive || alarmActive ? "text-red-700" : "text-slate-700";
  const activityLabel = alarmActive ? "报警中" : pauseActive ? "已暂停" : "待命";

  const handleEmergencyStop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await robotEmergencyStop(token, userToken);
    } finally {
      await refresh();
      setStopping(false);
    }
  };

  return (
    <section
      aria-label="机器人安全状态"
      className="robot-safety-bar flex min-h-12 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-2 text-xs shadow-sm backdrop-blur lg:px-5"
    >
      <div className="flex min-w-0 items-center gap-2 font-medium text-slate-800">
        <ShieldAlert className="h-4 w-4 shrink-0 text-cyan-600" aria-hidden="true" />
        <span className="hidden sm:inline">运行安全</span>
      </div>
      <div className="hidden h-4 w-px bg-slate-200 sm:block" />
      <div className="flex min-w-0 items-center gap-1.5 text-slate-600">
        <span className={`h-2 w-2 shrink-0 rounded-full ${controllerTone}`} />
        <span>{controllerLabel}</span>
        {polling === "connecting" ? <span className="text-slate-400">同步中</span> : null}
      </div>
      <div className="hidden items-center gap-1.5 sm:flex">
        <span className="text-slate-400">·</span>
        <span className={safetyTone}>{safetyLabel}</span>
      </div>
      <div className="hidden items-center gap-1.5 md:flex">
        <span className="text-slate-400">·</span>
        <span className={alarmActive ? "text-red-700" : "text-slate-600"}>{activityLabel}</span>
      </div>
      <button
        type="button"
        aria-label="急停"
        disabled={stopping}
        onClick={() => void handleEmergencyStop()}
        className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-md bg-red-600 px-3 font-semibold text-white shadow-sm transition-colors hover:bg-red-700 disabled:cursor-wait disabled:opacity-70"
      >
        {stopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
        急停
      </button>
    </section>
  );
}
