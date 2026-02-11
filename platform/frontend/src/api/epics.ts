import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Epic, EpicCreate, EpicUpdate, Task, PaginatedResponse } from "@/types/models"

export function useEpics(filters?: { status?: string; tags?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.status) params.set("status", filters.status)
  if (filters?.tags) params.set("tags", filters.tags)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({ queryKey: ["epics", filters], queryFn: () => apiFetch<PaginatedResponse<Epic>>(`/epics${qs ? `?${qs}` : ""}`) })
}

export function useEpic(id: string) {
  return useQuery({ queryKey: ["epics", id], queryFn: () => apiFetch<Epic>(`/epics/${id}/`), enabled: !!id })
}

export function useEpicTasks(epicId: string, filters?: { limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({ queryKey: ["epics", epicId, "tasks", filters], queryFn: () => apiFetch<PaginatedResponse<Task>>(`/epics/${epicId}/tasks/${qs ? `?${qs}` : ""}`), enabled: !!epicId })
}

export function useCreateEpic() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: EpicCreate) => apiFetch<Epic>("/epics/", { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["epics"] }) })
}

export function useUpdateEpic() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ({ id, ...data }: EpicUpdate & { id: string }) => apiFetch<Epic>(`/epics/${id}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["epics"] }) })
}

export function useDeleteEpic() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => apiFetch<void>(`/epics/${id}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["epics"] }) })
}

export function useBatchDeleteEpics() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (epic_ids: string[]) => apiFetch<void>("/epics/batch-delete/", { method: "POST", body: JSON.stringify({ epic_ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["epics"] }),
  })
}
