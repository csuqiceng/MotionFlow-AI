import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

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
    <div className="flex min-h-full w-full items-center justify-center bg-background px-6 py-8">
      <form
        onSubmit={handleSubmit}
        className={cn(
          "flex w-full max-w-md flex-col gap-5 rounded-2xl border p-8 shadow-lg",
          // Light: neutral card; Dark: glass-morphism industrial card
          "border-border/60 bg-card/80",
          "dark:border-[hsl(var(--accent-primary)/0.15)] dark:bg-[hsl(220_18%_9%/0.75)] dark:shadow-[0_0_40px_-12px_hsl(var(--accent-primary)/0.12)]",
          "dark:backdrop-blur-xl dark:backdrop-saturate-150",
        )}
        aria-label={t("login.title")}
      >
        {/* Title with accent glow */}
        <div className="flex flex-col items-center gap-1.5 text-center">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-[hsl(var(--accent-primary))] shadow-[0_0_10px_hsl(var(--accent-primary)/0.5)]" aria-hidden />
            <p className="text-2xl font-bold tracking-tight text-foreground">{t("login.preflight.systemTitle")}</p>
          </div>
          <p className="text-sm text-muted-foreground">{t("login.hint")}</p>
        </div>

        <section className="space-y-2.5 border-t border-border/40 pt-4" aria-label={t("login.preflight.connection")}>
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground" htmlFor="controller-host">{t("login.preflight.connection")}</label>
          <div className="flex gap-2">
            <Input id="controller-host" aria-label={t("login.preflight.address")} value={controllerHost}
              onChange={(e) => setControllerHost(e.target.value)} disabled={checking}
              className="dark:border-[hsl(var(--accent-primary)/0.2)] dark:bg-[hsl(220_16%_12%/0.6)] dark:focus-visible:ring-[hsl(var(--accent-primary)/0.4)]" />
            <Button type="button" variant="outline" onClick={() => void checkPreflight()} disabled={checking}
              className="dark:border-[hsl(var(--accent-primary)/0.25)] dark:hover:bg-[hsl(var(--accent-primary)/0.1)]">
              {checking ? t("login.preflight.checking") : t("login.preflight.checkConnection")}
            </Button>
          </div>
          {/* Industrial status indicators */}
          <div role="status" className="flex flex-col gap-1.5 rounded-lg border border-border/30 bg-muted/30 p-2.5 text-sm dark:bg-[hsl(220_16%_10%/0.5)]">
            {(["controller", "voice", "ai"] as const).map((name) => {
              const item = preflight?.data[name];
              const healthy = item?.state === "healthy";
              return (
                <div key={name} className="flex items-center gap-2">
                  <span className={cn(
                    "inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold",
                    healthy
                      ? "bg-emerald-500/20 text-emerald-400 dark:bg-emerald-500/15 dark:text-emerald-400 dark:shadow-[0_0_6px_hsl(142_72%_40%/0.3)]"
                      : "bg-amber-500/20 text-amber-400 dark:bg-amber-500/15 dark:text-amber-400",
                  )}>
                    {healthy ? "✓" : "!"}
                  </span>
                  <span className="text-xs text-muted-foreground">{t(`login.preflight.${name}`)}</span>
                  <span className="ml-auto text-xs tabular-nums">
                    {healthy
                      ? <span className="text-emerald-500/80 dark:text-emerald-400/70">{t("login.preflight.healthy", { latency: item.latency_ms })}</span>
                      : <span className="text-amber-500/80 dark:text-amber-400/70">{item?.reason ?? t("login.preflight.pending")}</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        {/* Role tabs — industrial segmented control */}
        <div
          role="tablist"
          aria-label={t("login.title")}
          className={cn(
            "grid grid-cols-2 gap-1 rounded-lg p-1",
            "bg-muted/60 dark:bg-[hsl(220_16%_12%/0.5)] dark:border dark:border-border/20",
          )}
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
                  "inline-flex h-9 items-center justify-center rounded-md px-3 text-sm font-medium transition-all",
                  selected
                    ? "bg-background text-foreground shadow-sm dark:bg-[hsl(var(--accent-primary)/0.15)] dark:text-[hsl(var(--accent-primary-foreground))] dark:shadow-[0_0_12px_hsl(var(--accent-primary)/0.12)]"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {errorText !== null && (
          <p role="alert" className="text-center text-sm text-destructive dark:text-red-400">
            {errorText}
          </p>
        )}

        <Input
          ref={usernameRef}
          type="text"
          autoComplete="username"
          placeholder={t("login.field.username")}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
          autoFocus
          className="dark:border-[hsl(var(--accent-primary)/0.15)] dark:bg-[hsl(220_16%_12%/0.6)] dark:focus-visible:ring-[hsl(var(--accent-primary)/0.4)]"
        />
        <Input
          ref={passwordRef}
          type="password"
          autoComplete="current-password"
          placeholder={t("login.field.password")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={submitting}
          className="dark:border-[hsl(var(--accent-primary)/0.15)] dark:bg-[hsl(220_16%_12%/0.6)] dark:focus-visible:ring-[hsl(var(--accent-primary)/0.4)]"
        />

        <Button type="submit"
          className={cn(
            "w-full font-semibold transition-all",
            "bg-[hsl(var(--accent-primary))] text-[hsl(var(--accent-primary-foreground))]",
            "hover:bg-[hsl(var(--accent-primary)/0.88)]",
            "dark:shadow-[0_0_20px_hsl(var(--accent-primary)/0.2)] dark:hover:shadow-[0_0_28px_hsl(var(--accent-primary)/0.3)]",
          )}
          disabled={submitDisabled}
        >
          {submitting ? t("login.submitting") : t("login.submit")}
        </Button>
      </form>
    </div>
  );
}

export default LoginPage;
