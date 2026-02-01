import { useCreateNode } from "@/api/nodes"
import { Button } from "@/components/ui/button"
import type { ComponentType } from "@/types/models"
import {
  MessageSquare, Send, Webhook, Clock, Hand, Workflow, AlertTriangle,
  Cpu, Bot, BrainCircuit,
  GitFork, Route, FileOutput,
  Wrench, Globe,
  Repeat, Columns2, Pause, Merge, Filter, Shuffle, ArrowDownNarrowWide, ListEnd,
  Code, UserCheck, Layers, ShieldAlert, FileText,
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
  simple_agent: Bot,
  planner_agent: BrainCircuit,
  categorizer: GitFork,
  router: Route,
  extractor: FileOutput,
  tool_node: Wrench,
  http_request: Globe,
  loop: Repeat,
  parallel: Columns2,
  wait: Pause,
  merge: Merge,
  filter: Filter,
  transform: Shuffle,
  sort: ArrowDownNarrowWide,
  limit: ListEnd,
  workflow: Workflow,
  code: Code,
  human_confirmation: UserCheck,
  aggregator: Layers,
  error_handler: ShieldAlert,
  output_parser: FileText,
}

const NODE_CATEGORIES: { label: string; types: ComponentType[] }[] = [
  { label: "Triggers", types: ["trigger_chat", "trigger_telegram", "trigger_webhook", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error"] },
  { label: "AI", types: ["ai_model", "simple_agent", "planner_agent"] },
  { label: "Routing", types: ["categorizer", "router", "extractor"] },
  { label: "Tools", types: ["tool_node", "http_request"] },
  { label: "Logic", types: ["loop", "parallel", "wait", "merge", "filter", "transform", "sort", "limit"] },
  { label: "Other", types: ["workflow", "code", "human_confirmation", "aggregator", "error_handler", "output_parser"] },
]

export default function NodePalette({ slug }: { slug: string }) {
  const createNode = useCreateNode(slug)

  function handleAdd(type: ComponentType) {
    const nodeId = `${type}_${Date.now().toString(36)}`
    createNode.mutate({
      node_id: nodeId,
      component_type: type,
      position_x: 250,
      position_y: 150,
    })
  }

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
                  {type.replace(/^trigger_/, "").replace(/_/g, " ")}
                </Button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
