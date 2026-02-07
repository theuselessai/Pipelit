import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { AgentUser, PaginatedResponse } from "@/types/models"

export function useAgentUsers(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", params.limit.toString())
  if (params?.offset) qs.set("offset", params.offset.toString())
  const q = qs.toString()
  return useQuery({
    queryKey: ["agent-users", params],
    queryFn: () => apiFetch<PaginatedResponse<AgentUser>>(`/users/agents/${q ? `?${q}` : ""}`),
  })
}

export function useDeleteAgentUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/users/agents/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-users"] }),
  })
}

export function useBatchDeleteAgentUsers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: number[]) => apiFetch<void>("/users/agents/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-users"] }),
  })
}
