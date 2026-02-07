import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Credential, CredentialCreate, CredentialUpdate, CredentialTestResult, CredentialModel, PaginatedResponse } from "@/types/models"

export function useCredentials(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", params.limit.toString())
  if (params?.offset) qs.set("offset", params.offset.toString())
  const q = qs.toString()
  return useQuery({ queryKey: ["credentials", params], queryFn: () => apiFetch<PaginatedResponse<Credential>>(`/credentials/${q ? `?${q}` : ""}`) })
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

export function useTestCredential() {
  return useMutation({ mutationFn: (id: number) => apiFetch<CredentialTestResult>(`/credentials/${id}/test/`, { method: "POST" }) })
}

export function useCredentialModels(credentialId: number | undefined) {
  return useQuery({
    queryKey: ["credential-models", credentialId],
    queryFn: () => apiFetch<CredentialModel[]>(`/credentials/${credentialId}/models/`),
    enabled: !!credentialId,
  })
}

export function useBatchDeleteCredentials() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: number[]) => apiFetch<void>("/credentials/batch-delete/", { method: "POST", body: JSON.stringify({ ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }),
  })
}
