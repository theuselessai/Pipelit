import { useMutation } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { WorkflowEdge, EdgeCreate, EdgeUpdate } from "@/types/models"

export function useCreateEdge(slug: string) {
  return useMutation({ mutationFn: (data: EdgeCreate) => apiFetch<WorkflowEdge>(`/workflows/${slug}/edges/`, { method: "POST", body: JSON.stringify(data) }) })
}

export function useUpdateEdge(slug: string) {
  return useMutation({ mutationFn: ({ edgeId, data }: { edgeId: number; data: EdgeUpdate }) => apiFetch<WorkflowEdge>(`/workflows/${slug}/edges/${edgeId}/`, { method: "PATCH", body: JSON.stringify(data) }) })
}

export function useDeleteEdge(slug: string) {
  return useMutation({ mutationFn: (edgeId: number) => apiFetch<void>(`/workflows/${slug}/edges/${edgeId}/`, { method: "DELETE" }) })
}
