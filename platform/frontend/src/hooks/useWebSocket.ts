import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { wsManager } from "@/lib/wsManager"

/**
 * Connect the global WebSocket on mount, disconnect on unmount.
 * Should be called once inside the authenticated layout.
 */
export function useWebSocket() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const token = localStorage.getItem("auth_token")
    if (!token) return

    wsManager.connect(token, queryClient)
    return () => wsManager.disconnect()
  }, [queryClient])
}

/**
 * Subscribe to a channel while the component is mounted.
 */
export function useSubscription(channel: string | null) {
  useEffect(() => {
    if (!channel) return
    wsManager.subscribe(channel)
    return () => wsManager.unsubscribe(channel)
  }, [channel])
}
