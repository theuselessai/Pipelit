import { useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { WorkflowEdge, EdgeCreate, EdgeUpdate } from "@/types/models"

export function useCreateEdge(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: EdgeCreate) => apiFetch<WorkflowEdge>(`/workflows/${slug}/edges/`, { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useUpdateEdge(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ({ edgeId, data }: { edgeId: number; data: EdgeUpdate }) => apiFetch<WorkflowEdge>(`/workflows/${slug}/edges/${edgeId}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useDeleteEdge(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (edgeId: number) => apiFetch<void>(`/workflows/${slug}/edges/${edgeId}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}
