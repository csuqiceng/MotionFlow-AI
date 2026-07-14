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
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [controllerHost, setControllerHost] = useState("10.168.3.21");
  const [checkedHost, setCheckedHost] = useState(preflight ? "10.168.3.21" : "");
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
      setUsername("");
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

  const controllerReady = preflight?.data.controller.state === "healthy" && checkedHost === controllerHost;
  const operatorBlocked = activeTab === "operator" && preflight !== undefined && !controllerReady;
  const submitDisabled = connectionError || usernameEmpty || passwordEmpty || submitting || throttled || operatorBlocked;

  const checkPreflight = async () => {
    setChecking(true);
    try {
      await onPreflight(controllerHost);
      setCheckedHost(controllerHost);
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
    <div className="flex min-h-full w-full items-center justify-center bg-slate-50 px-6 py-8">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-md flex-col gap-4 rounded-2xl border border-blue-200 bg-white p-8 shadow-sm"
        aria-label={t("login.title")}
      >
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-2xl font-bold text-slate-900">{t("login.preflight.systemTitle")}</p>
          <p className="text-sm text-muted-foreground">{t("login.hint")}</p>
        </div>

        <section className="space-y-2 border-t border-slate-200 pt-4" aria-label={t("login.preflight.connection")}>
          <label className="text-sm font-semibold" htmlFor="controller-host">{t("login.preflight.connection")}</label>
          <div className="flex gap-2">
            <Input id="controller-host" aria-label={t("login.preflight.address")} value={controllerHost}
              onChange={(e) => { setControllerHost(e.target.value); setCheckedHost(""); }} disabled={checking} />
            <Button type="button" variant="outline" onClick={() => void checkPreflight()} disabled={checking}>
              {checking ? t("login.preflight.checking") : t("login.preflight.checkConnection")}
            </Button>
          </div>
          <div role="status" className="space-y-1 text-sm">
            {(["controller", "voice", "ai"] as const).map((name) => {
              const item = preflight?.data[name];
              const label = t(`login.preflight.${name}`);
              return <p key={name} className={item?.state === "healthy" ? "text-emerald-700" : "text-amber-700"}>
                {item?.state === "healthy" ? "✓" : "!"} {label}: {item?.state === "healthy" ? t("login.preflight.healthy", { latency: item.latency_ms }) : item?.reason ?? t("login.preflight.pending")}
              </p>;
            })}
          </div>
        </section>

        {/* Tabs (no shadcn tabs.tsx exists, so render buttons with role=tab). */}
        <div
          role="tablist"
          aria-label={t("login.title")}
          className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1"
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
                  "inline-flex h-9 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors",
                  selected
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {errorText !== null && (
          <p role="alert" className="text-center text-sm text-destructive">
            {errorText}
          </p>
        )}

        {operatorBlocked && <p role="status" className="text-sm text-amber-700">{t("login.preflight.operatorGate")}</p>}

        <Input
          ref={usernameRef}
          type="text"
          autoComplete="username"
          placeholder={t("login.field.username")}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
          autoFocus
        />
        <Input
          ref={passwordRef}
          type="password"
          autoComplete="current-password"
          placeholder={t("login.field.password")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={submitting}
        />

        <Button type="submit" className="w-full bg-emerald-600 hover:bg-emerald-700" disabled={submitDisabled}>
          {submitting ? t("login.submitting") : t("login.submit")}
        </Button>
      </form>
    </div>
  );
}

export default LoginPage;
