import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Cpu, Lock, Mic, ShieldCheck, User, Wifi, LogIn } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { LoginPreflightResponse } from "@/lib/bootstrap";

export type LoginRole = "operator" | "engineer";

export interface LoginPageSubmit {
  username: string;
  password: string;
  role: LoginRole;
}

export interface LoginPageError {
  status?: number; // HTTP status from login attempt (401/403/429/5xx)
  code?: string; // e.g. "user_disabled", "too_many_attempts", "invalid_credentials"
  retryAfter?: number; // seconds, for 429
}

export interface LoginPageProps {
  /** false → show connection error, disable submit. Takes precedence over `error`. */
  bootstrapOk: boolean;
  /** last login attempt error */
  error: LoginPageError | null;
  /** login in flight (disable submit) */
  submitting?: boolean;
  preflight?: LoginPreflightResponse;
  onPreflight?: (controllerHost: string) => Promise<LoginPreflightResponse>;
  onSubmit: (creds: LoginPageSubmit) => void;
}

type TabId = LoginRole;

function pickInitialTab(hash: string): TabId {
  return hash.startsWith("#/engineer") ? "engineer" : "operator";
}

function defaultUsername(role: LoginRole): string {
  return role === "engineer" ? "admin" : "operator";
}

export function LoginPage({
  bootstrapOk,
  error,
  submitting = false,
  preflight,
  onPreflight = async () => { throw new Error("preflight unavailable"); },
  onSubmit,
}: LoginPageProps) {
  const { t } = useTranslation();

  // Read hash ONCE on mount to pick the initial tab. URL priority over the
  // operator default: #/engineer → engineer; anything else → operator.
  const [activeTab, setActiveTab] = useState<TabId>(() =>
    pickInitialTab(typeof window === "undefined" ? "" : window.location.hash),
  );
  const [username, setUsername] = useState(() => defaultUsername(activeTab));
  const [password, setPassword] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [controllerHost, setControllerHost] = useState("10.168.3.21");
  const [checking, setChecking] = useState(false);

  const usernameRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const switchTab = useCallback(
    (next: TabId) => {
      // No-op when re-selecting the active tab.
      if (activeTab === next) return;
      // Usernames are role-scoped: clear fields (and any displayed error,
      // since error comes from props it stays until parent changes it, but
      // clearing inputs is what we own).
      setActiveTab(next);
      setUsername(defaultUsername(next));
      setPassword("");
      setCountdown(0);
    },
    [activeTab],
  );

  // ----- Error classification (derived from props) -----
  // bootstrapOk===false takes precedence over any `error`.
  const connectionError = !bootstrapOk;

  const credentialError =
    !connectionError &&
    error !== null &&
    (error?.status === 401 ||
      (error?.status === 403 && error?.code !== "user_disabled"));

  const disabledError =
    !connectionError && error !== null && error?.status === 403 && error?.code === "user_disabled";

  const throttleError = !connectionError && error !== null && error?.status === 429;

  const serverError = !connectionError && error !== null && (error?.status ?? 0) >= 500;

  // ----- 429 countdown: tick down each second; re-enable submit when 0 -----
  useEffect(() => {
    if (!throttleError) {
      setCountdown(0);
      return;
    }
    const initial = Math.max(0, Math.floor(error?.retryAfter ?? 0));
    setCountdown(initial);
    if (initial <= 0) return;
    const handle = window.setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          window.clearInterval(handle);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(handle);
  }, [throttleError, error?.retryAfter]);

  // ----- Side effects of credential/disabled errors: clear password, focus password -----
  // 401 / 403 non-disabled: clear password, keep username, focus password.
  // 403 user_disabled: clear password, keep username.
  useEffect(() => {
    if (credentialError || disabledError) {
      setPassword("");
      // Focus password field after the cleared value settles.
      const id = window.setTimeout(() => passwordRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [credentialError, disabledError]);

  const usernameEmpty = username.trim() === "";
  const passwordEmpty = password === "";
  const throttled = throttleError && countdown > 0;

  const submitDisabled = usernameEmpty || passwordEmpty || submitting || throttled;

  const checkPreflight = async () => {
    setChecking(true);
    try {
      await onPreflight(controllerHost);
    } finally {
      setChecking(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (submitDisabled) return;
    onSubmit({ username: username.trim(), password, role: activeTab });
  };

  const errorText = useMemo(() => {
    if (connectionError) return t("login.error.bootstrap");
    if (disabledError) return t("login.error.disabled");
    if (throttleError) return t("login.error.throttle", { count: countdown });
    if (serverError) return t("login.error.server");
    if (credentialError) return t("login.error.credentials");
    return null;
  }, [
    connectionError,
    disabledError,
    throttleError,
    serverError,
    credentialError,
    countdown,
    t,
  ]);

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: "operator", label: t("login.tab.operator") },
    { id: "engineer", label: t("login.tab.engineer") },
  ];

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8 sm:px-6 lg:px-8">
      <div className="grid w-full max-w-4xl items-stretch gap-10 lg:grid-cols-2 lg:gap-14">

        {/* ============ 左侧品牌区（lg+ 显示） ============ */}
        <section className="hidden flex-col justify-center lg:flex">
          {/* Compact introduction and capability summary, with relaxed internal rhythm. */}
          <div className="animate-fade-in-up animate-delay-1 max-w-sm">
            <div className="mb-5 inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              <span className="data-mono text-[11px] uppercase tracking-wider text-primary">
                {t("login.brand.compliance")}
              </span>
            </div>

            <h2 className="text-3xl font-bold leading-[1.15] text-foreground">
              {t("login.brand.title1")}<br />
              <span className="text-primary">{t("login.brand.title2")}</span>{" "}
              {t("login.brand.title3")}
            </h2>
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              {t("login.brand.description")}
            </p>

            <ul className="mt-9 space-y-4">
              {([1, 2, 3] as const).map((n) => (
                <li key={n} className="flex items-start gap-3">
                  <span className="feature-check">
                    <Check className="h-3 w-3" />
                  </span>
                  <div>
                    <div className="text-sm font-semibold text-foreground">
                      {t(`login.brand.feature${n}Title`)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t(`login.brand.feature${n}Desc`)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

        </section>

        {/* ============ 右侧登录卡片区 ============ */}
        <section className="relative flex items-center justify-center">
          <form
            onSubmit={handleSubmit}
            className="glass-card login-card animate-fade-in-up animate-delay-2 w-full max-w-md rounded-xl p-8"
            aria-label={t("login.title")}
          >
            {/* 控制器连接区 */}
            <section aria-label={t("login.preflight.connection")}>
              <div className="mb-2 flex items-center gap-1.5">
                <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("login.preflight.connection")}
                </span>
              </div>

              {/* 地址输入 + 检测按钮 */}
              <div className="flex gap-2">
                <Input
                  id="controller-host"
                  aria-label={t("login.preflight.address")}
                  value={controllerHost}
                  onChange={(e) => setControllerHost(e.target.value)}
                  disabled={checking}
                  className="field-input data-mono h-10 flex-1"
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void checkPreflight()}
                  disabled={checking}
                  className="btn-outline h-10 shrink-0"
                >
                  <Wifi className="h-3.5 w-3.5" />
                  {checking ? t("login.preflight.checking") : t("login.preflight.checkConnection")}
                </Button>
              </div>

              <ControllerStatusRow preflight={preflight} t={t} />

              {/* 语音 / AI 服务芯片 */}
              <div className="mt-2 grid grid-cols-2 gap-2">
                {(["voice", "ai"] as const).map((name) => {
                  const item = preflight?.data[name];
                  const healthy = item?.state === "healthy";
                  const Icon = name === "voice" ? Mic : Cpu;
                  return (
                    <div
                      key={name}
                      className="svc-chip"
                      title={
                        healthy
                          ? formatServiceHealth(item?.latency_ms, t)
                          : (item?.reason ?? t("login.preflight.pending"))
                      }
                    >
                      <span
                        className={cn(
                          "status-dot",
                          healthy ? "status-dot--ok" : "status-dot--warn",
                        )}
                      />
                      <Icon className="h-3.5 w-3.5 text-success" />
                      <span className="truncate text-foreground/80">
                        {t(`login.preflight.${name}`)}
                      </span>
                      <span className="data-mono ml-auto text-[11px] font-semibold text-success">
                        {healthy
                          ? formatServiceHealth(item?.latency_ms, t)
                          : t("login.preflight.unavailableShort")}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* 3. 角色分段控制 */}
            <div className="mt-5">
              <div
                role="tablist"
                aria-label={t("login.title")}
                className="segmented grid-cols-2"
              >
                {tabs.map((tab) => {
                  const selected = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => switchTab(tab.id)}
                      className={cn(
                        "segmented__item",
                        selected && "segmented__item--active",
                      )}
                    >
                      <User className="mr-1.5 h-3.5 w-3.5" />
                      {tab.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {errorText !== null && (
              <p role="alert" className="mt-3 text-center text-sm text-destructive">
                {errorText}
              </p>
            )}

            {/* 4. 用户名（带图标） */}
            <div className="mt-5">
              <label
                className="mb-1.5 block text-xs font-medium text-muted-foreground"
                htmlFor="username"
              >
                {t("login.field.username")}
              </label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  ref={usernameRef}
                  id="username"
                  type="text"
                  autoComplete="username"
                  placeholder={t("login.field.username")}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={submitting}
                  autoFocus
                  className="field-input w-full pl-9"
                />
              </div>
            </div>

            {/* 5. 密码（带图标） */}
            <div className="mt-3">
              <label
                className="mb-1.5 block text-xs font-medium text-muted-foreground"
                htmlFor="password"
              >
                {t("login.field.password")}
              </label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  ref={passwordRef}
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder={t("login.field.password")}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  className="field-input w-full pl-9"
                />
              </div>
            </div>

            {/* 6. 登录按钮 */}
            <Button
              type="submit"
              className="btn-primary mt-6 flex h-10 w-full items-center justify-center gap-2"
              disabled={submitDisabled}
            >
              <LogIn className="h-4 w-4" />
              {submitting ? t("login.submitting") : t("login.submit")}
            </Button>

            {/* 7. 底部版本号 */}
            <div className="mt-5 flex items-center justify-center gap-2 text-muted-foreground">
              <span
                className="status-dot status-dot--ok"
                style={{ width: "0.375rem", height: "0.375rem" }}
              />
              <span className="data-mono text-xs">{t("login.brand.versionLabel")}</span>
              <span className="text-xs text-muted-foreground/60">·</span>
              <span className="data-mono text-[11px] uppercase tracking-wider text-muted-foreground/70">
                {t("login.brand.buildLabel")}
              </span>
            </div>
          </form>
        </section>

      </div>
    </main>
  );
}

/** Controller status row: pulse dot + human-readable state.
 * Pulses when unhealthy (checking, simulation, or disconnected), steady green
 * when a real lower machine is connected. Raw API reason codes stay hidden.
 */
function ControllerStatusRow({
  preflight,
  t,
}: {
  preflight?: LoginPreflightResponse;
  t: ReturnType<typeof useTranslation>["t"];
}) {
  const item = preflight?.data.controller;
  const healthy = item?.state === "healthy";
  const checking = item === undefined && preflight === undefined; // not yet checked
  const simulation = item?.reason === "simulation_mode";
  const disconnected = item?.reason === "lower_machine_not_connected";
  const stateKey = healthy
    ? "lowerMachineConnected"
    : simulation
      ? "simulationShort"
      : disconnected
        ? "lowerMachineDisconnected"
    : checking
      ? "pendingShort"
      : "offlineShort";

  return (
    <div className={cn(
      "mt-2.5 flex items-center justify-between rounded-lg px-3 py-2",
      healthy
        ? "border border-success/20 bg-success/5"
        : "border border-border/50",
    )}>
      <div className="flex items-center gap-2">
        <span className="relative inline-flex h-2.5 w-2.5 shrink-0">
          {healthy ? (
            <span className="status-dot status-dot--ok absolute inset-0" />
          ) : (
            <>
              <span className="status-dot status-dot--warn absolute inset-0" />
              <span
                className="preflight-pulse-ring absolute inset-0 rounded-full bg-amber-500/40 dark:bg-amber-400/40"
                aria-hidden
              />
            </>
          )}
        </span>
        <span className="text-xs font-medium text-foreground">
          {t(`login.preflight.${stateKey}`)}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{t("login.preflight.latency")}</span>
        <span className="data-mono text-xs font-semibold text-success">
          {healthy && item?.latency_ms !== undefined
            ? t("login.preflight.healthyShort", { latency: item.latency_ms })
            : "—"}
        </span>
      </div>
    </div>
  );
}

function formatServiceHealth(
  latencyMs: number | undefined,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  return typeof latencyMs === "number"
    ? t("login.preflight.healthyShort", { latency: latencyMs })
    : t("login.preflight.healthyText");
}

export default LoginPage;
