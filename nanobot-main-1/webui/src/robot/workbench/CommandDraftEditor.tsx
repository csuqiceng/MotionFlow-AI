import { useEffect, useState } from "react";

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
        throw new Error("Parameters must be a JSON object.");
      }
      setError(null);
      void onSave({
        ...value,
        aliases: (value.aliases ?? []).filter(Boolean),
        parameters,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Parameters must be valid JSON.");
    }
  };

  return <form className="flex flex-col gap-3 p-4" onSubmit={(e) => { e.preventDefault(); save(); }}>
    <h2 className="text-lg font-semibold">Command draft</h2>
    <label className="text-sm">Name<Input aria-label="Command name" value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
    <label className="text-sm">Aliases<Input aria-label="Aliases" value={(value.aliases ?? []).join(", ")} onChange={(e) => setValue({ ...value, aliases: e.target.value.split(",").map((item) => item.trim()) })} /></label>
    <label className="text-sm">Description<textarea aria-label="Command description" className="mt-1 min-h-20 w-full rounded border border-input bg-background p-2 text-sm" value={value.description ?? ""} onChange={(e) => setValue({ ...value, description: e.target.value })} /></label>
    <label className="text-sm">Component ID<Input aria-label="Component ID" value={value.component_id} onChange={(e) => setValue({ ...value, component_id: e.target.value })} /></label>
    <label className="text-sm">Parameters JSON<textarea aria-label="Parameters JSON" className="mt-1 min-h-32 w-full rounded border border-input bg-background p-2 font-mono text-xs" value={parametersText} onChange={(e) => setParametersText(e.target.value)} /></label>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save draft"}</Button>
  </form>;
}
