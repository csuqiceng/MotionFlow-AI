import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EngineerCommandDraft } from "@/lib/engineer-workbench-api";
import type { LibraryComponent, LibraryParameterField } from "@/lib/robot-library-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function CommandDraftEditor({
  draft,
  onSave,
  components = [],
  saving = false,
}: {
  draft: EngineerCommandDraft;
  onSave: (draft: EngineerCommandDraft) => void | Promise<void>;
  components?: LibraryComponent[];
  saving?: boolean;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(draft);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(draft);
    setError(null);
  }, [draft]);

  const save = () => {
    if (components.length > 0 && !value.component_id) { setError(t("library.workbench.selectCommandType")); return; }
    setError(null);
    void onSave({ ...value, aliases: (value.aliases ?? []).filter(Boolean) });
  };

  const selected = components.find((component) => component.id === value.component_id);
  const defaults = (component?: LibraryComponent): Record<string, unknown> => Object.fromEntries(
    (component?.parameters ?? []).filter((field) => field.default !== undefined).map((field) => [field.name, field.default]),
  );
  const parameterValue = (field: LibraryParameterField): string | number => {
    const raw = value.parameters[field.name];
    return raw === undefined || raw === null ? "" : (raw as string | number);
  };
  const setParameter = (field: LibraryParameterField, raw: string) => {
    const next = field.type === "int" || field.type === "float" ? (raw === "" ? "" : Number(raw)) : raw;
    setValue((current) => ({ ...current, parameters: { ...current.parameters, [field.name]: next } }));
  };

  return <form className="flex flex-col gap-3 p-4" onSubmit={(e) => { e.preventDefault(); save(); }}>
    <h2 className="text-lg font-semibold">{t("library.workbench.commandDraft")}</h2>
    <label className="text-sm">{t("library.workbench.name")}<Input aria-label={t("library.workbench.commandName")} value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
    <label className="text-sm">{t("library.workbench.aliases")}<Input aria-label={t("library.workbench.aliases")} value={(value.aliases ?? []).join(", ")} onChange={(e) => setValue({ ...value, aliases: e.target.value.split(",").map((item) => item.trim()) })} /></label>
    <label className="text-sm">{t("library.workbench.description")}<textarea aria-label={t("library.workbench.description")} className="mt-1 min-h-20 w-full rounded border border-input bg-background p-2 text-sm" value={value.description ?? ""} onChange={(e) => setValue({ ...value, description: e.target.value })} /></label>
    <label className="text-sm">{t("library.workbench.commandType")}<select aria-label={t("library.workbench.commandType")} className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={value.component_id} onChange={(e) => { const component = components.find((item) => item.id === e.target.value); setValue({ ...value, component_id: e.target.value, parameters: defaults(component) }); }}><option value="">{t("library.workbench.selectCommandType")}</option>{components.map((component) => <option key={component.id} value={component.id}>{component.name}</option>)}</select></label>
    {selected?.parameters.map((field) => <label key={field.name} className="text-sm">{field.name}{field.unit ? ` (${field.unit})` : ""}<Input aria-label={field.name} type={field.type === "int" || field.type === "float" ? "number" : "text"} value={parameterValue(field)} onChange={(e) => setParameter(field, e.target.value)} /></label>)}
    {selected ? <details><summary>{t("library.workbench.parameterPreview")}</summary><pre className="mt-2 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(value.parameters, null, 2)}</pre></details> : null}
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    <Button type="submit" disabled={saving}>{saving ? t("library.workbench.saving") : t("library.workbench.saveDraft")}</Button>
  </form>;
}
