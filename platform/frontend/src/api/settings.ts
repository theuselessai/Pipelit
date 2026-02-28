import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { EnvironmentInfo } from "@/types/models"

export interface PlatformConfigOut {
  pipelit_dir: string
  sandbox_mode: string
  database_url: string
  redis_url: string
  log_level: string
  log_file: string
  platform_base_url: string
  cors_allow_all_origins: boolean | null
  zombie_execution_threshold_seconds: number | null
}

export interface SettingsResponse {
  config: PlatformConfigOut
  environment: EnvironmentInfo
}

export interface SettingsUpdate {
  sandbox_mode?: string
  database_url?: string
  redis_url?: string
  log_level?: string
  log_file?: string
  platform_base_url?: string
  cors_allow_all_origins?: boolean
  zombie_execution_threshold_seconds?: number
}

export interface SettingsUpdateResponse {
  config: PlatformConfigOut
  hot_reloaded: string[]
  restart_required: string[]
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => apiFetch<SettingsResponse>("/settings/"),
  })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SettingsUpdate) =>
      apiFetch<SettingsUpdateResponse>("/settings/", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  })
}

export function useRecheckEnvironment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<{ environment: EnvironmentInfo }>("/settings/recheck-environment/", {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  })
}
