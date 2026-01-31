import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { Credential, CredentialCreate, CredentialUpdate, CredentialTestResult, CredentialModel } from "@/types/models"

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
