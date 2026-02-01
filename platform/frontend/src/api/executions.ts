import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Execution, ExecutionDetail } from "@/types/models"

export function useExecutions(filters?: { workflow_slug?: string; status?: string }) {
  const params = new URLSearchParams()
  if (filters?.workflow_slug) params.set("workflow_slug", filters.workflow_slug)
  if (filters?.status) params.set("status", filters.status)
  const qs = params.toString()
  return useQuery({ queryKey: ["executions", filters], queryFn: () => apiFetch<Execution[]>(`/executions/${qs ? `?${qs}` : ""}`) })
}

export function useExecution(id: string) {
  return useQuery({ queryKey: ["executions", id], queryFn: () => apiFetch<ExecutionDetail>(`/executions/${id}/`), enabled: !!id })
}

export function useCancelExecution() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => apiFetch<void>(`/executions/${id}/cancel/`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }) })
}
