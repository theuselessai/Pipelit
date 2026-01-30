import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Credential, CredentialCreate, CredentialUpdate, LLMProvider, LLMModel } from "@/types/models"

export function useCredentials() {
  return useQuery({ queryKey: ["credentials"], queryFn: () => apiFetch<Credential[]>("/credentials/") })
}

export function useCreateCredential() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (data: CredentialCreate) => apiFetch<Credential>("/credentials/", { method: "POST", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }) })
}

export function useUpdateCredential() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ({ id, data }: { id: number; data: CredentialUpdate }) => apiFetch<Credential>(`/credentials/${id}/`, { method: "PATCH", body: JSON.stringify(data) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }) })
}

export function useDeleteCredential() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: number) => apiFetch<void>(`/credentials/${id}/`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }) })
}

export function useLLMProviders() {
  return useQuery({ queryKey: ["llm-providers"], queryFn: () => apiFetch<LLMProvider[]>("/credentials/llm-providers/") })
}

export function useLLMModels(providerId?: number) {
  const qs = providerId ? `?provider_id=${providerId}` : ""
  return useQuery({ queryKey: ["llm-models", providerId], queryFn: () => apiFetch<LLMModel[]>(`/credentials/llm-models/${qs}`) })
}
