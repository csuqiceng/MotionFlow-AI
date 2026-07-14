import { createContext, useContext, type ReactNode } from "react";

import type { NanobotClient } from "@/lib/nanobot-client";

/** Slice ② authenticated user surfaced through the client context.
 *
 * Empty until F3 wires the real login flow; consumers treat the presence of a
 * non-empty ``user_id`` as "logged in". The defaults keep pre-F3 callers
 * (App.tsx, test fixtures that only pass ``client`` + ``token``) compiling. */
export interface ClientUser {
  user_id: string;
  username: string;
  role: "operator" | "engineer";
}

interface ClientContextValue {
  client: NanobotClient;
  /** WebSocket (gateway) one-shot bootstrap token. */
  token: string;
  /** Slice ② user session token (sent as the WS ``auth`` first-frame). */
  userToken: string;
  /** Slice ② authenticated user (empty until login). */
  user: ClientUser;
  modelName: string | null;
}

const DEFAULT_USER: ClientUser = { user_id: "", username: "", role: "operator" };

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  userToken = "",
  user = DEFAULT_USER,
  modelName = null,
  children,
}: {
  client: NanobotClient;
  token: string;
  /** @default "" — F3 passes the real user session token after login. */
  userToken?: string;
  /** @default { user_id: "", username: "", role: "operator" } */
  user?: ClientUser;
  modelName?: string | null;
  children: ReactNode;
}) {
  return (
    <ClientContext.Provider value={{ client, token, userToken, user, modelName }}>
      {children}
    </ClientContext.Provider>
  );
}

export function useClient(): ClientContextValue {
  const ctx = useContext(ClientContext);
  if (!ctx) {
    throw new Error("useClient must be used within a ClientProvider");
  }
  return ctx;
}
