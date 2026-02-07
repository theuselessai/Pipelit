import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { MemoryFact, MemoryEpisode, MemoryProcedure, MemoryUser, Checkpoint, PaginatedResponse } from "@/types/models"

export function useMemoryFacts(filters?: { scope?: string; fact_type?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.scope) params.set("scope", filters.scope)
  if (filters?.fact_type) params.set("fact_type", filters.fact_type)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-facts", filters],
    queryFn: () => apiFetch<PaginatedResponse<MemoryFact>>(`/memories/facts/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryEpisodes(filters?: { agent_id?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set("agent_id", filters.agent_id)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-episodes", filters],
    queryFn: () => apiFetch<PaginatedResponse<MemoryEpisode>>(`/memories/episodes/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryProcedures(filters?: { agent_id?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set("agent_id", filters.agent_id)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-procedures", filters],
    queryFn: () => apiFetch<PaginatedResponse<MemoryProcedure>>(`/memories/procedures/${qs ? `?${qs}` : ""}`),
  })
}

export function useMemoryUsers(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", params.limit.toString())
  if (params?.offset) qs.set("offset", params.offset.toString())
  const q = qs.toString()
  return useQuery({
    queryKey: ["memory-users", params],
    queryFn: () => apiFetch<PaginatedResponse<MemoryUser>>(`/memories/users/${q ? `?${q}` : ""}`),
  })
}

export function useMemoryCheckpoints(filters?: { thread_id?: string; limit?: number; offset?: number }) {
  const params = new URLSearchParams()
  if (filters?.thread_id) params.set("thread_id", filters.thread_id)
  if (filters?.limit) params.set("limit", filters.limit.toString())
  if (filters?.offset) params.set("offset", filters.offset.toString())
  const qs = params.toString()
  return useQuery({
    queryKey: ["memory-checkpoints", filters],
    queryFn: () => apiFetch<PaginatedResponse<Checkpoint>>(`/memories/checkpoints/${qs ? `?${qs}` : ""}`),
  })
}

// Batch delete hooks
export function useBatchDeleteFacts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => apiFetch<void>("/memories/facts/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-facts"] }),
  })
}

export function useBatchDeleteEpisodes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => apiFetch<void>("/memories/episodes/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-episodes"] }),
  })
}

export function useBatchDeleteProcedures() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => apiFetch<void>("/memories/procedures/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-procedures"] }),
  })
}

export function useBatchDeleteMemoryUsers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => apiFetch<void>("/memories/users/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-users"] }),
  })
}

export function useBatchDeleteCheckpoints() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { thread_ids?: string[]; checkpoint_ids?: string[] }) => apiFetch<void>("/memories/checkpoints/batch-delete/", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory-checkpoints"] }),
  })
}
