import { useRef, useCallback } from "react"
import { useCreateNode } from "@/api/nodes"
import { Button } from "@/components/ui/button"
import type { ComponentType } from "@/types/models"
import {
  MessageSquare, Send, Webhook, Clock, Hand, Workflow, AlertTriangle, Compass,
  Cpu, Bot,
  GitFork, Route, FileOutput, Split,
  Terminal, Globe, Search, Calculator,
  Repeat, Pause, Merge, Filter,
  Code, UserCheck, Layers, ShieldAlert, FileText,
  Database, DatabaseZap, UserSearch, SquareTerminal, UserPlus, Plug, Fingerprint, KeyRound,
  ClipboardList, ListChecks, Rocket, PencilRuler, CalendarClock, HeartPulse,
  type LucideIcon,
} from "lucide-react"

const ICONS: Record<ComponentType, LucideIcon> = {
  trigger_chat: MessageSquare,
  trigger_telegram: Send,
  trigger_webhook: Webhook,
  trigger_schedule: Clock,
  trigger_manual: Hand,
  trigger_workflow: Workflow,
  trigger_error: AlertTriangle,
  ai_model: Cpu,
  agent: Bot,
  categorizer: GitFork,
  router: Route,
  switch: Split,
  extractor: FileOutput,
  run_command: Terminal,
  http_request: Globe,
  web_search: Search,
  calculator: Calculator,
  datetime: Clock,
  create_agent_user: UserPlus,
  get_totp_code: KeyRound,
  platform_api: Plug,
  whoami: Fingerprint,
  epic_tools: ClipboardList,
  task_tools: ListChecks,
  spawn_and_await: Rocket,
  workflow_create: PencilRuler,
  workflow_discover: Compass,
  scheduler_tools: CalendarClock,
  system_health: HeartPulse,
  loop: Repeat,
  wait: Pause,
  merge: Merge,
  filter: Filter,
  workflow: Workflow,
  code: Code,
  human_confirmation: UserCheck,
  aggregator: Layers,
  error_handler: ShieldAlert,
  output_parser: FileText,
  memory_read: Database,
  memory_write: DatabaseZap,
  identify_user: UserSearch,
  code_execute: SquareTerminal,
}

const NODE_CATEGORIES: { label: string; types: ComponentType[] }[] = [
  { label: "Triggers", types: ["trigger_chat", "trigger_telegram", "trigger_webhook", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error"] },
  { label: "AI", types: ["ai_model", "agent"] },
  { label: "Routing", types: ["categorizer", "extractor"] },
  { label: "Memory", types: ["memory_read", "memory_write", "identify_user"] },
  { label: "Agent", types: ["whoami", "create_agent_user", "get_totp_code", "platform_api", "epic_tools", "task_tools", "scheduler_tools", "system_health", "spawn_and_await", "workflow_create", "workflow_discover"] },
  { label: "Tools", types: ["run_command", "http_request", "web_search", "calculator", "datetime", "code_execute"] },
  { label: "Logic", types: ["switch", "loop", "filter", "merge", "wait"] },
  { label: "Other", types: ["workflow", "code", "human_confirmation", "aggregator", "error_handler", "output_parser"] },
]

export default function NodePalette({ slug }: { slug: string }) {
  const createNode = useCreateNode(slug)

  const counterRef = useRef(0)
  const handleAdd = useCallback((type: ComponentType) => {
    counterRef.current += 1
    const nodeId = `${type}_${Date.now().toString(36)}${counterRef.current}`
    createNode.mutate({
      node_id: nodeId,
      component_type: type,
      position_x: 250,
      position_y: 150,
    })
  }, [createNode])

  return (
    <div className="space-y-4">
      {NODE_CATEGORIES.map((cat) => (
        <div key={cat.label}>
          <div className="text-xs font-semibold text-muted-foreground mb-1">{cat.label}</div>
          <div className="space-y-1">
            {cat.types.map((type) => {
              const Icon = ICONS[type]
              return (
                <Button
                  key={type}
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start text-xs gap-2"
                  onClick={() => handleAdd(type)}
                  disabled={createNode.isPending}
                >
                  {Icon && <Icon className="h-3.5 w-3.5 shrink-0" />}
                  {type.replace(/^trigger_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </Button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
