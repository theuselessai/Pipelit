import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Workspace, WorkspaceCreate, WorkspaceUpdate, PaginatedResponse } from "@/types/models"

export function useWorkspaces(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", params.limit.toString())
  if (params?.offset) qs.set("offset", params.offset.toString())
  const q = qs.toString()
  return useQuery({ queryKey: ["workspaces", params], queryFn: () => apiFetch<PaginatedResponse<Workspace>>(`/workspaces/${q ? `?${q}` : ""}`) })
}

export function useWorkspace(id: number | string) {
  return useQuery({
    queryKey: ["workspace", id],
    queryFn: () => apiFetch<Workspace>(`/workspaces/${id}/`),
    enabled: !!id,
  })
}

export function useCreateWorkspace() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: WorkspaceCreate) => apiFetch<Workspace>("/workspaces/", { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces"] }) })
}

export function useUpdateWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: WorkspaceUpdate }) => apiFetch<Workspace>(`/workspaces/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: (data, vars) => {
      qc.invalidateQueries({ queryKey: ["workspaces"] })
      qc.setQueryData(["workspace", String(vars.id)], data)
    },
  })
}

export function useDeleteWorkspace() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: number) => apiFetch<void>(`/workspaces/${id}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces"] }) })
}

export function useBatchDeleteWorkspaces() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: number[]) => apiFetch<void>("/workspaces/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces"] }),
  })
}

export function useResetWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch<{ ok: boolean; message: string }>(`/workspaces/${id}/reset/`, { method: "POST" }),
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: ["workspace", id] }),
  })
}

export function useResetWorkspaceRootfs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch<{ ok: boolean; message: string }>(`/workspaces/${id}/reset-rootfs/`, { method: "POST" }),
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: ["workspace", id] }),
  })
}
