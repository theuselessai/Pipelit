import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Workflow, WorkflowDetail, WorkflowCreate, WorkflowUpdate } from "@/types/models"
import type { NodeTypeSpec } from "@/types/nodeIO"

export function useWorkflows() {
  return useQuery({ queryKey: ["workflows"], queryFn: () => apiFetch<Workflow[]>("/workflows/") })
}

export function useWorkflow(slug: string) {
  return useQuery({ queryKey: ["workflows", slug], queryFn: () => apiFetch<WorkflowDetail>(`/workflows/${slug}/`), enabled: !!slug })
}

export function useCreateWorkflow() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: WorkflowCreate) => apiFetch<Workflow>("/workflows/", { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }) })
}

export function useUpdateWorkflow(slug: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: WorkflowUpdate) => apiFetch<Workflow>(`/workflows/${slug}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["workflows"] }); qc.invalidateQueries({ queryKey: ["workflows", slug] }) } })
}

export function useNodeTypes() {
  return useQuery({ queryKey: ["node-types"], queryFn: () => apiFetch<Record<string, NodeTypeSpec>>("/workflows/node-types/"), staleTime: Infinity })
}

export function useDeleteWorkflow() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (slug: string) => apiFetch<void>(`/workflows/${slug}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }) })
}
