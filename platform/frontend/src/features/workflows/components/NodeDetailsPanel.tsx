import { useState, useEffect, useRef, useMemo } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useUpdateNode, useDeleteNode, useScheduleStart, useSchedulePause, useScheduleStop } from "@/api/nodes"
import { useWorkflows } from "@/api/workflows"
import { useCredentials, useCredentialModels } from "@/api/credentials"
import { useWorkspaces } from "@/api/workspaces"

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
import { X, Trash2, Loader2, Expand, ExternalLink, Plus, Play, Pause, Square, ChevronDown, ChevronUp, Info } from "lucide-react"
import ExpressionTextarea from "@/components/ExpressionTextarea"
import CodeMirrorExpressionEditor from "@/components/CodeMirrorExpressionEditor"
import PopoutWindow from "@/components/PopoutWindow"
import type { CodeMirrorLanguage } from "@/components/CodeMirrorEditor"
import type { WorkflowNode, WorkflowDetail, SwitchRule, FilterRule, ScheduleJobInfo } from "@/types/models"
import RuleEditor from "./RuleEditor"

interface Props {
  slug: string
  node: WorkflowNode
  workflow?: WorkflowDetail
  onClose: () => void
}

const TRIGGER_TYPES = ["trigger_telegram", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat"]


/** Close a popout window and clear its state. Use for Save/Cancel buttons — NOT for onClose (which fires from beforeunload when the popup is already closing). */
function closePopout(popup: Window | null, setter: (w: Window | null) => void) {
  if (popup && !popup.closed) popup.close()
  setter(null)
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

export default function NodeDetailsPanel({ slug, node, workflow, onClose }: Props) {
  // key={node.node_id} causes React to fully remount when switching nodes,
  // so all useState initializers run fresh — no stale state across nodes.
  return <NodeConfigPanel key={node.node_id} slug={slug} node={node} workflow={workflow} onClose={onClose} />
}


function NodeConfigPanel({ slug, node, workflow, onClose }: Props) {
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const { data: credentials } = useCredentials()
  const { data: workspacesData } = useWorkspaces()
  const allCredentials = credentials?.items ?? []
  const llmCredentials = allCredentials.filter((c) => c.credential_type === "llm")

  const [labelValue, setLabelValue] = useState(node.label || node.node_id)

  useEffect(() => {
    setLabelValue(node.label || node.node_id)
  }, [node.label, node.node_id])

  const [systemPrompt, setSystemPrompt] = useState(node.config.system_prompt)
  const [extraConfig, setExtraConfig] = useState(JSON.stringify(node.config.extra_config, null, 2))
  const [llmCredentialId, setLlmCredentialId] = useState<string>(node.config.llm_credential_id?.toString() ?? "")
  const [modelName, setModelName] = useState(node.config.model_name ?? "")
  const [temperature, setTemperature] = useState<string>(node.config.temperature?.toString() ?? "")
  const [maxTokens, setMaxTokens] = useState<string>(node.config.max_tokens?.toString() ?? "")
  const [topP, setTopP] = useState<string>(node.config.top_p?.toString() ?? "")
  const [frequencyPenalty, setFrequencyPenalty] = useState<string>(node.config.frequency_penalty?.toString() ?? "")
  const [presencePenalty, setPresencePenalty] = useState<string>(node.config.presence_penalty?.toString() ?? "")
  const [useNativeSearch, setUseNativeSearch] = useState<boolean>(Boolean((node.config.extra_config as Record<string, unknown>)?.use_native_search))
  const [interruptBefore, setInterruptBefore] = useState(node.interrupt_before)
  const [interruptAfter, setInterruptAfter] = useState(node.interrupt_after)
  const [conversationMemory, setConversationMemory] = useState<boolean>(Boolean(node.config.extra_config?.conversation_memory))
  const [contextWindow, setContextWindow] = useState<string>(
    (node.config.extra_config?.context_window as number)?.toString() ?? ""
  )
  const [compacting, setCompacting] = useState<string>(
    (node.config.extra_config?.compacting as string) ?? ""
  )
  const [compactingTrigger, setCompactingTrigger] = useState<string>(
    (node.config.extra_config?.compacting_trigger as number)?.toString() ?? "70"
  )
  const [compactingKeep, setCompactingKeep] = useState<string>(
    (node.config.extra_config?.compacting_keep as number)?.toString() ?? "20"
  )
  const [inputTemplate, setInputTemplate] = useState<string>(
    (node.config.extra_config?.input_template as string) ?? ""
  )
  const [replyMessage, setReplyMessage] = useState<string>(
    (node.config.extra_config?.message as string) ?? ""
  )

  // Deep agent state
  const [workspaceId, setWorkspaceId] = useState<string>((node.config.extra_config?.workspace_id as number)?.toString() ?? "")
  const [enableTodos, setEnableTodos] = useState<boolean>(Boolean(node.config.extra_config?.enable_todos))
  // Network access is controlled at the workspace level (not per-node)
  const [subagents, setSubagents] = useState<{ name: string; description: string; system_prompt: string; model: string }[]>(
    () => (node.config.extra_config?.subagents as { name: string; description: string; system_prompt: string; model: string }[]) ?? []
  )

  // Skill state
  const [skillPath, setSkillPath] = useState<string>((node.config.extra_config?.skill_path as string) ?? "")
  const [skillSource, setSkillSource] = useState<string>((node.config.extra_config?.skill_source as string) ?? "filesystem")

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
    const SUB_TYPES = new Set(["ai_model", "run_command", "output_parser", "memory_read", "memory_write", "create_agent_user", "platform_api", "whoami", "spawn_and_await"])
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

  useEffect(() => {
    setTriggerIsActive(node.config.is_active ?? true)
  }, [node.config.is_active])

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
  const isAgentNode = node.component_type === "agent" || node.component_type === "deep_agent"
  const isDeepAgent = node.component_type === "deep_agent"
  const hasSystemPrompt = ["agent", "deep_agent", "categorizer", "router"].includes(node.component_type)
  const isTriggerNode = TRIGGER_TYPES.includes(node.component_type)

  const isAnthropicNative = useMemo(() => {
    if (!isLLMNode || !llmCredentialId) return false
    const cred = allCredentials.find(c => c.id === Number(llmCredentialId))
    if (!cred) return false
    const provider = cred.detail?.provider_type as string
    const baseUrl = cred.detail?.base_url as string
    return provider === "anthropic" && (!baseUrl || baseUrl.includes("anthropic.com"))
  }, [isLLMNode, llmCredentialId, allCredentials])

  const searchBackend = useMemo(() => {
    if (!isAgentNode || !workflow) return null
    // Check if connected ai_model has use_native_search enabled
    const modelEdge = workflow.edges.find(
      (e) => e.target_node_id === node.node_id && e.edge_label === "llm"
    )
    const modelNode = modelEdge ? workflow.nodes.find((n) => n.node_id === modelEdge.source_node_id) : undefined
    const credId = modelNode?.config.llm_credential_id
    const cred = credId ? allCredentials.find((c) => c.id === credId) : undefined
    const provider = (cred?.detail as Record<string, unknown>)?.provider_type as string
    const baseUrl = (cred?.detail as Record<string, unknown>)?.base_url as string
    const useNative = !!(modelNode?.config.extra_config as Record<string, unknown>)?.use_native_search
    // Priority 1: Native opt-in overrides SearXNG
    if (useNative && provider === "anthropic" && (!baseUrl || baseUrl.includes("anthropic.com")))
      return "anthropic"
    // Priority 2: SearXNG is the default
    const hasSearxng = allCredentials.some(
      (c) => c.credential_type === "tool" && (c.detail as Record<string, unknown>)?.tool_type === "searxng"
    )
    if (hasSearxng) return "searxng"
    return "unavailable"
  }, [isAgentNode, workflow, node.node_id, allCredentials])

  function handleSave() {
    let parsedExtra: Record<string, unknown> = {}
    try { parsedExtra = JSON.parse(extraConfig) } catch { /* keep empty */ }
    if (isAgentNode) {
      parsedExtra = {
        ...parsedExtra,
        conversation_memory: conversationMemory,
        context_window: contextWindow ? (Number(contextWindow) || null) : null,
        compacting: compacting || null,
        compacting_trigger: compacting === "summarize" ? (Number(compactingTrigger) || null) : null,
        compacting_keep: compacting === "summarize" ? (Number(compactingKeep) || null) : null,
        workspace_id: workspaceId ? Number(workspaceId) : null,
      }
    }
    if (isLLMNode) {
      parsedExtra = { ...parsedExtra, use_native_search: useNativeSearch }
    }
    if (isDeepAgent) {
      parsedExtra = {
        ...parsedExtra,
        enable_todos: enableTodos,
        subagents: subagents.filter((sa) => sa.name.trim() && sa.description.trim() && sa.system_prompt.trim()),
      }
    }
    if (["agent", "deep_agent"].includes(node.component_type) && inputTemplate) {
      parsedExtra.input_template = inputTemplate
    }
    if (node.component_type === "reply_chat") {
      parsedExtra.message = replyMessage
    }
    if (node.component_type === "skill") {
      parsedExtra = { ...parsedExtra, skill_path: skillPath, skill_source: skillSource }
    }
    if (node.component_type === "code") {
      parsedExtra = { ...parsedExtra, code: codeSnippet, language: codeLanguage, workspace_id: workspaceId ? Number(workspaceId) : null }
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
        <Input
          className="font-semibold text-sm h-8 px-2 border-transparent hover:border-input focus:border-input"
          value={labelValue}
          onChange={(e) => setLabelValue(e.target.value)}
          onBlur={() => {
            const val = labelValue.trim()
            if (val && val !== (node.label || node.node_id)) {
              updateNode.mutate({ nodeId: node.node_id, data: { label: val } })
            } else if (!val) {
              setLabelValue(node.label || node.node_id)
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur()
          }}
        />
        <Button variant="ghost" size="sm" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>
      <div className="text-xs text-muted-foreground">{node.component_type} &middot; {node.node_id}</div>

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
            {isAgentNode && (
              <div className="space-y-1">
                <Label className="text-xs">Context Window</Label>
                <Input type="number" min="1024" value={contextWindow} onChange={(e) => setContextWindow(e.target.value)} className="text-xs" placeholder="auto-detect" />
              </div>
            )}
          </div>
          {isAnthropicNative && (
            <div className="flex items-center justify-between mt-2">
              <div>
                <Label className="text-xs">Use Native Search</Label>
                <p className="text-xs text-muted-foreground">Use Anthropic's built-in web search instead of SearXNG</p>
              </div>
              <Switch checked={useNativeSearch} onCheckedChange={setUseNativeSearch} />
            </div>
          )}
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

      {isAgentNode && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Input Template</label>
          <p className="text-xs text-muted-foreground">
            Override the agent&apos;s input messages with a template. Supports{" "}
            <code className="text-xs">{"{{ node_id.output }}"}</code> expressions.
            Leave empty to use the full conversation history (default).
          </p>
          <Textarea
            value={inputTemplate}
            onChange={(e) => setInputTemplate(e.target.value)}
            placeholder={"{{ scribe.output }}"}
            className="font-mono text-sm min-h-[80px]"
          />
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
          {searchBackend && (
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-xs">Web Search</Label>
                <p className="text-xs text-muted-foreground">Auto-detected search backend</p>
              </div>
              <span className="text-xs">
                {searchBackend === "anthropic" && <span className="text-emerald-500">Anthropic native</span>}
                {searchBackend === "searxng" && <span className="text-blue-500">SearXNG</span>}
                {searchBackend === "unavailable" && <span className="text-zinc-400">unavailable</span>}
              </span>
            </div>
          )}
          {!isDeepAgent && (
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-xs">Compacting Strategy</Label>
                <p className="text-xs text-muted-foreground">Summarize old messages when context fills up</p>
              </div>
              <Switch checked={compacting === "summarize"} onCheckedChange={(v) => setCompacting(v ? "summarize" : "")} />
            </div>
          )}
          {compacting === "summarize" && !isDeepAgent && (
            <div className="grid grid-cols-2 gap-2 ml-0">
              <div className="space-y-1">
                <Label className="text-xs">Trigger at %</Label>
                <Input type="number" min="10" max="100" value={compactingTrigger}
                  onChange={(e) => setCompactingTrigger(e.target.value)}
                  className="text-xs" placeholder="70" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Keep messages</Label>
                <Input type="number" min="1" value={compactingKeep}
                  onChange={(e) => setCompactingKeep(e.target.value)}
                  className="text-xs" placeholder="20" />
              </div>
            </div>
          )}
          {!isDeepAgent && (
            <div className="space-y-1">
              <Label className="text-xs">Workspace</Label>
              <p className="text-xs text-muted-foreground">Sandboxed directory for tool execution</p>
              <Select value={workspaceId} onValueChange={(v) => {
                setWorkspaceId(v)
              }}>
                <SelectTrigger className="text-xs h-7">
                  <SelectValue placeholder="No workspace (unsandboxed)" />
                </SelectTrigger>
                <SelectContent>
                  {workspacesData?.items?.map((ws) => (
                    <SelectItem key={ws.id} value={ws.id.toString()}>{ws.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </>
      )}

      {isDeepAgent && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Deep Agent Features</Label>
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-xs">Task Planning (Todos)</Label>
                <p className="text-xs text-muted-foreground">Built-in task planning and tracking</p>
              </div>
              <Switch checked={enableTodos} onCheckedChange={setEnableTodos} />
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Info className="h-3 w-3 shrink-0" />
              <span>Network access is controlled by the workspace setting.</span>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Workspace</Label>
              <p className="text-xs text-muted-foreground">Sandboxed directory for file read/write operations</p>
              <Select value={workspaceId} onValueChange={setWorkspaceId}>
                <SelectTrigger className="text-xs h-7">
                  <SelectValue placeholder="Default workspace" />
                </SelectTrigger>
                <SelectContent>
                  {workspacesData?.items?.map((ws) => (
                    <SelectItem key={ws.id} value={ws.id.toString()}>{ws.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label className="text-xs font-semibold">Subagents</Label>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => setSubagents([...subagents, { name: "", description: "", system_prompt: "", model: "" }])}
              >
                <Plus className="h-3 w-3 mr-1" />
                Add
              </Button>
            </div>
            {subagents.length === 0 && (
              <p className="text-xs text-muted-foreground">No subagents configured. Add one to enable agent delegation.</p>
            )}
            {subagents.map((sa, idx) => (
              <div key={idx} className="space-y-2 p-2 border rounded-md">
                <div className="flex items-center justify-between">
                  <Label className="text-[10px] font-medium">Subagent {idx + 1}</Label>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 w-5 p-0"
                    onClick={() => setSubagents(subagents.filter((_, i) => i !== idx))}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Name</Label>
                  <Input
                    value={sa.name}
                    onChange={(e) => {
                      const updated = [...subagents]
                      updated[idx] = { ...updated[idx], name: e.target.value }
                      setSubagents(updated)
                    }}
                    className="text-xs h-7"
                    placeholder="researcher"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Description</Label>
                  <Input
                    value={sa.description}
                    onChange={(e) => {
                      const updated = [...subagents]
                      updated[idx] = { ...updated[idx], description: e.target.value }
                      setSubagents(updated)
                    }}
                    className="text-xs h-7"
                    placeholder="Researches topics and gathers information"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">System Prompt</Label>
                  <Textarea
                    value={sa.system_prompt}
                    onChange={(e) => {
                      const updated = [...subagents]
                      updated[idx] = { ...updated[idx], system_prompt: e.target.value }
                      setSubagents(updated)
                    }}
                    className="text-xs h-16 resize-none"
                    placeholder="You are a research assistant..."
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px]">Model Override (optional)</Label>
                  <Input
                    value={sa.model}
                    onChange={(e) => {
                      const updated = [...subagents]
                      updated[idx] = { ...updated[idx], model: e.target.value }
                      setSubagents(updated)
                    }}
                    className="text-xs h-7"
                    placeholder="Leave empty to use parent model"
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {node.component_type === "skill" && (
        <>
          <Separator />
          <div className="space-y-3">
            <Label className="text-xs font-semibold">Skill Configuration</Label>
            <div className="space-y-1">
              <Label className="text-[10px]">Source Type</Label>
              <Select value={skillSource} onValueChange={setSkillSource}>
                <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="filesystem">Filesystem</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Skill Path</Label>
              <Input
                value={skillPath}
                onChange={(e) => setSkillPath(e.target.value)}
                className="text-xs h-7"
                placeholder="~/.config/pipelit/skills/"
              />
              <p className="text-[10px] text-muted-foreground">
                Directory containing skill subdirectories, each with a SKILL.md file.
                Leave empty to use the platform default. Connect multiple skill nodes to load from different directories.
              </p>
            </div>
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
          <div className="space-y-1">
            <Label className="text-xs">Workspace</Label>
            <p className="text-xs text-muted-foreground">Sandboxed directory for code execution</p>
            <Select value={workspaceId} onValueChange={(v) => {
              setWorkspaceId(v)
            }}>
              <SelectTrigger className="text-xs h-7">
                <SelectValue placeholder="Default workspace" />
              </SelectTrigger>
              <SelectContent>
                {workspacesData?.items?.map((ws) => (
                  <SelectItem key={ws.id} value={ws.id.toString()}>{ws.name}</SelectItem>
                ))}
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
          <RuleEditor<SwitchRule>
            rules={switchRules}
            onChange={setSwitchRules}
            upstreamNodes={upstreamNodes}
            showLabel
            showSourceNode
            showFallback
            enableFallback={enableFallback}
            onFallbackChange={setEnableFallback}
            title="Routing Rules"
            emptyMessage="No rules defined. Add a rule to create routing branches."
          />
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
            <RuleEditor<FilterRule>
              rules={filterRules}
              onChange={setFilterRules}
              upstreamNodes={upstreamNodes}
              emptyMessage="No rules defined. All items will pass through."
            />
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

      {node.component_type === "reply_chat" && (
        <>
          <Separator />
          <div className="space-y-2">
            <Label className="text-xs font-semibold">Reply Message</Label>
            <p className="text-xs text-muted-foreground">
              Message to send back to the chat caller. Supports{" "}
              <code className="text-xs">{"{{ node_id.output }}"}</code> expressions.
            </p>
            <Textarea
              value={replyMessage}
              onChange={(e) => setReplyMessage(e.target.value)}
              placeholder={"{{ agent.output }}"}
              className="font-mono text-sm min-h-[80px]"
            />
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
