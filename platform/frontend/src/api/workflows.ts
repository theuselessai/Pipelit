import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Workflow, WorkflowDetail, WorkflowCreate, WorkflowUpdate, PaginatedResponse } from "@/types/models"
import type { NodeTypeSpec } from "@/types/nodeIO"

export function useWorkflows(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", params.limit.toString())
  if (params?.offset) qs.set("offset", params.offset.toString())
  const q = qs.toString()
  return useQuery({ queryKey: ["workflows", params], queryFn: () => apiFetch<PaginatedResponse<Workflow>>(`/workflows/${q ? `?${q}` : ""}`) })
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

export function useBatchDeleteWorkflows() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slugs: string[]) => apiFetch<void>("/workflows/batch-delete/", { method: "POST", body: JSON.stringify({ slugs }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  })
}
