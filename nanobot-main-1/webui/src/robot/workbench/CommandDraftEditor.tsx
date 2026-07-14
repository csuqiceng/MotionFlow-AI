import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EngineerCommandDraft } from "@/lib/engineer-workbench-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function CommandDraftEditor({
  draft,
  onSave,
  saving = false,
}: {
  draft: EngineerCommandDraft;
  onSave: (draft: EngineerCommandDraft) => void | Promise<void>;
  saving?: boolean;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(draft);
  const [parametersText, setParametersText] = useState(() => JSON.stringify(draft.parameters, null, 2));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(draft);
    setParametersText(JSON.stringify(draft.parameters, null, 2));
    setError(null);
  }, [draft]);

  const save = () => {
    try {
      const parameters = JSON.parse(parametersText) as Record<string, unknown>;
      if (parameters === null || Array.isArray(parameters) || typeof parameters !== "object") {
        throw new Error(t("library.workbench.invalidParametersObject"));
      }
      setError(null);
      void onSave({
        ...value,
        aliases: (value.aliases ?? []).filter(Boolean),
        parameters,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("library.workbench.invalidParametersJson"));
    }
  };

  return <form className="flex flex-col gap-3 p-4" onSubmit={(e) => { e.preventDefault(); save(); }}>
    <h2 className="text-lg font-semibold">{t("library.workbench.commandDraft")}</h2>
    <label className="text-sm">{t("library.workbench.name")}<Input aria-label={t("library.workbench.commandName")} value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
    <label className="text-sm">{t("library.workbench.aliases")}<Input aria-label={t("library.workbench.aliases")} value={(value.aliases ?? []).join(", ")} onChange={(e) => setValue({ ...value, aliases: e.target.value.split(",").map((item) => item.trim()) })} /></label>
    <label className="text-sm">{t("library.workbench.description")}<textarea aria-label={t("library.workbench.description")} className="mt-1 min-h-20 w-full rounded border border-input bg-background p-2 text-sm" value={value.description ?? ""} onChange={(e) => setValue({ ...value, description: e.target.value })} /></label>
    <label className="text-sm">{t("library.workbench.componentId")}<Input aria-label={t("library.workbench.componentId")} value={value.component_id} onChange={(e) => setValue({ ...value, component_id: e.target.value })} /></label>
    <label className="text-sm">{t("library.workbench.parametersJson")}<textarea aria-label={t("library.workbench.parametersJson")} className="mt-1 min-h-32 w-full rounded border border-input bg-background p-2 font-mono text-xs" value={parametersText} onChange={(e) => setParametersText(e.target.value)} /></label>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    <Button type="submit" disabled={saving}>{saving ? t("library.workbench.saving") : t("library.workbench.saveDraft")}</Button>
  </form>;
}
