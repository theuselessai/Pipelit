import { useMutation, useQuery } from "@tanstack/react-query"
import { apiFetch } from "./client"
import type { ChatMessage, ChatResponse } from "@/types/models"

export interface ChatHistoryResponse {
  messages: ChatMessage[]
  thread_id: string
  has_more: boolean
}

export interface ChatHistoryParams {
  limit?: number
  before?: string
}

export function useChatHistory(slug: string, params?: ChatHistoryParams) {
  const queryParams = new URLSearchParams()
  if (params?.limit) queryParams.set("limit", params.limit.toString())
  if (params?.before) queryParams.set("before", params.before)
  const queryString = queryParams.toString()

  return useQuery({
    queryKey: ["chat-history", slug, params?.limit, params?.before],
    queryFn: () => apiFetch<ChatHistoryResponse>(
      `/workflows/${slug}/chat/history${queryString ? `?${queryString}` : ""}`
    ),
  })
}

export function useSendChatMessage(slug: string, triggerNodeId?: string) {
  return useMutation({
    mutationFn: (text: string) =>
      apiFetch<ChatResponse>(`/workflows/${slug}/chat/`, {
        method: "POST",
        body: JSON.stringify({ text, trigger_node_id: triggerNodeId }),
      }),
  })
}

