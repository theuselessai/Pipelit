import { useQuery } from "@tanstack/react-query"
import { apiFetch } from "./client"

/**
 * Binary plugins, and the identities each one holds.
 *
 * Every response comes from running the plugin's own read verbs — the binary is
 * the only thing that knows which identities exist, because it owns the store.
 * Neither verb prints credential material by construction.
 */

export interface PluginSummary {
  plugin: string
  registered: boolean
  binary?: string
  registered_at?: string
  dev_mode?: boolean
}

export interface PluginSession {
  id: string
  subject: string | null
  env: string
  expires_at: string | null
  created_at: string
  last_used_at: string | null
}

export interface PluginEnvironment {
  name: string
  url: string
  kind: string
  created_at?: string
}

export function usePlugins() {
  return useQuery({
    queryKey: ["plugins"],
    queryFn: () => apiFetch<{ items: PluginSummary[]; total: number }>("/plugins/"),
  })
}

/** Identities held by one binary. Spawns a process, so it is not refetched idly. */
export function usePluginSessions(binary: string | undefined) {
  return useQuery({
    queryKey: ["plugins", binary, "sessions"],
    queryFn: () => apiFetch<{ items: PluginSession[]; unreadable: string[] }>(
      `/plugins/${binary}/sessions/`),
    enabled: Boolean(binary),
    staleTime: 30_000,
  })
}

export function usePluginEnvironments(binary: string | undefined) {
  return useQuery({
    queryKey: ["plugins", binary, "environments"],
    queryFn: () => apiFetch<{ items: PluginEnvironment[] }>(`/plugins/${binary}/environments/`),
    enabled: Boolean(binary),
    staleTime: 30_000,
  })
}

/**
 * One registered binary's catalog, in the legacy config-schema shape the
 * schema-driven form reads: an `operation` enum plus an `x-operations` sidecar
 * whose entries carry summary, params, session_required, timeout_default_s,
 * outputs and `domain`. `schema` is null for a registered binary whose pinned
 * catalog file cannot be read — the listing never fails as a whole.
 */
export interface BinaryCatalog {
  binary: string
  plugin: string
  schema: Record<string, unknown> | null
}

/** Catalogs of every registered binary. The pinned file is the source — no
 * process restart is needed for a newly registered binary to appear here. */
export function useBinaryCatalogs() {
  return useQuery({
    queryKey: ["plugins", "catalog"],
    queryFn: () => apiFetch<{ items: BinaryCatalog[]; total: number }>("/plugins/catalog/"),
    staleTime: 30_000,
  })
}
