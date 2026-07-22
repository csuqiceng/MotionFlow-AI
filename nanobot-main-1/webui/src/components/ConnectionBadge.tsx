import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";

const DOT_CLASS: Record<ConnectionStatus, string> = {
  idle: "status-dot status-dot--idle",
  connecting: "status-dot status-dot--warn",
  open: "status-dot status-dot--ok",
  reconnecting: "status-dot status-dot--warn",
  closed: "status-dot status-dot--idle",
  error: "status-dot status-dot--danger",
};

export function ConnectionBadge() {
  const { t } = useTranslation();
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);

  useEffect(() => client.onStatus(setStatus), [client]);

  const pulsing =
    status === "connecting" ||
    status === "reconnecting" ||
    status === "error";
  const label = t(`connection.${status}`);
  return (
    <span
      className={cn(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
        "text-muted-foreground/70 hover:bg-sidebar-accent/65",
      )}
      aria-live="polite"
      role="status"
      title={label}
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        {pulsing && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
        )}
        <span className={cn("relative inline-flex h-2 w-2", DOT_CLASS[status])} />
      </span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
