import type { QueryClient } from "@tanstack/react-query"
import type { WorkflowDetail, WorkflowNode, WorkflowEdge, Epic } from "@/types/models"

interface WsMessage {
  type: string
  channel?: string
  execution_id?: string
  timestamp?: number
  data?: Record<string, unknown>
}

type Handler = (msg: WsMessage) => void

class WebSocketManager {
  private ws: WebSocket | null = null
  private token: string | null = null
  private queryClient: QueryClient | null = null
  private subscriptions = new Set<string>()
  private handlers = new Map<string, Handler>()
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private inactivityTimer: ReturnType<typeof setTimeout> | null = null
  private closing = false

  connect(token: string, queryClient: QueryClient) {
    this.token = token
    this.queryClient = queryClient
    this.closing = false
    this._open()
  }

  disconnect() {
    this.closing = true
    this._clearTimers()
    if (this.ws) {
      this.ws.close(1000, "Client disconnect")
      this.ws = null
    }
  }

  subscribe(channel: string) {
    this.subscriptions.add(channel)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "subscribe", channel }))
    }
  }

  unsubscribe(channel: string) {
    this.subscriptions.delete(channel)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "unsubscribe", channel }))
    }
  }

  registerHandler(id: string, fn: Handler) {
    this.handlers.set(id, fn)
  }

  unregisterHandler(id: string) {
    this.handlers.delete(id)
  }

  private _open() {
    if (this.closing || !this.token) return
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/?token=${this.token}`)

    this.ws.onopen = () => {
      this.reconnectAttempt = 0
      // Resubscribe to all channels
      for (const ch of this.subscriptions) {
        this.ws!.send(JSON.stringify({ type: "subscribe", channel: ch }))
      }
      this._resetInactivityTimer()
    }

    this.ws.onmessage = (event) => {
      this._resetInactivityTimer()
      try {
        const msg: WsMessage = JSON.parse(event.data)
        if (msg.type === "ping") {
          this.ws?.send(JSON.stringify({ type: "pong" }))
          return
        }
        if (msg.type === "subscribed" || msg.type === "unsubscribed") return
        this._dispatch(msg)
      } catch { /* ignore parse errors */ }
    }

    this.ws.onclose = () => {
      this.ws = null
      if (!this.closing) this._scheduleReconnect()
    }

    this.ws.onerror = () => {
      // onclose will fire after this
    }
  }

  private _dispatch(msg: WsMessage) {
    const qc = this.queryClient
    if (!qc) return

    // Call registered ad-hoc handlers
    for (const handler of this.handlers.values()) {
      try { handler(msg) } catch { /* ignore */ }
    }

    const channel = msg.channel || ""
    const slugMatch = channel.match(/^workflow:(.+)$/)
    const slug = slugMatch?.[1]

    switch (msg.type) {
      case "node_created": {
        if (!slug || !msg.data) break
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, nodes: [...old.nodes, msg.data as unknown as WorkflowNode] }
        })
        break
      }
      case "node_updated": {
        if (!slug || !msg.data) break
        const updated = msg.data as unknown as WorkflowNode
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, nodes: old.nodes.map((n) => n.node_id === updated.node_id ? updated : n) }
        })
        break
      }
      case "node_deleted": {
        if (!slug || !msg.data) break
        const deletedId = msg.data.node_id as string
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, nodes: old.nodes.filter((n) => n.node_id !== deletedId) }
        })
        break
      }
      case "edge_created": {
        if (!slug || !msg.data) break
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, edges: [...old.edges, msg.data as unknown as WorkflowEdge] }
        })
        break
      }
      case "edge_updated": {
        if (!slug || !msg.data) break
        const updatedEdge = msg.data as unknown as WorkflowEdge
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, edges: old.edges.map((e) => e.id === updatedEdge.id ? updatedEdge : e) }
        })
        break
      }
      case "edge_deleted": {
        if (!slug || !msg.data) break
        const deletedEdgeId = msg.data.id as number
        qc.setQueryData<WorkflowDetail>(["workflows", slug], (old) => {
          if (!old) return old
          return { ...old, edges: old.edges.filter((e) => e.id !== deletedEdgeId) }
        })
        break
      }
      case "node_status": {
        // Node status updates dispatched to handlers only (no query cache update needed)
        break
      }
      case "execution_completed":
      case "execution_failed":
      case "execution_interrupted": {
        const execId = msg.execution_id
        if (execId) {
          qc.invalidateQueries({ queryKey: ["executions", execId] })
          qc.invalidateQueries({ queryKey: ["executions"] })
        }
        break
      }
      case "epic_updated": {
        const epicMatch = channel.match(/^epic:(.+)$/)
        if (epicMatch?.[1] && msg.data) {
          qc.setQueryData<Epic>(["epics", epicMatch[1]], msg.data as unknown as Epic)
          qc.invalidateQueries({ queryKey: ["epics"] })
        }
        break
      }
      case "epic_deleted": {
        qc.invalidateQueries({ queryKey: ["epics"] })
        break
      }
      case "task_created":
      case "task_updated":
      case "task_deleted":
      case "tasks_deleted": {
        const epicMatch = channel.match(/^epic:(.+)$/)
        const epicId = epicMatch?.[1]
        if (epicId) {
          qc.invalidateQueries({ queryKey: ["epics", epicId, "tasks"] })
          qc.invalidateQueries({ queryKey: ["epics", epicId] })
          qc.invalidateQueries({ queryKey: ["epics"] })
          qc.invalidateQueries({ queryKey: ["tasks"] })
        }
        break
      }
    }
  }

  private _scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, 30000)
    this.reconnectAttempt++
    this.reconnectTimer = setTimeout(() => this._open(), delay)
  }

  private _resetInactivityTimer() {
    if (this.inactivityTimer) clearTimeout(this.inactivityTimer)
    this.inactivityTimer = setTimeout(() => {
      // No messages for 45s — assume dead, reconnect
      if (this.ws) {
        this.ws.close()
        this.ws = null
      }
      if (!this.closing) this._scheduleReconnect()
    }, 45_000)
  }

  private _clearTimers() {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.inactivityTimer) { clearTimeout(this.inactivityTimer); this.inactivityTimer = null }
  }
}

export const wsManager = new WebSocketManager()
