import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { getProductProfile, saveProductProfile, type ProductProfile } from "@/transport/product-profile";

export function ProductProfileSettings({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [profile, setProfile] = useState<ProductProfile | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getProductProfile(gatewayToken, userToken)
      .then((result) => setProfile(result.data))
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法读取机器人配置"));
  }, [gatewayToken, userToken]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!profile) return <p className="text-sm text-muted-foreground">正在读取机器人配置…</p>;
  const enabled = new Set(profile.tools.filter((tool) => tool.enabled).map((tool) => tool.tool_id));

  const save = async () => {
    setSaving(true);
    try {
      const result = await saveProductProfile(gatewayToken, userToken, {
        backend_mode: profile.backend_mode,
        enabled_tools: [...enabled],
      });
      setProfile(result.data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存机器人配置失败");
    } finally {
      setSaving(false);
    }
  };

  return <section className="space-y-4 rounded-xl border p-4" aria-label="机器人与 Tool 配置">
    <div><h3 className="font-medium">机器人与 Tool 配置</h3><p className="text-sm text-muted-foreground">仅工程师可修改。AI 配置不在此页面显示。</p></div>
    <label className="block text-sm">机械手后端
      <select className="mt-1 w-full rounded-md border bg-background p-2" value={profile.backend_mode} onChange={(event) => setProfile({ ...profile, backend_mode: event.target.value })}>
        {profile.available_backend_modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
      </select>
    </label>
    <div className="space-y-2">{profile.tools.map((tool) => <label key={tool.tool_id} className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={enabled.has(tool.tool_id)} disabled={!tool.eligible && !tool.enabled} onChange={(event) => {
        setProfile({ ...profile, tools: profile.tools.map((item) => item.tool_id === tool.tool_id ? { ...item, enabled: event.target.checked } : item) });
      }} />
      <span>{tool.tool_id} <span className="text-muted-foreground">({tool.risk_level})</span>{tool.reason ? `：${tool.reason}` : ""}</span>
    </label>)}</div>
    <div className="space-y-2"><Button type="button" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存机器人与 Tool 配置"}</Button><p className="text-xs text-muted-foreground">保存后重启服务，新的 Tool 启用状态才会用于新的 AI 运行时。</p></div>
  </section>;
}
