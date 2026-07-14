import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { engineerDiagnostics, type EngineerDiagnostics } from "@/lib/engineer-workbench-api";

export function ControllerDiagnostics({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [snapshot, setSnapshot] = useState<EngineerDiagnostics | null>(null);
  const [error, setError] = useState("");
  const refresh = async () => { try { setSnapshot((await engineerDiagnostics(gatewayToken, userToken)).data); setError(""); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } };
  useEffect(() => { void refresh(); }, [gatewayToken, userToken]);
  return <section aria-label="Controller diagnostics" className="space-y-2 border-b p-3"><div className="flex items-center justify-between"><h3 className="font-semibold">Controller diagnostics</h3><Button size="sm" variant="outline" onClick={() => void refresh()}>Refresh diagnostics</Button></div>{error ? <p role="alert">{error}</p> : null}{snapshot ? <dl className="grid grid-cols-2 gap-2 text-sm"><div><dt>Connection</dt><dd>{snapshot.connection.mode}</dd></div><div><dt>Real device</dt><dd>{String(snapshot.connection.real_device)}</dd></div><div><dt>Task</dt><dd>{String(snapshot.task ?? "unavailable")}</dd></div><div><dt>Alarms</dt><dd>{snapshot.alarms.join(", ") || "none"}</dd></div></dl> : <p>Loading diagnostics…</p>}</section>;
}
