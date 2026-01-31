import { useMutation } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { ChatResponse } from "@/types/models"

export function useSendChatMessage(slug: string) {
  return useMutation({
    mutationFn: (text: string) =>
      apiFetch<ChatResponse>(`/workflows/${slug}/chat/`, {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
  })
}
