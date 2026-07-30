import { useEffect, useState } from "react";

import {
  robotLibraryCommand,
  robotLibraryCommands,
  robotLibraryFlow,
  robotLibraryFlows,
  type LibraryCommand,
  type LibraryCommandFilters,
  type LibraryFlow,
} from "@/lib/robot-library-api";
import { engineerCommandEntities, engineerCommandEntity, engineerFlowEntities, engineerFlowEntity } from "@/lib/engineer-workbench-api";

export type LibraryTab = "commands" | "flows";

export interface LibraryFilters {
  q: string;
  component_id: string;
  risk_level: string;
  status: string;
}

export interface UseRobotLibraryResult {
  items: LibraryCommand[] | LibraryFlow[];
  loading: boolean;
  error: string | null;
  filters: LibraryFilters;
  setFilters: (patch: Partial<LibraryFilters>) => void;
  selectedId: string | null;
  select: (id: string | null) => void;
  detail: LibraryCommand | LibraryFlow | null;
  detailLoading: boolean;
  detailError: string | null;
  /** Refetch the list without discarding the selected detail or an external editor. */
  refresh: () => void;
}

const EMPTY_FILTERS: LibraryFilters = { q: "", component_id: "", risk_level: "", status: "" };

function commandFromEntity(entity: Record<string, any>): LibraryCommand {
  const value = entity.draft ?? entity.versions?.[String(entity.published_version)] ?? {};
  return { ...value, id: entity.command_id, name: value.name ?? entity.command_id, aliases: value.aliases ?? [], description: value.description ?? "", component_id: value.component_id ?? "", parameters: value.parameters ?? {}, risk_level: value.risk_level ?? "", status: entity.draft ? "draft" : "published", version: value.version ?? 0, source: value.source ?? "", created_by: value.created_by ?? "", created_at: value.created_at ?? "", updated_at: value.updated_at ?? "", published_at: value.published_at ?? "" };
}
function normalizeFlow(value: Record<string, any>, fallbackId = "", fallbackState = "published"): LibraryFlow {
  const steps = Array.isArray(value.steps) ? value.steps : [];
  const flowId = String(value.flow_id ?? fallbackId ?? value.name ?? "");
  return {
    ...value,
    flow_id: flowId,
    name: String(value.name ?? flowId),
    description: String(value.description ?? ""),
    steps,
    step_delay_ms: Number(value.step_delay_ms ?? 0),
    rehearsal_spd: Number(value.rehearsal_spd ?? 100),
    confirmed: Boolean(value.confirmed),
    version: Number(value.version ?? 0),
    state: String(value.state ?? fallbackState),
    current_step: Number(value.current_step ?? 0),
    created_by: String(value.created_by ?? ""),
    created_at: String(value.created_at ?? ""),
    updated_at: String(value.updated_at ?? ""),
  };
}
function flowFromEntity(entity: Record<string, any>): LibraryFlow {
  const value = entity.draft ?? entity.versions?.[String(entity.published_version)] ?? {};
  return normalizeFlow(value, entity.flow_id, entity.draft ? "draft" : "published");
}
export function useRobotLibrary(token: string, tab: LibraryTab, engineerToken?: string): UseRobotLibraryResult {
  const [filters, setFiltersState] = useState<LibraryFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<LibraryCommand[] | LibraryFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryCommand | LibraryFlow | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);

  // When the tab changes, synchronously clear the previous tab's items/detail so
  // we never render stale items (e.g. commands under the flows tab) during the
  // brief window before the new fetch resolves — that mismatch crashed the flows
  // tab (command items have no `steps`). React's "adjust state when a prop
  // changes" pattern; re-renders immediately with items=[] + loading=true.
  const [lastTab, setLastTab] = useState<LibraryTab>(tab);
  if (tab !== lastTab) {
    setLastTab(tab);
    setItems([]);
    setLoading(true);
    setError(null);
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
  }

  const setFilters = (patch: Partial<LibraryFilters>) => {
    setFiltersState((current) => ({ ...current, ...patch }));
    setSelectedId(null);
    setDetail(null);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const apiFilters: LibraryCommandFilters = {
      q: filters.q || undefined,
      component_id: filters.component_id || undefined,
      risk_level: filters.risk_level || undefined,
      status: filters.status || undefined,
    };
    const promise =
      engineerToken ? (tab === "commands"
        ? engineerCommandEntities(token, engineerToken).then((r) => r.data.entities.map(commandFromEntity))
        : engineerFlowEntities(token, engineerToken).then((r) => r.data.entities.map(flowFromEntity))) : tab === "commands"
        ? robotLibraryCommands(token, apiFilters).then((r) => r.data.items as LibraryCommand[])
        : robotLibraryFlows(token).then((r) => {
            // Flow API has no server-side filter — apply q client-side (name/description).
            const all = r.data.items.map((item) => normalizeFlow(item as Record<string, any>));
            const q = filters.q.trim().toLowerCase();
            if (!q) return all;
            return all.filter(
              (f) =>
                f.name.toLowerCase().includes(q) ||
                (f.description ?? "").toLowerCase().includes(q),
            );
          });
    promise
      .then((result) => {
        if (!cancelled) {
          setItems(result);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setItems([]);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, tab, filters.q, filters.component_id, filters.risk_level, filters.status, refreshVersion]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    const promise =
      engineerToken ? (tab === "commands"
        ? engineerCommandEntity(token, engineerToken, selectedId).then((r) => commandFromEntity(r.data as Record<string, any>))
        : engineerFlowEntity(token, engineerToken, selectedId).then((r) => flowFromEntity(r.data as Record<string, any>))) : tab === "commands"
        ? robotLibraryCommand(token, selectedId).then((r) => r.data as LibraryCommand)
        : robotLibraryFlow(token, selectedId).then((r) => normalizeFlow(r.data as Record<string, any>, selectedId));
    promise
      .then((result) => {
        if (!cancelled) {
          setDetail(result);
          setDetailLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setDetailError(e instanceof Error ? e.message : String(e));
          setDetail(null);
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, tab, selectedId, refreshVersion, engineerToken]);

  return {
    items,
    loading,
    error,
    filters,
    setFilters,
    selectedId,
    select: setSelectedId,
    detail,
    detailLoading,
    detailError,
    refresh: () => setRefreshVersion((version) => version + 1),
  };
}
