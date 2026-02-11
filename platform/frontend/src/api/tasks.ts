import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Task, TaskCreate, TaskUpdate, PaginatedResponse } from "@/types/models"

export function useTasks(filters?: { epic_id?: string; status?: string; tags?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.epic_id) params.set("epic_id", filters.epic_id)
  if (filters?.status) params.set("status", filters.status)
  if (filters?.tags) params.set("tags", filters.tags)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({ queryKey: ["tasks", filters], queryFn: () => apiFetch<PaginatedResponse<Task>>(`/tasks/${qs ? `?${qs}` : ""}`) })
}

export function useTask(id: string) {
  return useQuery({ queryKey: ["tasks", id], queryFn: () => apiFetch<Task>(`/tasks/${id}/`), enabled: !!id })
}

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) => apiFetch<Task>("/tasks/", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); qc.invalidateQueries({ queryKey: ["epics"] }) },
  })
}

export function useUpdateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: TaskUpdate & { id: string }) => apiFetch<Task>(`/tasks/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); qc.invalidateQueries({ queryKey: ["epics"] }) },
  })
}

export function useDeleteTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/tasks/${id}/`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); qc.invalidateQueries({ queryKey: ["epics"] }) },
  })
}

export function useBatchDeleteTasks() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (task_ids: string[]) => apiFetch<void>("/tasks/batch-delete/", { method: "POST", body: JSON.stringify({ task_ids }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); qc.invalidateQueries({ queryKey: ["epics"] }) },
  })
}
