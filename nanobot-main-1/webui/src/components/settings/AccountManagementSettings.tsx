import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createUser, listUsers, resetUserPassword, updateUser,
  type ManagedUser, type ManagedUserRole,
} from "@/lib/users-api";

export function AccountManagementSettings({ gatewayToken, userToken }: { gatewayToken: string; userToken: string }) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<ManagedUserRole>("operator");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const refresh = async () => {
    const result = await listUsers(gatewayToken, userToken);
    setUsers(result.data.users);
  };
  useEffect(() => { void refresh().catch((e) => setMessage((e as Error).message)); }, [gatewayToken, userToken]);
  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setMessage("");
    try { await action(); await refresh(); setMessage(success); } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="space-y-6" data-testid="account-management-settings">
    <div><h2 className="text-xl font-semibold">账户管理</h2><p className="text-sm text-muted-foreground">管理操作员和工程师账户。</p></div>
    <form className="grid gap-3 rounded-lg border p-4 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (username && password) void run(async () => { await createUser(gatewayToken, userToken, { username, password, role }); setUsername(""); setPassword(""); }, "账户已创建"); }}>
      <Input aria-label="新账户用户名" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名" />
      <Input aria-label="新账户密码" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="初始密码" />
      <select aria-label="新账户角色" value={role} onChange={(e) => setRole(e.target.value as ManagedUserRole)} className="rounded-lg border bg-background px-3"><option value="operator">操作员</option><option value="engineer">工程师</option></select>
      <Button type="submit" disabled={busy || !username || !password}>新增账户</Button>
    </form>
    {message ? <p role="status" className="text-sm text-muted-foreground">{message}</p> : null}
    <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm"><thead className="bg-muted/50 text-left"><tr><th className="p-3">用户名</th><th className="p-3">角色</th><th className="p-3">状态</th><th className="p-3">操作</th></tr></thead><tbody>{users.map((user) => <tr key={user.user_id} className="border-t"><td className="p-3">{user.username}</td><td className="p-3">{user.role === "engineer" ? "工程师" : "操作员"}</td><td className="p-3">{user.enabled ? "已启用" : "已停用"}</td><td className="flex flex-wrap gap-2 p-3"><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => updateUser(gatewayToken, userToken, user.user_id, { enabled: !user.enabled }), user.enabled ? "账户已停用" : "账户已启用")}>{user.enabled ? "停用" : "启用"}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => updateUser(gatewayToken, userToken, user.user_id, { role: user.role === "engineer" ? "operator" : "engineer" }), "角色已更新")}>设为{user.role === "engineer" ? "操作员" : "工程师"}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => { const next = window.prompt(`为 ${user.username} 设置新密码`); if (next) void run(() => resetUserPassword(gatewayToken, userToken, user.user_id, next), "密码已重置"); }}>重置密码</Button></td></tr>)}</tbody></table></div>
  </section>;
}
