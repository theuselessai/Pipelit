import { useQuery } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { MemoryFact, MemoryEpisode, MemoryProcedure, MemoryUser } from "@/types/models"

export function useMemoryFacts(filters?: { scope?: string; fact_type?: string }) {
  const params = new URLSearchParams()
  if (filters?.scope) params.set("scope", filters.scope)
  if (filters?.fact_type) params.set("fact_type", filters.fact_type)
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-facts", filters],
    queryFn: () => apiFetch<MemoryFact[]>(`/memories/facts/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryEpisodes(filters?: { agent_id?: string }) {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set("agent_id", filters.agent_id)
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-episodes", filters],
    queryFn: () => apiFetch<MemoryEpisode[]>(`/memories/episodes/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryProcedures(filters?: { agent_id?: string }) {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set("agent_id", filters.agent_id)
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-procedures", filters],
    queryFn: () => apiFetch<MemoryProcedure[]>(`/memories/procedures/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryUsers() {
  return useQuery({
    queryKey: ["memory-users"],
    queryFn: () => apiFetch<MemoryUser[]>("/memories/users/"),
  })
}
