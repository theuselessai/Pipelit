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

export interface ExecutionEvent {
  type: string
  execution_id: string
  timestamp: number
  data?: Record<string, unknown>
}

/**
 * Connect to the execution WebSocket and return the final output.
 * Resolves when execution_completed arrives, rejects on execution_failed.
 */
export function waitForExecution(executionId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/executions/${executionId}/`)

    const timeout = setTimeout(() => {
      ws.close()
      reject(new Error("Execution timed out"))
    }, 120_000)

    ws.onmessage = (event) => {
      try {
        const msg: ExecutionEvent = JSON.parse(event.data)
        if (msg.type === "execution_completed") {
          clearTimeout(timeout)
          ws.close()
          const output = msg.data?.output as Record<string, unknown> | undefined
          if (output) {
            const text =
              (output.message as string) ||
              (output.output as string) ||
              (output.node_outputs ? formatNodeOutputs(output.node_outputs as Record<string, unknown>) : null) ||
              JSON.stringify(output)
            resolve(text)
          } else {
            resolve("(completed with no output)")
          }
        } else if (msg.type === "execution_failed") {
          clearTimeout(timeout)
          ws.close()
          reject(new Error((msg.data?.error as string) || "Execution failed"))
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onerror = () => {
      clearTimeout(timeout)
      reject(new Error("WebSocket connection error"))
    }

    ws.onclose = (event) => {
      if (!event.wasClean) {
        clearTimeout(timeout)
        // Don't reject if already resolved
      }
    }
  })
}

function formatNodeOutputs(outputs: Record<string, unknown>): string {
  return Object.entries(outputs)
    .map(([_nodeId, value]) => `${String(value)}`)
    .join("\n\n")
}
