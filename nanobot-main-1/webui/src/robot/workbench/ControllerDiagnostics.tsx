import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { engineerDiagnostics, type EngineerDiagnostics } from "@/lib/engineer-workbench-api";

function values(value: unknown): Array<[string, string]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [["状态", String(value ?? "无")]];
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, typeof item === "object" ? JSON.stringify(item) : String(item)]);
}

function DiagnosticValues({ title, value }: { title: string; value: unknown }) {
  return <div><dt>{title}</dt><dd className="mt-1 rounded border bg-muted/30 p-2"><dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">{values(value).map(([key, item]) => <div key={key}><dt className="text-muted-foreground">{key}</dt><dd>{item}</dd></div>)}</dl></dd></div>;
}

export function ControllerDiagnostics({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [snapshot, setSnapshot] = useState<EngineerDiagnostics | null>(null);
  const [error, setError] = useState("");
  const refresh = async () => {
    try {
      setSnapshot((await engineerDiagnostics(gatewayToken, userToken)).data);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };
  useEffect(() => { void refresh(); }, [gatewayToken, userToken]);

  return <section aria-label="控制器诊断" className="space-y-2 border-b p-3">
    <div className="flex items-center justify-between"><h3 className="font-semibold">控制器诊断</h3><Button size="sm" variant="outline" onClick={() => void refresh()}>刷新诊断</Button></div>
    {error ? <p role="alert">{error}</p> : null}
    {snapshot ? <dl className="grid gap-3 text-sm md:grid-cols-2">
      <div><dt>连接模式</dt><dd>{snapshot.connection.mode}</dd></div>
      <div><dt>真实设备</dt><dd>{snapshot.connection.real_device ? "是" : "否"}</dd></div>
      <div><dt>执行模式</dt><dd>{snapshot.execution_mode ?? "未知"}</dd></div>
      <div><dt>当前任务</dt><dd>{String(snapshot.task ?? "无")}</dd></div>
      <div><dt>报警</dt><dd>{snapshot.alarms.join("，") || "无"}</dd></div>
      <DiagnosticValues title="位置" value={snapshot.position} />
      <DiagnosticValues title="IO 状态" value={snapshot.io} />
      <DiagnosticValues title="命令回显" value={snapshot.command_echo} />
    </dl> : <p>正在读取控制器诊断…</p>}
  </section>;
}
