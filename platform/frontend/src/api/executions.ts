import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Execution, ExecutionDetail, PaginatedResponse } from "@/types/models"

export function useExecutions(filters?: { workflow_slug?: string; status?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.workflow_slug) params.set("workflow_slug", filters.workflow_slug)
  if (filters?.status) params.set("status", filters.status)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({ queryKey: ["executions", filters], queryFn: () => apiFetch<PaginatedResponse<Execution>>(`/executions/${qs ? `?${qs}` : ""}`) })
}

export function useExecution(id: string) {
  return useQuery({ queryKey: ["executions", id], queryFn: () => apiFetch<ExecutionDetail>(`/executions/${id}/`), enabled: !!id })
}

export function useCancelExecution() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => apiFetch<void>(`/executions/${id}/cancel/`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }) })
}

export function useValidateWorkflow(slug: string) {
  return useMutation({ mutationFn: () => apiFetch<{ valid: boolean; errors: string[] }>(`/workflows/${slug}/validate/`, { method: "POST" }) })
}

export function useBatchDeleteExecutions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (execution_ids: string[]) => apiFetch<void>("/executions/batch-delete/", { method: "POST", body: JSON.stringify({ execution_ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  })
}

export function useManualExecute(slug: string, triggerNodeId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text?: string) =>
      apiFetch<{ execution_id: string; status: string }>(`/workflows/${slug}/execute/`, {
        method: "POST",
        body: JSON.stringify({ text: text ?? "", trigger_node_id: triggerNodeId }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  })
}
