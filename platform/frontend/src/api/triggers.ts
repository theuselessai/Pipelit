import { useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { WorkflowTrigger, TriggerCreate, TriggerUpdate } from "@/types/models"

export function useCreateTrigger(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: TriggerCreate) => apiFetch<WorkflowTrigger>(`/workflows/${slug}/triggers/`, { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useUpdateTrigger(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ({ triggerId, data }: { triggerId: number; data: TriggerUpdate }) => apiFetch<WorkflowTrigger>(`/workflows/${slug}/triggers/${triggerId}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useDeleteTrigger(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (triggerId: number) => apiFetch<void>(`/workflows/${slug}/triggers/${triggerId}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}
