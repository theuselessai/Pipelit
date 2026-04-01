import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Provider, FetchedModel, ProviderModel } from "@/types/models"

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => apiFetch<Provider[]>("/providers/"),
  })
}

export function useCreateProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { provider: string; provider_type: string; api_key: string; base_url: string }) =>
      apiFetch<void>("/providers/", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  })
}

export function useDeleteProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (provider: string) =>
      apiFetch<void>(`/providers/${provider}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  })
}

export function useFetchProviderModels(provider: string) {
  return useQuery({
    queryKey: ["provider-models", provider],
    queryFn: () => apiFetch<FetchedModel[]>(`/providers/${provider}/fetch-models/`),
    enabled: false, // only fetch on demand
  })
}

export function useProviderModels(provider: string) {
  return useQuery({
    queryKey: ["provider-configured-models", provider],
    queryFn: () => apiFetch<ProviderModel[]>(`/providers/${provider}/models/`),
    enabled: !!provider,
  })
}

export function useAddModels() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, models }: { provider: string; models: { slug: string; model_name: string }[] }) =>
      apiFetch<void>(`/providers/${provider}/models/`, { method: "POST", body: JSON.stringify({ models }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  })
}

export function useDeleteModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, modelSlug }: { provider: string; modelSlug: string }) =>
      apiFetch<void>(`/providers/${provider}/models/${modelSlug}/`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  })
}
