import { useMutation } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { WorkflowNode, NodeCreate, NodeUpdate } from "@/types/models"

export function useCreateNode(slug: string) {
  return useMutation({ mutationFn: (data: NodeCreate) => apiFetch<WorkflowNode>(`/workflows/${slug}/nodes/`, { method: "POST", body: JSON.stringify(data) }) })
}

export function useUpdateNode(slug: string) {
  return useMutation({ mutationFn: ({ nodeId, data }: { nodeId: string; data: NodeUpdate }) => apiFetch<WorkflowNode>(`/workflows/${slug}/nodes/${nodeId}/`, { method: "PATCH", body: JSON.stringify(data) }) })
}

export function useDeleteNode(slug: string) {
  return useMutation({ mutationFn: (nodeId: string) => apiFetch<void>(`/workflows/${slug}/nodes/${nodeId}/`, { method: "DELETE" }) })
}
