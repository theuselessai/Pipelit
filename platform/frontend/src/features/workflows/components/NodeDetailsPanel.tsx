import { useState, useEffect, useRef, useCallback } from "react"
import { useUpdateNode, useDeleteNode } from "@/api/nodes"
import { useCredentials, useCredentialModels } from "@/api/credentials"
import { useSendChatMessage, useChatHistory } from "@/api/chat"
import { wsManager } from "@/lib/wsManager"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Calendar } from "@/components/ui/calendar"
import { X, Trash2, Send, Loader2, Expand, RotateCcw, CalendarIcon } from "lucide-react"
import { format } from "date-fns"
import type { WorkflowNode, ChatMessage } from "@/types/models"

interface Props {
  slug: string
  node: WorkflowNode
  onClose: () => void
}

const TRIGGER_TYPES = ["trigger_telegram", "trigger_webhook", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat"]

function formatTimestamp(ts: string | undefined): string {
  if (!ts) return ""
  try {
    const date = new Date(ts)
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
  const deleteNode = useDeleteNode(slug)
  const sendMessage = useSendChatMessage(slug, node.node_id)
  const [beforeDate, setBeforeDate] = useState<Date | undefined>(undefined)
  const [calendarOpen, setCalendarOpen] = useState(false)

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
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load history on mount or when refetched
  useEffect(() => {
    if (historyData?.messages) {
      setMessages(historyData.messages)
    }
  }, [historyData])

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [messages])

  const [waiting, setWaiting] = useState(false)
  const pendingExecRef = useRef<string | null>(null)

  // Register a global WS handler to listen for execution completion
  useEffect(() => {
    const handlerId = `chat-panel-${node.node_id}`
    wsManager.registerHandler(handlerId, (msg) => {
      if (!pendingExecRef.current) return
      if (msg.execution_id !== pendingExecRef.current) return

      if (msg.type === "execution_completed") {
        pendingExecRef.current = null
        setWaiting(false)
        const output = msg.data?.output as Record<string, unknown> | undefined
        if (output) {
          const text =
            (output.message as string) ||
            (output.output as string) ||
            (output.node_outputs ? Object.values(output.node_outputs as Record<string, unknown>).map(String).join("\n\n") : null) ||
            JSON.stringify(output)
          setMessages((prev) => [...prev, { role: "assistant", text, timestamp: new Date().toISOString() }])
        } else {
          setMessages((prev) => [...prev, { role: "assistant", text: "(completed with no output)", timestamp: new Date().toISOString() }])
        }
      } else if (msg.type === "execution_failed") {
        pendingExecRef.current = null
        setWaiting(false)
        setMessages((prev) => [...prev, { role: "assistant", text: `Error: ${(msg.data?.error as string) || "Execution failed"}`, timestamp: new Date().toISOString() }])
      }
    })
    return () => wsManager.unregisterHandler(handlerId)
  }, [node.node_id])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || sendMessage.isPending || waiting) return
    setInput("")
    setMessages((prev) => [...prev, { role: "user", text, timestamp: new Date().toISOString() }])
    sendMessage.mutate(text, {
      onSuccess: (data) => {
        setWaiting(true)
        pendingExecRef.current = data.execution_id
        // Timeout fallback
        setTimeout(() => {
          if (pendingExecRef.current === data.execution_id) {
            pendingExecRef.current = null
            setWaiting(false)
            setMessages((prev) => [...prev, { role: "assistant", text: "Error: Execution timed out", timestamp: new Date().toISOString() }])
          }
        }, 120_000)
      },
      onError: (err) => {
        setMessages((prev) => [...prev, { role: "assistant", text: `Error: ${err.message}`, timestamp: new Date().toISOString() }])
      },
    })
  }, [input, sendMessage, waiting])

  return (
    <Dialog open={true} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-[90vw] w-[900px] h-[80vh] flex flex-col p-0" showCloseButton={false}>
        <DialogHeader className="p-4 border-b flex-row items-center justify-between space-y-0">
          <div>
            <DialogTitle>{node.node_id}</DialogTitle>
            <div className="text-xs text-muted-foreground mt-1">Chat Trigger</div>
          </div>
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
            <Button variant="ghost" size="sm" onClick={() => { deleteNode.mutate(node.node_id); onClose() }}>
              <Trash2 className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </DialogHeader>
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
          {(sendMessage.isPending || waiting) && (
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
      </DialogContent>
    </Dialog>
  )
}

export default function NodeDetailsPanel({ slug, node, onClose }: Props) {
  if (node.component_type === "trigger_chat") {
    return <ChatPanel slug={slug} node={node} onClose={onClose} />
  }
  return <NodeConfigPanel slug={slug} node={node} onClose={onClose} />
}

function NodeConfigPanel({ slug, node, onClose }: Props) {
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const { data: credentials } = useCredentials()
  const llmCredentials = credentials?.filter((c) => c.credential_type === "llm") ?? []

  const [systemPrompt, setSystemPrompt] = useState(node.config.system_prompt)
  const [extraConfig, setExtraConfig] = useState(JSON.stringify(node.config.extra_config, null, 2))
  const [llmCredentialId, setLlmCredentialId] = useState<string>(node.config.llm_credential_id?.toString() ?? "")
  const [modelName, setModelName] = useState(node.config.model_name ?? "")
  const [temperature, setTemperature] = useState<string>(node.config.temperature?.toString() ?? "")
  const [maxTokens, setMaxTokens] = useState<string>(node.config.max_tokens?.toString() ?? "")
  const [topP, setTopP] = useState<string>(node.config.top_p?.toString() ?? "")
  const [frequencyPenalty, setFrequencyPenalty] = useState<string>(node.config.frequency_penalty?.toString() ?? "")
  const [presencePenalty, setPresencePenalty] = useState<string>(node.config.presence_penalty?.toString() ?? "")
  const [isEntryPoint, setIsEntryPoint] = useState(node.is_entry_point)
  const [interruptBefore, setInterruptBefore] = useState(node.interrupt_before)
  const [interruptAfter, setInterruptAfter] = useState(node.interrupt_after)
  const [conversationMemory, setConversationMemory] = useState<boolean>(Boolean(node.config.extra_config?.conversation_memory))

  // System prompt modal state
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState("")

  // Trigger fields
  const [triggerCredentialId, setTriggerCredentialId] = useState<string>(node.config.credential_id?.toString() ?? "")
  const [triggerIsActive, setTriggerIsActive] = useState(node.config.is_active ?? true)
  const [triggerPriority, setTriggerPriority] = useState<string>(node.config.priority?.toString() ?? "0")
  const [triggerConfig, setTriggerConfig] = useState(JSON.stringify(node.config.trigger_config ?? {}, null, 2))

  const credId = llmCredentialId ? Number(llmCredentialId) : undefined
  const { data: availableModels } = useCredentialModels(credId)

  useEffect(() => {
    setSystemPrompt(node.config.system_prompt)
    setExtraConfig(JSON.stringify(node.config.extra_config, null, 2))
    setLlmCredentialId(node.config.llm_credential_id?.toString() ?? "")
    setModelName(node.config.model_name ?? "")
    setTemperature(node.config.temperature?.toString() ?? "")
    setMaxTokens(node.config.max_tokens?.toString() ?? "")
    setTopP(node.config.top_p?.toString() ?? "")
    setFrequencyPenalty(node.config.frequency_penalty?.toString() ?? "")
    setPresencePenalty(node.config.presence_penalty?.toString() ?? "")
    setIsEntryPoint(node.is_entry_point)
    setInterruptBefore(node.interrupt_before)
    setInterruptAfter(node.interrupt_after)
    setTriggerCredentialId(node.config.credential_id?.toString() ?? "")
    setTriggerIsActive(node.config.is_active ?? true)
    setTriggerPriority(node.config.priority?.toString() ?? "0")
    setTriggerConfig(JSON.stringify(node.config.trigger_config ?? {}, null, 2))
    setConversationMemory(Boolean(node.config.extra_config?.conversation_memory))
  }, [node])

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
    let parsedTriggerConfig = {}
    try { parsedTriggerConfig = JSON.parse(triggerConfig) } catch { /* keep empty */ }
    updateNode.mutate({
      nodeId: node.node_id,
      data: {
        is_entry_point: isEntryPoint,
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
          <Label className="text-xs">Entry Point</Label>
          <Switch checked={isEntryPoint} onCheckedChange={setIsEntryPoint} />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt Before</Label>
          <Switch checked={interruptBefore} onCheckedChange={setInterruptBefore} />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt After</Label>
          <Switch checked={interruptAfter} onCheckedChange={setInterruptAfter} />
        </div>
      </div>

      <Separator />

      {isTriggerNode && (
        <>
          <div className="space-y-2">
            <Label className="text-xs">Credential</Label>
            <Select value={triggerCredentialId || "none"} onValueChange={(v) => setTriggerCredentialId(v === "none" ? "" : v)}>
              <SelectTrigger><SelectValue placeholder="Select credential (optional)" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {credentials?.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center justify-between">
            <Label className="text-xs">Active</Label>
            <Switch checked={triggerIsActive} onCheckedChange={setTriggerIsActive} />
          </div>
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
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2"
              onClick={() => { setPromptDraft(systemPrompt ?? ""); setPromptModalOpen(true) }}
            >
              <Expand className="h-3 w-3 mr-1" />
              <span className="text-xs">Expand</span>
            </Button>
          </div>
          <Textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} className="text-xs h-24 resize-none" />

          <Dialog open={promptModalOpen} onOpenChange={setPromptModalOpen}>
            <DialogContent className="max-w-[90vw] w-[1000px] h-[80vh] flex flex-col">
              <DialogHeader>
                <DialogTitle>Edit System Prompt</DialogTitle>
              </DialogHeader>
              <Textarea
                className="flex-1 font-mono text-sm resize-none"
                value={promptDraft}
                onChange={(e) => setPromptDraft(e.target.value)}
                placeholder="Enter system prompt instructions..."
              />
              <DialogFooter>
                <Button variant="outline" onClick={() => setPromptModalOpen(false)}>Cancel</Button>
                <Button onClick={() => { setSystemPrompt(promptDraft); setPromptModalOpen(false) }}>Save</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
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
        <div className="space-y-2">
          <Label className="text-xs">Extra Config (JSON)</Label>
          <Textarea value={extraConfig} onChange={(e) => setExtraConfig(e.target.value)} rows={4} className="text-xs font-mono" />
        </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" onClick={handleSave} disabled={updateNode.isPending} className="flex-1">Save</Button>
        <Button size="sm" variant="destructive" onClick={handleDelete}><Trash2 className="h-4 w-4" /></Button>
      </div>
    </div>
  )
}
