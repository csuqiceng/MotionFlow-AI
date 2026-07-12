import { useTranslation } from "react-i18next";
import type { LibraryCommand } from "@/lib/robot-library-api";

export function CommandDetail({ command }: { command: LibraryCommand }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 p-4">
      <h2 className="text-lg font-semibold">{command.name}</h2>
      {command.description ? (
        <p className="text-sm text-muted-foreground">{command.description}</p>
      ) : null}
      {command.aliases.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("library.aliases", { defaultValue: "Aliases" })}: {command.aliases.join(", ")}
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">component_id</dt>
          <dd className="font-mono">{command.component_id}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">risk_level</dt>
          <dd>{command.risk_level}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">status</dt>
          <dd>{command.status}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">version</dt>
          <dd>{command.version}</dd>
        </div>
      </dl>
      <div>
        <p className="text-xs text-muted-foreground">parameters</p>
        <table className="mt-1 w-full text-xs">
          <tbody>
            {Object.entries(command.parameters).map(([k, v]) => (
              <tr key={k} className="border-b border-border/40">
                <td className="py-1 pr-2 font-mono">{k}</td>
                <td className="py-1 font-mono">{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
