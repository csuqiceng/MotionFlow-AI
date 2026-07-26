import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Check,
  KeyRound,
  Loader2,
  Lock,
  Plus,
  ShieldCheck,
  Trash2,
  UserCog,
  UserX,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type ManagedUser,
  type ManagedUserRole,
} from "@/lib/users-api";

type StatusPill = "active" | "disabled";

function roleLabel(role: ManagedUserRole): string {
  return role === "engineer" ? "工程师" : "操作员";
}

function statusPill(user: ManagedUser): StatusPill {
  return user.enabled ? "active" : "disabled";
}

function statusLabel(user: ManagedUser): string {
  return user.enabled ? "已启用" : "已停用";
}

export function AccountManagementSettings({
  gatewayToken,
  userToken,
  currentUser,
}: {
  gatewayToken: string;
  userToken: string;
  currentUser?: { user_id?: string; username?: string; role?: string } | null;
}) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 新增账户表单
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<ManagedUserRole>("operator");

  // 重置密码对话框
  const [passwordTarget, setPasswordTarget] = useState<ManagedUser | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // 删除账户对话框
  const [deleteTarget, setDeleteTarget] = useState<ManagedUser | null>(null);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");

  const currentUserId = currentUser?.user_id;

  const refresh = async () => {
    try {
      const result = await listUsers(gatewayToken, userToken);
      setUsers(result.data.users);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gatewayToken, userToken]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await action();
      await refresh();
      setNotice(success);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    if (!username || !password) return;
    void run(async () => {
      await createUser(gatewayToken, userToken, { username, password, role });
      setUsername("");
      setPassword("");
      setRole("operator");
    }, "账户已创建");
  };

  const openResetPassword = (user: ManagedUser) => {
    setPasswordTarget(user);
    setNewPassword("");
    setConfirmPassword("");
  };

  const submitResetPassword = (event: FormEvent) => {
    event.preventDefault();
    if (!passwordTarget) return;
    if (newPassword.length < 4) return;
    if (newPassword !== confirmPassword) return;
    const target = passwordTarget;
    void run(async () => {
      await resetUserPassword(gatewayToken, userToken, target.user_id, newPassword);
      setPasswordTarget(null);
      setNewPassword("");
      setConfirmPassword("");
    }, `已重置 ${target.username} 的密码`);
  };

  const openDelete = (user: ManagedUser) => {
    setDeleteTarget(user);
    setDeleteConfirmName("");
  };

  const submitDelete = (event: FormEvent) => {
    event.preventDefault();
    if (!deleteTarget) return;
    if (deleteConfirmName.trim() !== deleteTarget.username) return;
    const target = deleteTarget;
    void run(async () => {
      await deleteUser(gatewayToken, userToken, target.user_id);
      setDeleteTarget(null);
      setDeleteConfirmName("");
    }, `已删除账户 ${target.username}`);
  };

  const passwordMismatch = newPassword !== confirmPassword;
  const passwordTooShort = newPassword.length > 0 && newPassword.length < 4;
  const passwordFormInvalid =
    passwordTooShort || passwordMismatch || newPassword.length === 0;
  const deleteConfirmMismatch =
    deleteConfirmName.trim().length > 0 && deleteConfirmName.trim() !== deleteTarget?.username;

  const sortedUsers = useMemo(() => {
    return [...users].sort((a, b) => {
      if (a.role === "engineer" && b.role !== "engineer") return -1;
      if (a.role !== "engineer" && b.role === "engineer") return 1;
      return a.username.localeCompare(b.username, "zh-Hans");
    });
  }, [users]);

  return (
    <section className="space-y-7" data-testid="account-management-settings">
      <header className="space-y-1.5 px-1">
        <h2 className="flex items-center gap-2 text-[20px] font-medium tracking-[-0.01em] text-foreground">
          <ShieldCheck className="h-5 w-5 text-[hsl(var(--accent-primary))]" strokeWidth={2} aria-hidden />
          安全
        </h2>
        <p className="text-[13px] leading-5 text-muted-foreground">
          管理操作员与工程师账户、密码及启用状态。仅工程师可见。
        </p>
      </header>

      {notice ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-2.5 text-[13px] text-emerald-700 dark:text-emerald-300"
        >
          <Check className="h-4 w-4 shrink-0" aria-hidden />
          <span>{notice}</span>
        </div>
      ) : null}
      {error ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/8 px-4 py-2.5 text-[13px] text-destructive"
        >
          <span className="flex-1 break-words">{error}</span>
        </div>
      ) : null}

      {/* 新增账户 */}
      <section>
        <h3 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
          新增账户
        </h3>
        <form
          onSubmit={handleCreate}
          className="soft-card space-y-3 rounded-xl p-4 sm:space-y-0 sm:p-5"
        >
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end sm:gap-3">
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">用户名</span>
              <Input
                aria-label="新账户用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="例如 zhang_san"
                autoComplete="off"
                disabled={busy}
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">初始密码</span>
              <Input
                aria-label="新账户密码"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="至少 4 个字符"
                autoComplete="new-password"
                disabled={busy}
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">角色</span>
              <select
                aria-label="新账户角色"
                value={role}
                onChange={(e) => setRole(e.target.value as ManagedUserRole)}
                disabled={busy}
                className="h-9 w-full rounded-lg border border-border/70 bg-background px-3 text-[13px] text-foreground shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:w-[120px]"
              >
                <option value="operator">操作员</option>
                <option value="engineer">工程师</option>
              </select>
            </label>
            <Button
              type="submit"
              disabled={busy || !username || !password}
              className="h-9 gap-1.5 px-4 text-[13px] font-semibold sm:mb-0"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
              新增
            </Button>
          </div>
        </form>
      </section>

      {/* 账户列表 */}
      <section>
        <h3 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
          账户列表
        </h3>
        <div className="soft-card overflow-hidden rounded-xl">
          <div className="divide-y divide-border/45">
            {loading ? (
              <div className="flex items-center justify-center px-5 py-10 text-[13px] text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                正在加载账户…
              </div>
            ) : sortedUsers.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] text-muted-foreground">
                暂无账户
              </div>
            ) : (
              sortedUsers.map((user) => {
                const pill = statusPill(user);
                const isSelf = currentUserId === user.user_id;
                const isLastEngineer = user.role === "engineer" && user.enabled && sortedUsers.filter(
                  (item) => item.role === "engineer" && item.enabled,
                ).length <= 1;
                return (
                  <div
                    key={user.user_id}
                    className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-[14px] font-medium leading-5 text-foreground">
                        <span className="truncate">{user.username}</span>
                        {isSelf ? (
                          <span className="rounded-full border border-border/60 bg-muted/50 px-1.5 py-px text-[10px] font-medium text-muted-foreground">
                            当前
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-px text-[11px] font-medium",
                            user.role === "engineer"
                              ? "bg-[hsl(var(--accent-primary)/0.12)] text-[hsl(var(--accent-primary))]"
                              : "bg-muted text-muted-foreground",
                          )}
                        >
                          {roleLabel(user.role)}
                        </span>
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-2 py-px text-[11px] font-medium",
                            pill === "active"
                              ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
                              : "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                          )}
                        >
                          {statusLabel(user)}
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:shrink-0">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={busy || isLastEngineer}
                        onClick={() =>
                          void run(
                            () =>
                              updateUser(gatewayToken, userToken, user.user_id, {
                                enabled: !user.enabled,
                              }),
                            user.enabled ? "账户已停用" : "账户已启用",
                          )
                        }
                        className="h-8 gap-1.5 px-2.5 text-[12px]"
                      >
                        <UserCog className="h-3.5 w-3.5" aria-hidden />
                        {user.enabled ? "停用" : "启用"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={busy || isLastEngineer}
                        onClick={() =>
                          void run(
                            () =>
                              updateUser(gatewayToken, userToken, user.user_id, {
                                role: user.role === "engineer" ? "operator" : "engineer",
                              }),
                            "角色已更新",
                          )
                        }
                        className="h-8 gap-1.5 px-2.5 text-[12px]"
                      >
                        <UserCog className="h-3.5 w-3.5" aria-hidden />
                        设为{user.role === "engineer" ? "操作员" : "工程师"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={busy || isSelf}
                        onClick={() => openResetPassword(user)}
                        className="h-8 gap-1.5 px-2.5 text-[12px]"
                      >
                        <KeyRound className="h-3.5 w-3.5" aria-hidden />
                        重置密码
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={busy || isSelf || isLastEngineer}
                        onClick={() => openDelete(user)}
                        className="h-8 gap-1.5 px-2.5 text-[12px] text-destructive hover:bg-destructive/8 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        删除
                      </Button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
        <p className="mt-2 px-1 text-[11px] leading-4 text-muted-foreground/80">
          为保护系统可用性，最后一个启用的工程师账户无法被停用、降级或删除；当前登录账户无法被删除。
        </p>
      </section>

      {/* 重置密码对话框 */}
      <Dialog open={passwordTarget !== null} onOpenChange={(open) => !open && setPasswordTarget(null)}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-[hsl(var(--accent-primary))]" aria-hidden />
              重置密码
            </DialogTitle>
            <DialogDescription>
              为账户 <span className="font-medium text-foreground">{passwordTarget?.username}</span> 设置新密码。重置后该账户的所有会话将立即失效。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitResetPassword} className="space-y-3">
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">新密码</span>
              <Input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="至少 4 个字符"
                autoComplete="new-password"
                autoFocus
                disabled={busy}
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">确认新密码</span>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="再次输入新密码"
                autoComplete="new-password"
                disabled={busy}
                aria-invalid={passwordMismatch}
              />
            </label>
            {passwordTooShort ? (
              <p className="text-[12px] text-destructive">密码至少 4 个字符。</p>
            ) : null}
            {passwordMismatch ? (
              <p className="text-[12px] text-destructive">两次输入的密码不一致。</p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setPasswordTarget(null)}
                disabled={busy}
              >
                取消
              </Button>
              <Button type="submit" disabled={busy || passwordFormInvalid}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
                确认重置
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除账户对话框 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <UserX className="h-4 w-4" aria-hidden />
              删除账户
            </DialogTitle>
            <DialogDescription>
              此操作不可撤销。账户 <span className="font-medium text-foreground">{deleteTarget?.username}</span> 的所有会话将立即失效，历史记录会保留。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitDelete} className="space-y-3">
            <div className="rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-[12px] text-destructive">
              请输入用户名 <span className="font-semibold">{deleteTarget?.username}</span> 以确认删除。
            </div>
            <label className="block space-y-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">用户名确认</span>
              <Input
                value={deleteConfirmName}
                onChange={(e) => setDeleteConfirmName(e.target.value)}
                placeholder={deleteTarget?.username ?? ""}
                autoComplete="off"
                autoFocus
                disabled={busy}
                aria-invalid={deleteConfirmMismatch}
              />
            </label>
            {deleteConfirmMismatch ? (
              <p className="text-[12px] text-destructive">输入的用户名不匹配。</p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setDeleteTarget(null)}
                disabled={busy}
              >
                取消
              </Button>
              <Button
                type="submit"
                variant="destructive"
                disabled={busy || deleteConfirmName.trim() !== deleteTarget?.username}
              >
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <Trash2 className="mr-2 h-4 w-4" aria-hidden />}
                永久删除
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 自我服务提示 */}
      <section>
        <h3 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
          修改自己的密码
        </h3>
        <div className="soft-card flex items-center gap-3 rounded-xl px-4 py-3.5 sm:px-5">
          <Lock className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="flex-1 text-[13px] text-muted-foreground">
            如需修改当前登录账户的密码，请在登录页使用「修改密码」入口。
          </span>
        </div>
      </section>
    </section>
  );
}
