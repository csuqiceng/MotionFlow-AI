import { ROBOT_POSE_AXES, formatPoseValue } from "@/robot/status";
import type { RobotDisplaySnapshot } from "@/robot/types";

/**
 * Left status column: connection card, safety grid (急停/暂停/报警/取消锁存),
 * and pose grid (X/Y/Z/RX/RY/RZ in monospace). Missing values render as "-".
 */
export function RobotLeftStatusPanel({
  snapshot,
}: {
  snapshot: RobotDisplaySnapshot | null;
}) {
  return (
    <aside className="flex min-h-0 w-72 shrink-0 flex-col gap-3 overflow-y-auto border-r border-border/70 bg-muted/20 p-4">
      <h2 className="text-sm font-semibold">实时状态</h2>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">连接</p>
        <p className="mt-1 text-sm font-medium">{snapshot?.connection.label ?? "连接中"}</p>
      </section>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">安全</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          <SafetyItem label="急停" value={snapshot?.safety.estop ?? "unknown"} />
          <SafetyItem label="暂停" value={snapshot?.safety.pause ?? "unknown"} />
          <SafetyItem label="报警" value={snapshot?.safety.alarm ?? "unknown"} />
          <SafetyItem
            label="取消锁存"
            value={snapshot?.safety.cancelLatch ? "active" : "ok"}
          />
        </dl>
      </section>

      <section className="rounded-md border border-border/70 bg-background p-3">
        <p className="text-xs text-muted-foreground">位姿</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs">
          {ROBOT_POSE_AXES.map((axis) => (
            <div key={axis} className="flex items-baseline justify-between gap-2">
              <dt className="uppercase text-muted-foreground">{axis}</dt>
              <dd>{formatPoseValue(snapshot?.pose[axis] ?? null)}</dd>
            </div>
          ))}
        </dl>
      </section>
    </aside>
  );
}

function SafetyItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
