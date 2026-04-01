import { useQuery } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { AvailableModel } from "@/types/models"

export function useAvailableModels() {
  return useQuery({
    queryKey: ["available-models"],
    queryFn: () => apiFetch<AvailableModel[]>("/available-models/"),
  })
}
