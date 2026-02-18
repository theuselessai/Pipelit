import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useUpdateNode, useDeleteNode, useScheduleStart, useSchedulePause, useScheduleStop } from "@/api/nodes"
import { useWorkflows } from "@/api/workflows"
import { useCredentials, useCredentialModels } from "@/api/credentials"
import { useSendChatMessage, useChatHistory, useDeleteChatHistory } from "@/api/chat"
import { useManualExecute } from "@/api/executions"
import { wsManager } from "@/lib/wsManager"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Calendar } from "@/components/ui/calendar"
import { X, Trash2, Send, Loader2, Expand, ExternalLink, RotateCcw, CalendarIcon, Plus, Play, Pause, Square, ChevronDown, ChevronUp } from "lucide-react"
import { format } from "date-fns"
import ExpressionTextarea from "@/components/ExpressionTextarea"
import CodeMirrorExpressionEditor from "@/components/CodeMirrorExpressionEditor"
import PopoutWindow from "@/components/PopoutWindow"
import type { CodeMirrorLanguage } from "@/components/CodeMirrorEditor"
import type { WorkflowNode, WorkflowDetail, ChatMessage, SwitchRule, FilterRule, ScheduleJobInfo } from "@/types/models"
import type { ActivityStep, ActivityToolStep, ActivitySummary } from "@/types/activity"
import ActivityIndicator from "./ActivityIndicator"

interface Props {
  slug: string
  node: WorkflowNode
  workflow?: WorkflowDetail
  onClose: () => void
}

const TRIGGER_TYPES = ["trigger_telegram", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat"]

const OPERATOR_OPTIONS = [
  { group: "Universal", options: [
    { value: "exists", label: "Exists" },
    { value: "does_not_exist", label: "Does not exist" },
    { value: "is_empty", label: "Is empty" },
    { value: "is_not_empty", label: "Is not empty" },
  ]},
  { group: "String", options: [
    { value: "equals", label: "Equals" },
    { value: "not_equals", label: "Not equals" },
    { value: "contains", label: "Contains" },
    { value: "not_contains", label: "Not contains" },
    { value: "starts_with", label: "Starts with" },
    { value: "not_starts_with", label: "Not starts with" },
    { value: "ends_with", label: "Ends with" },
    { value: "not_ends_with", label: "Not ends with" },
    { value: "matches_regex", label: "Matches regex" },
    { value: "not_matches_regex", label: "Not matches regex" },
  ]},
  { group: "Number", options: [
    { value: "gt", label: "Greater than" },
    { value: "lt", label: "Less than" },
    { value: "gte", label: "Greater or equal" },
    { value: "lte", label: "Less or equal" },
  ]},
  { group: "Datetime", options: [
    { value: "after", label: "After" },
    { value: "before", label: "Before" },
    { value: "after_or_equal", label: "After or equal" },
    { value: "before_or_equal", label: "Before or equal" },
  ]},
  { group: "Boolean", options: [
    { value: "is_true", label: "Is true" },
    { value: "is_false", label: "Is false" },
  ]},
  { group: "Array", options: [
    { value: "length_eq", label: "Length equals" },
    { value: "length_neq", label: "Length not equals" },
    { value: "length_gt", label: "Length greater than" },
    { value: "length_lt", label: "Length less than" },
    { value: "length_gte", label: "Length greater or equal" },
    { value: "length_lte", label: "Length less or equal" },
  ]},
]

const UNARY_OPERATORS = new Set(["exists", "does_not_exist", "is_empty", "is_not_empty", "is_true", "is_false"])

/** Close a popout window and clear its state. Use for Save/Cancel buttons — NOT for onClose (which fires from beforeunload when the popup is already closing). */
function closePopout(popup: Window | null, setter: (w: Window | null) => void) {
  if (popup && !popup.closed) popup.close()
  setter(null)
}

function generateRuleId(): string {
  return "r_" + Math.random().toString(36).slice(2, 8)
}

function formatTimestamp(ts: string | undefined): string {
  if (!ts) return ""
  try {
    const date = new Date(ts)
    if (isNaN(date.getTime())) return ""
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return ""
  }
}

function ChatPanel({ slug, node, onClose }: Props) {
  const sendMessage = useSendChatMessage(slug, node.node_id)
  const deleteChatHistory = useDeleteChatHistory(slug)
  const [beforeDate, setBeforeDate] = useState<Date | undefined>(undefined)
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [chatPopoutWindow, setChatPopoutWindow] = useState<Window | null>(null)

  // Convert date to ISO string for API (end of day)
  const beforeDateISO = beforeDate
    ? (() => {
        const combined = new Date(beforeDate)
        combined.setHours(23, 59, 59)
        return combined.toISOString()
      })()
    : undefined

  const { data: historyData, refetch: refetchHistory } = useChatHistory(slug, {
    limit: 10,
    before: beforeDateISO,
  })
  const baseMessages = useMemo(() => historyData?.messages ?? [], [historyData])
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])
  const messages = useMemo(() => [...baseMessages, ...localMessages], [baseMessages, localMessages])
  const [input, setInput] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [messages])

  const [waiting, setWaiting] = useState(false)
  const pendingExecRef = useRef<string | null>(null)

  // Activity indicator state
  const [activitySteps, setActivitySteps] = useState<ActivityStep[]>([])
  const [activitySummary, setActivitySummary] = useState<ActivitySummary | null>(null)
  const [activityExpanded, setActivityExpanded] = useState(true)

  // Register a global WS handler to listen for execution completion
  useEffect(() => {
    const handlerId = `chat-panel-${node.node_id}`
    wsManager.registerHandler(handlerId, (msg) => {
      if (!pendingExecRef.current) return
      if (msg.execution_id !== pendingExecRef.current) return

      // Handle node_status events for activity tracking
      if (msg.type === "node_status" && msg.data) {
        const d = msg.data
        const nodeId = d.node_id as string
        if (!nodeId) return
        const status = d.status as string
        const isToolCall = d.is_tool_call === true

        if (isToolCall) {
          const parentId = d.parent_node_id as string
          if (!parentId) return
          // Upsert into parent step's tool_steps
          const toolStep: ActivityToolStep = {
            tool_name: (d.tool_name as string) || "",
            tool_node_id: nodeId,
            status: status as ActivityToolStep["status"],
            started_at: Date.now(),
            duration_ms: d.duration_ms as number | undefined,
            error: d.error as string | undefined,
          }
          setActivitySteps((prev) => {
            return prev.map((step) => {
              if (step.node_id !== parentId) return step
              const existing = step.tool_steps.findIndex((ts) => ts.tool_node_id === nodeId)
              if (existing >= 0) {
                const updated = [...step.tool_steps]
                updated[existing] = { ...updated[existing], status: toolStep.status, duration_ms: toolStep.duration_ms, error: toolStep.error }
                return { ...step, tool_steps: updated }
              }
              return { ...step, tool_steps: [...step.tool_steps, toolStep] }
            })
          })
        } else {
          // Upsert into activitySteps
          setActivitySteps((prev) => {
            const idx = prev.findIndex((s) => s.node_id === nodeId)
            if (idx >= 0) {
              const updated = [...prev]
              updated[idx] = {
                ...updated[idx],
                status: status as ActivityStep["status"],
                duration_ms: d.duration_ms as number | undefined,
                error: d.error as string | undefined,
              }
              return updated
            }
            // New step
            return [...prev, {
              node_id: nodeId,
              component_type: (d.component_type as string) || "",
              display_name: (d.display_name as string) || nodeId,
              node_label: (d.node_label as string) || nodeId,
              status: status as ActivityStep["status"],
              started_at: Date.now(),
              duration_ms: d.duration_ms as number | undefined,
              error: d.error as string | undefined,
              tool_steps: [],
            }]
          })
        }
      }

      if (msg.type === "execution_completed") {
        pendingExecRef.current = null
        setWaiting(false)
        // Set activity summary and auto-collapse
        if (msg.data?.activity_summary) {
          setActivitySummary(msg.data.activity_summary as ActivitySummary)
        }
        setActivityExpanded(false)
        const output = msg.data?.output as Record<string, unknown> | undefined
        if (output) {
          const text =
            (output.message as string) ||
            (output.output as string) ||
            (output.node_outputs ? Object.entries(output.node_outputs as Record<string, unknown>).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("\n\n") : null) ||
            JSON.stringify(output)
          setLocalMessages((prev) => [...prev, { role: "assistant", text, timestamp: new Date().toISOString() }])
        } else {
          setLocalMessages((prev) => [...prev, { role: "assistant", text: "(completed with no output)", timestamp: new Date().toISOString() }])
        }
      } else if (msg.type === "execution_failed") {
        pendingExecRef.current = null
        setWaiting(false)
        setActivityExpanded(false)
        setActivitySteps([])
        setActivitySummary(null)
        setLocalMessages((prev) => [...prev, { role: "assistant", text: `Error: ${(msg.data?.error as string) || "Execution failed"}`, timestamp: new Date().toISOString() }])
      }
    })
    return () => wsManager.unregisterHandler(handlerId)
  }, [node.node_id])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || sendMessage.isPending || waiting) return
    setInput("")
    // Reset activity state for new execution
    setActivitySteps([])
    setActivitySummary(null)
    setActivityExpanded(true)
    setLocalMessages((prev) => [...prev, { role: "user", text, timestamp: new Date().toISOString() }])
    sendMessage.mutate(text, {
      onSuccess: (data) => {
        setWaiting(true)
        pendingExecRef.current = data.execution_id
      },
      onError: (err) => {
        setLocalMessages((prev) => [...prev, { role: "assistant", text: `Error: ${err.message}`, timestamp: new Date().toISOString() }])
      },
    })
  }, [input, sendMessage, waiting])

  function handleDeleteHistory() {
    deleteChatHistory.mutate(undefined, {
      onSuccess: () => {
        setLocalMessages([])
        setConfirmDelete(false)
        refetchHistory()
      },
    })
  }

  const handleChatPopout = () => {
    const popup = window.open("", "", "width=900,height=700,left=200,top=100")
    if (!popup) return
    setChatPopoutWindow(popup)
  }

  const handleChatPopoutClose = useCallback(() => {
    setChatPopoutWindow(null)
  }, [])

  const handleChatPopoutCloseButton = useCallback(() => {
    closePopout(chatPopoutWindow, setChatPopoutWindow)
  }, [chatPopoutWindow])

  const chatToolbar = (closeFn: () => void) => (
    <div className="flex items-center gap-2">
      <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" title={beforeDate ? format(beforeDate, "MMM d, yyyy") : "Filter by date"}>
            <CalendarIcon className="h-4 w-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="end">
          <Calendar
            mode="single"
            selected={beforeDate}
            onSelect={(date) => {
              setBeforeDate(date)
              setCalendarOpen(false)
            }}
            initialFocus
          />
        </PopoverContent>
      </Popover>
      {beforeDate && (
        <Button variant="ghost" size="sm" className="h-8 px-2" onClick={() => setBeforeDate(undefined)} title="Clear date filter">
          <X className="h-3 w-3" />
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={() => refetchHistory()} title="Reload history">
        <RotateCcw className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} title="Clear chat history">
        <Trash2 className="h-4 w-4" />
      </Button>
      {!chatPopoutWindow && (
        <Button variant="ghost" size="sm" onClick={handleChatPopout} title="Pop out to window">
          <ExternalLink className="h-4 w-4" />
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={closeFn}>
        <X className="h-4 w-4" />
      </Button>
    </div>
  )

  const chatBody = (
    <>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {historyData?.has_more && (
          <div className="text-xs text-muted-foreground text-center py-2">
            Showing last 10 messages. Use the date picker to view older messages.
          </div>
        )}
        {messages.length === 0 && <div className="text-xs text-muted-foreground text-center py-8">Send a message to test this workflow</div>}
        {messages.map((msg, i) => (
          <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
              {msg.text}
            </div>
            {msg.timestamp && (
              <div className="text-[10px] text-muted-foreground mt-0.5 px-1">
                {formatTimestamp(msg.timestamp)}
              </div>
            )}
          </div>
        ))}
        {activitySteps.length > 0 && (
          <ActivityIndicator
            steps={activitySteps}
            summary={activitySummary}
            expanded={activityExpanded}
            onToggle={() => setActivityExpanded((prev) => !prev)}
          />
        )}
        {(sendMessage.isPending || waiting) && activitySteps.length === 0 && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-lg px-3 py-2"><Loader2 className="h-4 w-4 animate-spin" /></div>
          </div>
        )}
      </div>
      <div className="p-4 border-t flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend() } }}
          placeholder="Type a message..."
          className="text-sm"
          disabled={sendMessage.isPending || waiting}
        />
        <Button size="sm" onClick={handleSend} disabled={sendMessage.isPending || waiting || !input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </>
  )

  const confirmDeleteDialog = (
    <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
      <DialogContent>
        <DialogHeader><DialogTitle>Clear Chat History</DialogTitle></DialogHeader>
        <p>Are you sure you want to clear all chat history for this workflow? This cannot be undone.</p>
        <DialogFooter>
          <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
          <Button variant="destructive" onClick={handleDeleteHistory} disabled={deleteChatHistory.isPending}>
            {deleteChatHistory.isPending ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Clear History
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  if (chatPopoutWindow) {
    return (
      <PopoutWindow popupWindow={chatPopoutWindow} title={`Chat — ${node.node_id}`} onClose={handleChatPopoutClose}>
        <div className="flex flex-col h-screen">
          <div className="p-4 border-b flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">{node.node_id}</h2>
              <div className="text-xs text-muted-foreground mt-1">Chat Trigger</div>
            </div>
            {chatToolbar(handleChatPopoutCloseButton)}
          </div>
          {chatBody}
          {confirmDeleteDialog}
        </div>
      </PopoutWindow>
    )
  }

  return (
    <Dialog open={true} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-[90vw] w-[900px] h-[80vh] flex flex-col p-0" showCloseButton={false}>
        <DialogHeader className="p-4 border-b flex-row items-center justify-between space-y-0">
          <div>
            <DialogTitle>{node.node_id}</DialogTitle>
            <div className="text-xs text-muted-foreground mt-1">Chat Trigger</div>
          </div>
          {chatToolbar(onClose)}
        </DialogHeader>
        {chatBody}
      </DialogContent>
      {confirmDeleteDialog}
    </Dialog>
  )
}

export default function NodeDetailsPanel({ slug, node, workflow, onClose }: Props) {
  if (node.component_type === "trigger_chat") {
    return <ChatPanel slug={slug} node={node} onClose={onClose} />
  }
  return <NodeConfigPanel key={node.node_id} slug={slug} node={node} workflow={workflow} onClose={onClose} />
}

/** Parse a full field path like "node_outputs.cat_1.category" into { sourceNodeId, outputField }. */
function parseFieldPath(field: string): { sourceNodeId: string; outputField: string } {
  if (!field || !field.startsWith("node_outputs.")) return { sourceNodeId: "", outputField: field }
  const rest = field.slice("node_outputs.".length) // "cat_1.category"
  const dotIdx = rest.indexOf(".")
  if (dotIdx === -1) return { sourceNodeId: rest, outputField: "" }
  return { sourceNodeId: rest.slice(0, dotIdx), outputField: rest.slice(dotIdx + 1) }
}

function buildFieldPath(sourceNodeId: string, outputField: string): string {
  if (!sourceNodeId) return outputField
  return `node_outputs.${sourceNodeId}${outputField ? "." + outputField : ""}`
}

function NodeConfigPanel({ slug, node, workflow, onClose }: Props) {
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const { data: credentials } = useCredentials()
  const allCredentials = credentials?.items ?? []
  const llmCredentials = allCredentials.filter((c) => c.credential_type === "llm")

  const [systemPrompt, setSystemPrompt] = useState(node.config.system_prompt)
  const [extraConfig, setExtraConfig] = useState(JSON.stringify(node.config.extra_config, null, 2))
  const [llmCredentialId, setLlmCredentialId] = useState<string>(node.config.llm_credential_id?.toString() ?? "")
  const [modelName, setModelName] = useState(node.config.model_name ?? "")
  const [temperature, setTemperature] = useState<string>(node.config.temperature?.toString() ?? "")
  const [maxTokens, setMaxTokens] = useState<string>(node.config.max_tokens?.toString() ?? "")
  const [topP, setTopP] = useState<string>(node.config.top_p?.toString() ?? "")
  const [frequencyPenalty, setFrequencyPenalty] = useState<string>(node.config.frequency_penalty?.toString() ?? "")
  const [presencePenalty, setPresencePenalty] = useState<string>(node.config.presence_penalty?.toString() ?? "")
  const [interruptBefore, setInterruptBefore] = useState(node.interrupt_before)
  const [interruptAfter, setInterruptAfter] = useState(node.interrupt_after)
  const [conversationMemory, setConversationMemory] = useState<boolean>(Boolean(node.config.extra_config?.conversation_memory))

  // Code editor state
  const [codeSnippet, setCodeSnippet] = useState<string>((node.config.extra_config?.code as string) ?? "")
  const [codeLanguage, setCodeLanguage] = useState<string>((node.config.extra_config?.language as string) ?? "python")
  const [codeModalOpen, setCodeModalOpen] = useState(false)
  const [codeDraft, setCodeDraft] = useState("")

  // Categorizer categories state
  const [categories, setCategories] = useState<{ name: string; description: string }[]>(
    () => (node.config.extra_config?.categories as { name: string; description: string }[]) ?? []
  )

  // Switch rules state
  const [switchRules, setSwitchRules] = useState<SwitchRule[]>(() => (node.config.extra_config?.rules as SwitchRule[]) ?? [])
  const [enableFallback, setEnableFallback] = useState<boolean>(Boolean(node.config.extra_config?.enable_fallback))

  // Wait state
  const [waitDuration, setWaitDuration] = useState<string>((node.config.extra_config?.duration as number)?.toString() ?? "0")
  const [waitUnit, setWaitUnit] = useState<string>((node.config.extra_config?.unit as string) ?? "seconds")

  // Filter state
  const [filterRules, setFilterRules] = useState<FilterRule[]>(() => (node.config.extra_config?.rules as FilterRule[]) ?? [])
  const [filterSourceNode, setFilterSourceNode] = useState<string>((node.config.extra_config?.source_node as string) ?? "")
  const [filterField, setFilterField] = useState<string>((node.config.extra_config?.field as string) ?? "")

  // Merge state
  const [mergeMode, setMergeMode] = useState<string>((node.config.extra_config?.mode as string) ?? "append")

  // Loop state
  const [loopSourceNode, setLoopSourceNode] = useState<string>((node.config.extra_config?.source_node as string) ?? "")
  const [loopField, setLoopField] = useState<string>((node.config.extra_config?.field as string) ?? "")
  const [loopOnError, setLoopOnError] = useState<string>((node.config.extra_config?.on_error as string) ?? "stop")

  // Subworkflow state
  const [subworkflowTarget, setSubworkflowTarget] = useState<string>((node.config.extra_config?.target_workflow as string) ?? "")
  const [subworkflowTriggerMode, setSubworkflowTriggerMode] = useState<string>((node.config.extra_config?.trigger_mode as string) ?? "implicit")
  const { data: workflowList } = useWorkflows({ limit: 200 })

  // Compute all upstream ancestor nodes for switch/filter/loop (BFS backward through data edges)
  const upstreamNodes = useMemo(() => {
    if (!workflow) return []
    const SUB_TYPES = new Set(["ai_model", "run_command", "http_request", "web_search", "calculator", "datetime", "output_parser", "memory_read", "memory_write", "code_execute", "create_agent_user", "platform_api", "whoami", "epic_tools", "task_tools", "spawn_and_await"])
    const visited = new Set<string>()
    const queue = [node.node_id]
    while (queue.length > 0) {
      const current = queue.shift()!
      for (const e of workflow.edges) {
        if (e.target_node_id === current && !e.edge_label && !visited.has(e.source_node_id)) {
          visited.add(e.source_node_id)
          queue.push(e.source_node_id)
        }
      }
    }
    const nodeMap = new Map(workflow.nodes.map((n) => [n.node_id, n]))
    return Array.from(visited).filter((nid) => {
      const n = nodeMap.get(nid)
      return n && !n.component_type.startsWith("trigger_") && !SUB_TYPES.has(n.component_type)
    })
  }, [workflow, node.node_id])

  // System prompt modal state
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState("")
  const [promptLanguage, setPromptLanguage] = useState<CodeMirrorLanguage>("markdown")
  const [promptPopoutWindow, setPromptPopoutWindow] = useState<Window | null>(null)

  // Extra config modal state
  const [extraConfigModalOpen, setExtraConfigModalOpen] = useState(false)
  const [extraConfigDraft, setExtraConfigDraft] = useState("")
  const [extraConfigPopoutWindow, setExtraConfigPopoutWindow] = useState<Window | null>(null)

  // Code popout state
  const [codePopoutWindow, setCodePopoutWindow] = useState<Window | null>(null)

  // Trigger fields
  const [triggerCredentialId, setTriggerCredentialId] = useState<string>(node.config.credential_id?.toString() ?? "")
  const [triggerIsActive, setTriggerIsActive] = useState(node.config.is_active ?? true)
  const [triggerPriority, setTriggerPriority] = useState<string>(node.config.priority?.toString() ?? "0")
  const [triggerConfig, setTriggerConfig] = useState(JSON.stringify(node.config.trigger_config ?? {}, null, 2))

  // Schedule trigger state
  const [schedInterval, setSchedInterval] = useState<string>((node.config.extra_config?.interval_seconds as number)?.toString() ?? "300")
  const [schedRepeats, setSchedRepeats] = useState<string>((node.config.extra_config?.total_repeats as number)?.toString() ?? "0")
  const [schedRetries, setSchedRetries] = useState<string>((node.config.extra_config?.max_retries as number)?.toString() ?? "3")
  const [schedTimeout, setSchedTimeout] = useState<string>((node.config.extra_config?.timeout_seconds as number)?.toString() ?? "600")
  const [schedPayload, setSchedPayload] = useState<string>(
    node.config.extra_config?.trigger_payload ? JSON.stringify(node.config.extra_config.trigger_payload, null, 2) : "{}"
  )
  const [schedErrorExpanded, setSchedErrorExpanded] = useState(false)
  const scheduleStart = useScheduleStart(slug)
  const schedulePause = useSchedulePause(slug)
  const scheduleStop = useScheduleStop(slug)
  const [schedJob, setSchedJob] = useState<ScheduleJobInfo | null>(node.schedule_job ?? null)
  const queryClient = useQueryClient()

  // Sync schedJob when node prop updates (e.g. via WS node_updated)
  useEffect(() => {
    setSchedJob(node.schedule_job ?? null)
  }, [node.schedule_job])

  // Refresh schedule data when executions complete
  useEffect(() => {
    if (node.component_type !== "trigger_schedule") return
    const handlerId = `schedule-panel-${node.node_id}`
    wsManager.registerHandler(handlerId, (msg) => {
      if (msg.type === "execution_completed" || msg.type === "execution_failed") {
        queryClient.invalidateQueries({ queryKey: ["workflows", slug] })
      }
    })
    return () => wsManager.unregisterHandler(handlerId)
  }, [node.node_id, slug, queryClient])

  const manualExecute = useManualExecute(slug, node.node_id)

  const credId = llmCredentialId ? Number(llmCredentialId) : undefined
  const { data: availableModels } = useCredentialModels(credId)

  const isLLMNode = node.component_type === "ai_model"
  const isAgentNode = node.component_type === "agent"
  const hasSystemPrompt = ["agent", "categorizer", "router"].includes(node.component_type)
  const isTriggerNode = TRIGGER_TYPES.includes(node.component_type)

  function handleSave() {
    let parsedExtra: Record<string, unknown> = {}
    try { parsedExtra = JSON.parse(extraConfig) } catch { /* keep empty */ }
    if (isAgentNode) {
      parsedExtra = { ...parsedExtra, conversation_memory: conversationMemory }
    }
    if (node.component_type === "code") {
      parsedExtra = { ...parsedExtra, code: codeSnippet, language: codeLanguage }
    }
    if (node.component_type === "categorizer") {
      parsedExtra = { ...parsedExtra, categories }
    }
    if (node.component_type === "switch") {
      parsedExtra = { ...parsedExtra, rules: switchRules, enable_fallback: enableFallback }
      delete parsedExtra.condition_field
      delete parsedExtra.condition_expression
    }
    if (node.component_type === "wait") {
      parsedExtra = { ...parsedExtra, duration: Number(waitDuration) || 0, unit: waitUnit }
    }
    if (node.component_type === "filter") {
      parsedExtra = { ...parsedExtra, rules: filterRules, source_node: filterSourceNode || undefined, field: filterField || undefined }
    }
    if (node.component_type === "merge") {
      parsedExtra = { ...parsedExtra, mode: mergeMode }
    }
    if (node.component_type === "loop") {
      parsedExtra = { ...parsedExtra, source_node: loopSourceNode || undefined, field: loopField || undefined, on_error: loopOnError }
    }
    if (node.component_type === "workflow") {
      parsedExtra = { ...parsedExtra, target_workflow: subworkflowTarget || undefined, trigger_mode: subworkflowTriggerMode }
    }
    if (node.component_type === "trigger_schedule") {
      let parsedPayload = {}
      try { parsedPayload = JSON.parse(schedPayload) } catch { /* keep empty */ }
      parsedExtra = {
        ...parsedExtra,
        interval_seconds: Number(schedInterval) || 300,
        total_repeats: Number(schedRepeats) || 0,
        max_retries: Number(schedRetries) || 3,
        timeout_seconds: Number(schedTimeout) || 600,
        trigger_payload: parsedPayload,
      }
    }
    let parsedTriggerConfig = {}
    try { parsedTriggerConfig = JSON.parse(triggerConfig) } catch { /* keep empty */ }
    updateNode.mutate({
      nodeId: node.node_id,
      data: {
        interrupt_before: interruptBefore,
        interrupt_after: interruptAfter,
        config: {
          system_prompt: systemPrompt,
          extra_config: parsedExtra,
          llm_credential_id: llmCredentialId ? Number(llmCredentialId) : null,
          model_name: modelName,
          temperature: temperature ? Number(temperature) : null,
          max_tokens: maxTokens ? Number(maxTokens) : null,
          top_p: topP ? Number(topP) : null,
          frequency_penalty: frequencyPenalty ? Number(frequencyPenalty) : null,
          presence_penalty: presencePenalty ? Number(presencePenalty) : null,
          credential_id: triggerCredentialId ? Number(triggerCredentialId) : null,
          is_active: triggerIsActive,
          priority: triggerPriority ? Number(triggerPriority) : 0,
          trigger_config: parsedTriggerConfig,
        },
      },
    })
  }

  // When a popout Save button is clicked, it updates local state (e.g. setSystemPrompt)
  // and sets this ref. On the next render — after state has settled — the effect calls handleSave.
  const saveOnNextRender = useRef(false)
  useEffect(() => {
    if (saveOnNextRender.current) {
      saveOnNextRender.current = false
      handleSave()
    }
  })

  function handleDelete() {
    deleteNode.mutate(node.node_id)
    onClose()
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{node.node_id}</h3>
        <Button variant="ghost" size="sm" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>
      <div className="text-xs text-muted-foreground">{node.component_type}</div>

      <Separator />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt Before</Label>
          <Switch checked={interruptBefore} onCheckedChange={setInterruptBefore} />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt After</Label>
          <Switch checked={interruptAfter} onCheckedChange={setInterruptAfter} />
        </div>
      </div>

      {isTriggerNode && (
        <>
          {node.component_type === "trigger_manual" && (
            <Button
              size="sm"
              className="w-full"
              onClick={() => manualExecute.mutate("")}
              disabled={manualExecute.isPending}
            >
              {manualExecute.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Play className="h-4 w-4 mr-2" />
              )}
              Run
            </Button>
          )}
          {node.component_type !== "trigger_schedule" && (
            <>
              <div className="space-y-2">
                <Label className="text-xs">Credential</Label>
                <Select value={triggerCredentialId || "none"} onValueChange={(v) => setTriggerCredentialId(v === "none" ? "" : v)}>
                  <SelectTrigger><SelectValue placeholder="Select credential (optional)" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">None</SelectItem>
                    {allCredentials.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs">Active</Label>
                <Switch checked={triggerIsActive} onCheckedChange={setTriggerIsActive} />
              </div>
            </>
          )}

          {node.component_type === "trigger_schedule" && (
            <>
              <Separator />
              <div className="space-y-3">
                <Label className="text-xs font-semibold">Schedule Configuration</Label>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-[10px]">Interval (seconds)</Label>
                    <Input type="number" min="1" value={schedInterval} onChange={(e) => setSchedInterval(e.target.value)} className="text-xs h-7" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">Total Repeats</Label>
                    <Input type="number" min="0" value={schedRepeats} onChange={(e) => setSchedRepeats(e.target.value)} className="text-xs h-7" />
                    <p className="text-[10px] text-muted-foreground">0 = infinite</p>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">Max Retries</Label>
                    <Input type="number" min="0" value={schedRetries} onChange={(e) => setSchedRetries(e.target.value)} className="text-xs h-7" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px]">Timeout (seconds)</Label>
                    <Input type="number" min="1" value={schedTimeout} onChange={(e) => setSchedTimeout(e.target.value)} className="text-xs h-7" />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Payload (JSON)</Label>
                  <Textarea
                    value={schedPayload}
                    onChange={(e) => setSchedPayload(e.target.value)}
                    rows={3}
                    className="text-xs font-mono"
                    placeholder='{ "key": "value" }'
                  />
                  <p className="text-[10px] text-muted-foreground">Data passed to downstream nodes on each run</p>
                </div>
              </div>
              <Separator />
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-semibold">Schedule Status</Label>
                  <div className="flex items-center gap-1">
                    {(!schedJob || schedJob.status === "paused" || schedJob.status === "done" || schedJob.status === "dead") && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title={!schedJob ? "Start" : schedJob.status === "paused" ? "Resume" : "Restart"}
                        disabled={scheduleStart.isPending}
                        onClick={() => scheduleStart.mutate(node.node_id, {
                          onSuccess: (data) => setSchedJob(data.schedule_job ?? null),
                        })}
                      >
                        {scheduleStart.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                      </Button>
                    )}
                    {schedJob?.status === "active" && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title="Pause"
                        disabled={schedulePause.isPending}
                        onClick={() => schedulePause.mutate(node.node_id, {
                          onSuccess: (data) => setSchedJob(data.schedule_job ?? null),
                        })}
                      >
                        {schedulePause.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pause className="h-3.5 w-3.5" />}
                      </Button>
                    )}
                    {schedJob && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 w-7 p-0"
                        title="Stop (delete job)"
                        disabled={scheduleStop.isPending}
                        onClick={() => scheduleStop.mutate(node.node_id, {
                          onSuccess: () => setSchedJob(null),
                        })}
                      >
                        {scheduleStop.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
                      </Button>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`inline-block h-2 w-2 rounded-full ${
                    schedJob?.status === "active" ? "bg-green-500" :
                    schedJob?.status === "paused" ? "bg-yellow-500" :
                    schedJob?.status === "dead" ? "bg-red-500" :
                    schedJob?.status === "done" ? "bg-gray-400" :
                    "bg-gray-300"
                  }`} />
                  <span className="text-xs">{schedJob ? schedJob.status : "No schedule"}</span>
                </div>
                {schedJob && (
                  <>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                      <span className="text-muted-foreground">Runs</span>
                      <span>{schedJob.run_count} / {schedJob.total_repeats === 0 ? "\u221E" : schedJob.total_repeats}</span>
                      <span className="text-muted-foreground">Errors</span>
                      <span>{schedJob.error_count}</span>
                      <span className="text-muted-foreground">Retry</span>
                      <span>{schedJob.current_retry} / {schedJob.max_retries}</span>
                      <span className="text-muted-foreground">Last run</span>
                      <span>{schedJob.last_run_at ? formatTimestamp(schedJob.last_run_at) : "—"}</span>
                      <span className="text-muted-foreground">Next run</span>
                      <span>{schedJob.next_run_at ? formatTimestamp(schedJob.next_run_at) : "—"}</span>
                    </div>
                    {schedJob.last_error && (
                      <div className="space-y-1">
                        <button
                          className="flex items-center gap-1 text-xs text-red-500 hover:text-red-400"
                          onClick={() => setSchedErrorExpanded(!schedErrorExpanded)}
                        >
                          {schedErrorExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                          Last error
                        </button>
                        {schedErrorExpanded && (
                          <pre className="text-[10px] text-red-400 bg-muted rounded p-2 whitespace-pre-wrap break-words max-h-32 overflow-y-auto">{schedJob.last_error}</pre>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}

          <div className="space-y-2">
            <Label className="text-xs">Priority</Label>
            <Input type="number" value={triggerPriority} onChange={(e) => setTriggerPriority(e.target.value)} className="text-xs" />
          </div>
          <div className="space-y-2">
            <Label className="text-xs">Trigger Config (JSON)</Label>
            <Textarea value={triggerConfig} onChange={(e) => setTriggerConfig(e.target.value)} rows={4} className="text-xs font-mono" />
          </div>
        </>
      )}

      {isLLMNode && (
        <>
          <div className="space-y-2">
            <Label className="text-xs">LLM Credential</Label>
            <Select value={llmCredentialId} onValueChange={setLlmCredentialId}>
              <SelectTrigger><SelectValue placeholder="Select credential" /></SelectTrigger>
              <SelectContent>
                {llmCredentials.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label className="text-xs">Model</Label>
            {availableModels && availableModels.length > 0 ? (
              <Select value={modelName} onValueChange={setModelName}>
                <SelectTrigger><SelectValue placeholder="Select model" /></SelectTrigger>
                <SelectContent>
                  {availableModels.map((m) => (
                    <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="e.g. gpt-4o" className="text-xs" />
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Temperature</Label>
              <Input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(e.target.value)} className="text-xs" placeholder="default" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Max Tokens</Label>
              <Input type="number" min="1" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} className="text-xs" placeholder="default" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Top P</Label>
              <Input type="number" step="0.05" min="0" max="1" value={topP} onChange={(e) => setTopP(e.target.value)} className="text-xs" placeholder="default" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Freq. Penalty</Label>
              <Input type="number" step="0.1" min="-2" max="2" value={frequencyPenalty} onChange={(e) => setFrequencyPenalty(e.target.value)} className="text-xs" placeholder="default" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Pres. Penalty</Label>
              <Input type="number" step="0.1" min="-2" max="2" value={presencePenalty} onChange={(e) => setPresencePenalty(e.target.value)} className="text-xs" placeholder="default" />
            </div>
          </div>
        </>
      )}

      {hasSystemPrompt && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">System Prompt</Label>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2"
                onClick={() => { setPromptDraft(systemPrompt ?? ""); setPromptModalOpen(true) }}
              >
                <Expand className="h-3 w-3 mr-1" />
                <span className="text-xs">Expand</span>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                title="Pop out to window"
                onClick={() => {
                  const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                  if (!popup) return
                  setPromptDraft(systemPrompt ?? "")
                  setPromptPopoutWindow(popup)
                  setPromptModalOpen(false)
                }}
              >
                <ExternalLink className="h-3 w-3" />
              </Button>
            </div>
          </div>
          {workflow ? (
            <ExpressionTextarea
              value={systemPrompt}
              onChange={setSystemPrompt}
              slug={slug}
              nodeId={node.node_id}
              workflow={workflow}
              className="text-xs h-24 resize-none"
            />
          ) : (
            <Textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} className="text-xs h-24 resize-none" />
          )}

          <Dialog open={promptModalOpen} onOpenChange={setPromptModalOpen}>
            <DialogContent className="max-w-[90vw] w-[1000px] h-[80vh] p-0 overflow-hidden" showCloseButton={false}>
              <div className="absolute inset-0 flex flex-col p-6 gap-4">
                <DialogHeader>
                  <div className="flex items-center justify-between">
                    <DialogTitle>Edit System Prompt</DialogTitle>
                    <div className="flex items-center gap-1 text-xs">
                      <Button
                        variant={promptLanguage === "markdown" ? "secondary" : "ghost"}
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={() => setPromptLanguage("markdown")}
                      >
                        Markdown
                      </Button>
                      <Button
                        variant={promptLanguage === "toml" ? "secondary" : "ghost"}
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={() => setPromptLanguage("toml")}
                      >
                        TOML
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        title="Pop out to window"
                        onClick={() => {
                          const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                          if (!popup) return
                          setPromptPopoutWindow(popup)
                          setPromptModalOpen(false)
                        }}
                      >
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                      <DialogClose asChild>
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                          <X className="h-3 w-3" />
                        </Button>
                      </DialogClose>
                    </div>
                  </div>
                </DialogHeader>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={promptDraft}
                      onChange={setPromptDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language={promptLanguage}
                      placeholder="Enter system prompt instructions..."
                    />
                  ) : (
                    <Textarea
                      className="flex-1 min-h-0 font-mono text-sm resize-none"
                      value={promptDraft}
                      onChange={(e) => setPromptDraft(e.target.value)}
                      placeholder="Enter system prompt instructions..."
                    />
                  )}
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setPromptModalOpen(false)}>Cancel</Button>
                  <Button onClick={() => { setSystemPrompt(promptDraft); saveOnNextRender.current = true; setPromptModalOpen(false) }}>Save</Button>
                </DialogFooter>
              </div>
            </DialogContent>
          </Dialog>

          {promptPopoutWindow && (
            <PopoutWindow popupWindow={promptPopoutWindow} title="Edit System Prompt" onClose={() => setPromptPopoutWindow(null)}>
              <div className="flex flex-col h-screen p-4 gap-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Edit System Prompt</h2>
                  <div className="flex items-center gap-1 text-xs">
                    <Button
                      variant={promptLanguage === "markdown" ? "secondary" : "ghost"}
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={() => setPromptLanguage("markdown")}
                    >
                      Markdown
                    </Button>
                    <Button
                      variant={promptLanguage === "toml" ? "secondary" : "ghost"}
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={() => setPromptLanguage("toml")}
                    >
                      TOML
                    </Button>
                  </div>
                </div>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={promptDraft}
                      onChange={setPromptDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language={promptLanguage}
                      placeholder="Enter system prompt instructions..."
                    />
                  ) : (
                    <Textarea
                      className="h-full font-mono text-sm resize-none"
                      value={promptDraft}
                      onChange={(e) => setPromptDraft(e.target.value)}
                      placeholder="Enter system prompt instructions..."
                    />
                  )}
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => closePopout(promptPopoutWindow, setPromptPopoutWindow)}>Cancel</Button>
                  <Button onClick={() => { setSystemPrompt(promptDraft); saveOnNextRender.current = true; closePopout(promptPopoutWindow, setPromptPopoutWindow) }}>Save</Button>
                </div>
              </div>
            </PopoutWindow>
          )}
        </div>
      )}

      {node.component_type === "categorizer" && (
        <>
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label className="text-xs font-semibold">Categories</Label>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => setCategories((prev) => [...prev, { name: "", description: "" }])}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Category
              </Button>
            </div>
            {categories.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">No categories defined. The LLM output will not be validated.</p>
            )}
            {categories.map((cat, idx) => (
              <div key={idx} className="border rounded-md p-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">Category {idx + 1}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 w-5 p-0"
                    onClick={() => setCategories((prev) => prev.filter((_, i) => i !== idx))}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Name</Label>
                  <Input
                    value={cat.name}
                    onChange={(e) => setCategories((prev) => prev.map((c, i) => i === idx ? { ...c, name: e.target.value } : c))}
                    className="text-xs h-7 font-mono"
                    placeholder="e.g. CHINESE"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Description</Label>
                  <Input
                    value={cat.description}
                    onChange={(e) => setCategories((prev) => prev.map((c, i) => i === idx ? { ...c, description: e.target.value } : c))}
                    className="text-xs h-7"
                    placeholder="e.g. Chinese cuisine"
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {isAgentNode && (
        <>
          <Separator />
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-xs">Conversation Memory</Label>
              <p className="text-xs text-muted-foreground">Remember prior conversations across executions</p>
            </div>
            <Switch checked={conversationMemory} onCheckedChange={setConversationMemory} />
          </div>
        </>
      )}

      {node.component_type === "code" && (
        <>
          <Separator />
          <div className="space-y-2">
            <Label className="text-xs">Language</Label>
            <Select value={codeLanguage} onValueChange={setCodeLanguage}>
              <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="python">Python</SelectItem>
                <SelectItem value="javascript">JavaScript</SelectItem>
                <SelectItem value="bash">Bash</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Code</Label>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => { setCodeDraft(codeSnippet); setCodeModalOpen(true) }}
                >
                  <Expand className="h-3 w-3 mr-1" />
                  <span className="text-xs">Expand</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  title="Pop out to window"
                  onClick={() => {
                    const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                    if (!popup) return
                    setCodeDraft(codeSnippet)
                    setCodePopoutWindow(popup)
                    setCodeModalOpen(false)
                  }}
                >
                  <ExternalLink className="h-3 w-3" />
                </Button>
              </div>
            </div>
            {workflow ? (
              <ExpressionTextarea
                value={codeSnippet}
                onChange={setCodeSnippet}
                slug={slug}
                nodeId={node.node_id}
                workflow={workflow}
                className="text-xs h-32 font-mono resize-none"
                placeholder="# Write your code here..."
              />
            ) : (
              <Textarea
                value={codeSnippet}
                onChange={(e) => setCodeSnippet(e.target.value)}
                className="text-xs h-32 font-mono resize-none"
                placeholder="# Write your code here..."
              />
            )}
          </div>

          <Dialog open={codeModalOpen} onOpenChange={setCodeModalOpen}>
            <DialogContent className="max-w-[90vw] w-[1000px] h-[80vh] p-0 overflow-hidden" showCloseButton={false}>
              <div className="absolute inset-0 flex flex-col p-6 gap-4">
                <DialogHeader>
                  <div className="flex items-center justify-between">
                    <DialogTitle>Edit Code — {codeLanguage}</DialogTitle>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        title="Pop out to window"
                        onClick={() => {
                          const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                          if (!popup) return
                          setCodePopoutWindow(popup)
                          setCodeModalOpen(false)
                        }}
                      >
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                      <DialogClose asChild>
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                          <X className="h-3 w-3" />
                        </Button>
                      </DialogClose>
                    </div>
                  </div>
                </DialogHeader>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={codeDraft}
                      onChange={setCodeDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language={codeLanguage as CodeMirrorLanguage}
                      placeholder="# Write your code here..."
                    />
                  ) : (
                    <Textarea
                      className="flex-1 min-h-0 font-mono text-sm resize-none"
                      value={codeDraft}
                      onChange={(e) => setCodeDraft(e.target.value)}
                      placeholder="# Write your code here..."
                    />
                  )}
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setCodeModalOpen(false)}>Cancel</Button>
                  <Button onClick={() => { setCodeSnippet(codeDraft); saveOnNextRender.current = true; setCodeModalOpen(false) }}>Save</Button>
                </DialogFooter>
              </div>
            </DialogContent>
          </Dialog>

          {codePopoutWindow && (
            <PopoutWindow popupWindow={codePopoutWindow} title={`Edit Code — ${codeLanguage}`} onClose={() => setCodePopoutWindow(null)}>
              <div className="flex flex-col h-screen p-4 gap-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Edit Code — {codeLanguage}</h2>
                </div>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={codeDraft}
                      onChange={setCodeDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language={codeLanguage as CodeMirrorLanguage}
                      placeholder="# Write your code here..."
                    />
                  ) : (
                    <Textarea
                      className="h-full font-mono text-sm resize-none"
                      value={codeDraft}
                      onChange={(e) => setCodeDraft(e.target.value)}
                      placeholder="# Write your code here..."
                    />
                  )}
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => closePopout(codePopoutWindow, setCodePopoutWindow)}>Cancel</Button>
                  <Button onClick={() => { setCodeSnippet(codeDraft); saveOnNextRender.current = true; closePopout(codePopoutWindow, setCodePopoutWindow) }}>Save</Button>
                </div>
              </div>
            </PopoutWindow>
          )}
        </>
      )}

      {node.component_type === "switch" && (
        <>
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label className="text-xs font-semibold">Routing Rules</Label>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => {
                  const defaultField = upstreamNodes.length === 1 ? buildFieldPath(upstreamNodes[0], "") : ""
                  setSwitchRules((prev) => [...prev, { id: generateRuleId(), field: defaultField, operator: "equals", value: "", label: "" }])
                }}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Rule
              </Button>
            </div>
            {switchRules.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">No rules defined. Add a rule to create routing branches.</p>
            )}
            {switchRules.map((rule, idx) => (
              <div key={rule.id} className="border rounded-md p-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">Rule {idx + 1}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 w-5 p-0"
                    onClick={() => setSwitchRules((prev) => prev.filter((r) => r.id !== rule.id))}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Label</Label>
                  <Input
                    value={rule.label}
                    onChange={(e) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, label: e.target.value } : r))}
                    className="text-xs h-7"
                    placeholder="e.g. Good"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Source Node</Label>
                  {upstreamNodes.length > 0 ? (
                    <Select
                      value={parseFieldPath(rule.field).sourceNodeId || (upstreamNodes.length === 1 ? upstreamNodes[0] : "")}
                      onValueChange={(v) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, field: buildFieldPath(v, parseFieldPath(r.field).outputField) } : r))}
                    >
                      <SelectTrigger className="text-xs h-7 font-mono"><SelectValue placeholder="Select source node" /></SelectTrigger>
                      <SelectContent>
                        {upstreamNodes.map((nid) => (
                          <SelectItem key={nid} value={nid} className="text-xs font-mono">{nid}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      value={parseFieldPath(rule.field).sourceNodeId}
                      onChange={(e) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, field: buildFieldPath(e.target.value, parseFieldPath(r.field).outputField) } : r))}
                      className="text-xs h-7 font-mono"
                      placeholder="node_id"
                    />
                  )}
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Output Field</Label>
                  <Input
                    value={parseFieldPath(rule.field).outputField}
                    onChange={(e) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, field: buildFieldPath(parseFieldPath(r.field).sourceNodeId, e.target.value) } : r))}
                    className="text-xs h-7 font-mono"
                    placeholder="e.g. category"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Operator</Label>
                  <Select
                    value={rule.operator}
                    onValueChange={(v) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, operator: v } : r))}
                  >
                    <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {OPERATOR_OPTIONS.map((group) => (
                        <div key={group.group}>
                          <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground">{group.group}</div>
                          {group.options.map((op) => (
                            <SelectItem key={op.value} value={op.value} className="text-xs">{op.label}</SelectItem>
                          ))}
                        </div>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {!UNARY_OPERATORS.has(rule.operator) && (
                  <div className="space-y-1">
                    <Label className="text-[10px]">Value</Label>
                    <Input
                      value={rule.value}
                      onChange={(e) => setSwitchRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, value: e.target.value } : r))}
                      className="text-xs h-7"
                      placeholder="comparison value"
                    />
                  </div>
                )}
              </div>
            ))}
            <div className="flex items-center justify-between pt-1">
              <div>
                <Label className="text-xs">Fallback Route</Label>
                <p className="text-[10px] text-muted-foreground">Route to "other" when no rules match</p>
              </div>
              <Switch checked={enableFallback} onCheckedChange={setEnableFallback} />
            </div>
          </div>
        </>
      )}

      {node.component_type === "wait" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Wait Duration</Label>
            <div className="flex gap-2">
              <Input
                type="number"
                min="0"
                step="1"
                value={waitDuration}
                onChange={(e) => setWaitDuration(e.target.value)}
                className="text-xs h-7 flex-1"
                placeholder="0"
              />
              <Select value={waitUnit} onValueChange={setWaitUnit}>
                <SelectTrigger className="text-xs h-7 w-28"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="seconds">Seconds</SelectItem>
                  <SelectItem value="minutes">Minutes</SelectItem>
                  <SelectItem value="hours">Hours</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </>
      )}

      {node.component_type === "filter" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Filter Configuration</Label>
            <div className="space-y-1">
              <Label className="text-[10px]">Source Node</Label>
              {upstreamNodes.length > 0 ? (
                <Select value={filterSourceNode} onValueChange={setFilterSourceNode}>
                  <SelectTrigger className="text-xs h-7 font-mono"><SelectValue placeholder="Select source node" /></SelectTrigger>
                  <SelectContent>
                    {upstreamNodes.map((nid) => (
                      <SelectItem key={nid} value={nid} className="text-xs font-mono">{nid}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input value={filterSourceNode} onChange={(e) => setFilterSourceNode(e.target.value)} className="text-xs h-7 font-mono" placeholder="source_node_id" />
              )}
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Source Field (optional)</Label>
              <Input value={filterField} onChange={(e) => setFilterField(e.target.value)} className="text-xs h-7 font-mono" placeholder="e.g. items" />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-xs font-semibold">Rules</Label>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => setFilterRules((prev) => [...prev, { id: generateRuleId(), field: "", operator: "equals", value: "" }])}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Rule
              </Button>
            </div>
            {filterRules.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">No rules defined. All items will pass through.</p>
            )}
            {filterRules.map((rule, idx) => (
              <div key={rule.id} className="border rounded-md p-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">Rule {idx + 1}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 w-5 p-0"
                    onClick={() => setFilterRules((prev) => prev.filter((r) => r.id !== rule.id))}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Field</Label>
                  <Input
                    value={rule.field}
                    onChange={(e) => setFilterRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, field: e.target.value } : r))}
                    className="text-xs h-7 font-mono"
                    placeholder="e.g. name, status"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Operator</Label>
                  <Select
                    value={rule.operator}
                    onValueChange={(v) => setFilterRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, operator: v } : r))}
                  >
                    <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {OPERATOR_OPTIONS.map((group) => (
                        <div key={group.group}>
                          <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground">{group.group}</div>
                          {group.options.map((op) => (
                            <SelectItem key={op.value} value={op.value} className="text-xs">{op.label}</SelectItem>
                          ))}
                        </div>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {!UNARY_OPERATORS.has(rule.operator) && (
                  <div className="space-y-1">
                    <Label className="text-[10px]">Value</Label>
                    <Input
                      value={rule.value}
                      onChange={(e) => setFilterRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, value: e.target.value } : r))}
                      className="text-xs h-7"
                      placeholder="comparison value"
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {node.component_type === "merge" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Merge Mode</Label>
            <Select value={mergeMode} onValueChange={setMergeMode}>
              <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="append">Append (flat array)</SelectItem>
                <SelectItem value="combine">Combine (merged object)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[10px] text-muted-foreground">
              {mergeMode === "append"
                ? "Concatenate all upstream outputs into a single array"
                : "Merge all upstream outputs into a single object"}
            </p>
          </div>
        </>
      )}

      {node.component_type === "loop" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Loop Configuration</Label>
            <div className="space-y-1">
              <Label className="text-[10px]">Source Node</Label>
              {upstreamNodes.length > 0 ? (
                <Select value={loopSourceNode} onValueChange={setLoopSourceNode}>
                  <SelectTrigger className="text-xs h-7 font-mono"><SelectValue placeholder="Select source node" /></SelectTrigger>
                  <SelectContent>
                    {upstreamNodes.map((nid) => (
                      <SelectItem key={nid} value={nid} className="text-xs font-mono">{nid}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input value={loopSourceNode} onChange={(e) => setLoopSourceNode(e.target.value)} className="text-xs h-7 font-mono" placeholder="source_node_id" />
              )}
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Array Field (optional)</Label>
              <Input value={loopField} onChange={(e) => setLoopField(e.target.value)} className="text-xs h-7 font-mono" placeholder="e.g. items, results" />
              <p className="text-[10px] text-muted-foreground">Field from source output that contains the array to iterate. Leave empty if source output is the array.</p>
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">On Error</Label>
              <Select value={loopOnError} onValueChange={setLoopOnError}>
                <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="stop">Stop (fail execution)</SelectItem>
                  <SelectItem value="continue">Continue (skip to next item)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground">
                {loopOnError === "continue"
                  ? "When a body node fails, record the error and continue to the next item"
                  : "When a body node fails, stop the entire execution"}
              </p>
            </div>
            <div className="border rounded-md p-2 space-y-1 bg-muted/50">
              <p className="text-[10px] font-medium">Loop handles</p>
              <p className="text-[10px] text-muted-foreground"><span className="text-amber-500 font-medium">Each Item</span> — connect to the first body node(s)</p>
              <p className="text-[10px] text-muted-foreground"><span className="text-amber-500 font-medium">Return</span> — connect from the last body node back to loop</p>
              <p className="text-[10px] text-muted-foreground"><span className="text-emerald-500 font-medium">Done</span> — connect to nodes that run after all items</p>
              <p className="text-[10px] text-muted-foreground mt-1">Access current item: <code className="bg-muted px-1 rounded">{"{{ loop.item }}"}</code></p>
              <p className="text-[10px] text-muted-foreground">Access index: <code className="bg-muted px-1 rounded">{"{{ loop.index }}"}</code></p>
            </div>
          </div>
        </>
      )}

      {node.component_type === "workflow" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Subworkflow Configuration</Label>
            <div className="space-y-1">
              <Label className="text-[10px]">Target Workflow</Label>
              <Select value={subworkflowTarget} onValueChange={setSubworkflowTarget}>
                <SelectTrigger className="text-xs h-7"><SelectValue placeholder="Select a workflow" /></SelectTrigger>
                <SelectContent>
                  {(workflowList?.items ?? [])
                    .filter((w: { slug: string }) => w.slug !== workflow?.slug)
                    .map((w: { slug: string; name: string }) => (
                      <SelectItem key={w.slug} value={w.slug} className="text-xs">{w.name} <span className="text-muted-foreground font-mono">({w.slug})</span></SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground">The workflow to execute as a child</p>
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Trigger Mode</Label>
              <Select value={subworkflowTriggerMode} onValueChange={setSubworkflowTriggerMode}>
                <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="implicit">Implicit (direct call)</SelectItem>
                  <SelectItem value="explicit">Explicit (via trigger resolver)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground">
                {subworkflowTriggerMode === "implicit"
                  ? "Call the target workflow directly — no trigger node needed on the child"
                  : "Fire a workflow event through the trigger resolver — child must have a Workflow Trigger node"}
              </p>
            </div>
            <div className="border rounded-md p-2 space-y-1 bg-muted/50">
              <p className="text-[10px] font-medium">How it works</p>
              <p className="text-[10px] text-muted-foreground">Parent state data is passed as the child&apos;s trigger payload. The parent waits for the child to complete, then receives its output.</p>
              <p className="text-[10px] text-muted-foreground">Use <span className="font-medium">Input Mapping</span> in Extra Config to control what data flows to the child.</p>
            </div>
          </div>
        </>
      )}

      {node.component_type === "http_request" && (
        <div className="space-y-2 text-xs text-muted-foreground">
          <p>Configure via Extra Config: method, headers, timeout</p>
        </div>
      )}

      {node.component_type === "web_search" && (
        <div className="space-y-2 text-xs text-muted-foreground">
          <p>Configure via Extra Config: searxng_url</p>
        </div>
      )}

      {node.component_type === "datetime" && (
        <div className="space-y-2 text-xs text-muted-foreground">
          <p>Configure via Extra Config: timezone (optional)</p>
        </div>
      )}

      {!isTriggerNode && (
        <>
        <Separator />
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">Extra Config (JSON)</Label>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2"
                onClick={() => { setExtraConfigDraft(extraConfig); setExtraConfigModalOpen(true) }}
              >
                <Expand className="h-3 w-3 mr-1" />
                <span className="text-xs">Expand</span>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                title="Pop out to window"
                onClick={() => {
                  const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                  if (!popup) return
                  setExtraConfigDraft(extraConfig)
                  setExtraConfigPopoutWindow(popup)
                  setExtraConfigModalOpen(false)
                }}
              >
                <ExternalLink className="h-3 w-3" />
              </Button>
            </div>
          </div>
          {workflow ? (
            <ExpressionTextarea slug={slug} nodeId={node.node_id} workflow={workflow} value={extraConfig} onChange={setExtraConfig} className="text-xs font-mono" />
          ) : (
            <Textarea value={extraConfig} onChange={(e) => setExtraConfig(e.target.value)} rows={4} className="text-xs font-mono" />
          )}

          <Dialog open={extraConfigModalOpen} onOpenChange={setExtraConfigModalOpen}>
            <DialogContent className="max-w-[90vw] w-[1000px] h-[80vh] p-0 overflow-hidden" showCloseButton={false}>
              <div className="absolute inset-0 flex flex-col p-6 gap-4">
                <DialogHeader>
                  <div className="flex items-center justify-between">
                    <DialogTitle>Edit Extra Config (JSON)</DialogTitle>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        title="Pop out to window"
                        onClick={() => {
                          const popup = window.open("", "", "width=1000,height=700,left=200,top=100")
                          if (!popup) return
                          setExtraConfigPopoutWindow(popup)
                          setExtraConfigModalOpen(false)
                        }}
                      >
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                      <DialogClose asChild>
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                          <X className="h-3 w-3" />
                        </Button>
                      </DialogClose>
                    </div>
                  </div>
                </DialogHeader>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={extraConfigDraft}
                      onChange={setExtraConfigDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language="json"
                      placeholder='{ "key": "value" }'
                    />
                  ) : (
                    <Textarea
                      className="flex-1 min-h-0 font-mono text-sm resize-none"
                      value={extraConfigDraft}
                      onChange={(e) => setExtraConfigDraft(e.target.value)}
                      placeholder='{ "key": "value" }'
                    />
                  )}
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setExtraConfigModalOpen(false)}>Cancel</Button>
                  <Button onClick={() => { setExtraConfig(extraConfigDraft); saveOnNextRender.current = true; setExtraConfigModalOpen(false) }}>Save</Button>
                </DialogFooter>
              </div>
            </DialogContent>
          </Dialog>

          {extraConfigPopoutWindow && (
            <PopoutWindow popupWindow={extraConfigPopoutWindow} title="Edit Extra Config (JSON)" onClose={() => setExtraConfigPopoutWindow(null)}>
              <div className="flex flex-col h-screen p-4 gap-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Edit Extra Config (JSON)</h2>
                </div>
                <div className="flex-1 min-h-0 flex flex-col">
                  {workflow ? (
                    <CodeMirrorExpressionEditor
                      value={extraConfigDraft}
                      onChange={setExtraConfigDraft}
                      slug={slug}
                      nodeId={node.node_id}
                      workflow={workflow}
                      language="json"
                      placeholder='{ "key": "value" }'
                    />
                  ) : (
                    <Textarea
                      className="h-full font-mono text-sm resize-none"
                      value={extraConfigDraft}
                      onChange={(e) => setExtraConfigDraft(e.target.value)}
                      placeholder='{ "key": "value" }'
                    />
                  )}
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => closePopout(extraConfigPopoutWindow, setExtraConfigPopoutWindow)}>Cancel</Button>
                  <Button onClick={() => { setExtraConfig(extraConfigDraft); saveOnNextRender.current = true; closePopout(extraConfigPopoutWindow, setExtraConfigPopoutWindow) }}>Save</Button>
                </div>
              </div>
            </PopoutWindow>
          )}
        </div>
        </>
      )}

      <div className="flex gap-2">
        <Button size="sm" onClick={handleSave} disabled={updateNode.isPending} className="flex-1">Save</Button>
        <Button size="sm" variant="destructive" onClick={handleDelete}><Trash2 className="h-4 w-4" /></Button>
      </div>
    </div>
  )
}
