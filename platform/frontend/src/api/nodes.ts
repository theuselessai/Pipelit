import { useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { WorkflowNode, NodeCreate, NodeUpdate } from "@/types/models"

export function useCreateNode(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: NodeCreate) => apiFetch<WorkflowNode>(`/workflows/${slug}/nodes/`, { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useUpdateNode(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ({ nodeId, data }: { nodeId: string; data: NodeUpdate }) => apiFetch<WorkflowNode>(`/workflows/${slug}/nodes/${nodeId}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}

export function useDeleteNode(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (nodeId: string) => apiFetch<void>(`/workflows/${slug}/nodes/${nodeId}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows", slug] }) })
}
