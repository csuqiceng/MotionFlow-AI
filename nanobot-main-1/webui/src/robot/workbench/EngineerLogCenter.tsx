import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { engineerAudit, type EngineerAuditEvent } from "@/lib/engineer-workbench-api";

export function EngineerLogCenter({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [items, setItems] = useState<EngineerAuditEvent[]>([]);
  const [error, setError] = useState("");
  const refresh = async () => {
    try {
      setItems((await engineerAudit(gatewayToken, userToken)).data.items);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };
  useEffect(() => { void refresh(); }, [gatewayToken, userToken]);

  return <section aria-label="工程师操作日志" className="space-y-2 border-b p-3">
    <div className="flex items-center justify-between"><h3 className="font-semibold">工程师操作日志</h3><Button size="sm" variant="outline" onClick={() => void refresh()}>刷新日志</Button></div>
    {error ? <p role="alert">{error}</p> : null}
    {!error && items.length === 0 ? <p className="text-xs text-muted-foreground">暂无操作记录</p> : null}
    <ol className="space-y-1 text-xs">{items.slice(0, 10).map((item, index) => <li key={String(item.audit_id ?? item.timestamp ?? index)} className="rounded border p-2">{String(item.timestamp ?? "")} · {String(item.action ?? "未命名操作")}</li>)}</ol>
  </section>;
}
