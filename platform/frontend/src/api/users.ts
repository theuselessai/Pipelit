import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { AgentUser } from "@/types/models"

export function useAgentUsers() {
  return useQuery({
    queryKey: ["agent-users"],
    queryFn: () => apiFetch<AgentUser[]>("/users/agents/"),
  })
}

export function useDeleteAgentUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/users/agents/${id}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-users"] }),
  })
}
