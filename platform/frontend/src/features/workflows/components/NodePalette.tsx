import { useCallback } from "react"
import { useCreateNode } from "@/api/nodes"
import { useNodeTypes } from "@/api/workflows"
import { useBinaryCatalogs } from "@/api/plugins"
import { Button } from "@/components/ui/button"
import type { BuiltinComponentType, ComponentType } from "@/types/models"
import {
  MessageSquare, Send, Clock, Hand, Workflow, AlertTriangle, Compass,
  Cpu, Bot, Brain, GraduationCap,
  GitFork, Route, FileOutput, Split,
  Terminal,
  Repeat, Pause, Merge, Filter, ClipboardCheck,
  Code, UserCheck, ShieldAlert, FileText, CheckSquare, FileCheck,
  Database, DatabaseZap, UserSearch, UserPlus, Plug, Fingerprint, KeyRound,
  Rocket, PencilRuler, CalendarClock, HeartPulse,
  Mail, MailSearch, Boxes, IdCard,
  type LucideIcon,
} from "lucide-react"

const ICONS: Record<BuiltinComponentType, LucideIcon> = {
  trigger_chat: MessageSquare,
  trigger_telegram: Send,
  trigger_schedule: Clock,
  trigger_manual: Hand,
  trigger_workflow: Workflow,
  trigger_error: AlertTriangle,
  ai_model: Cpu,
  agent: Bot,
  deep_agent: Brain,
  categorizer: GitFork,
  router: Route,
  switch: Split,
  extractor: FileOutput,
  run_command: Terminal,
  create_agent_user: UserPlus,
  get_totp_code: KeyRound,
  platform_api: Plug,
  whoami: Fingerprint,
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
  error_handler: ShieldAlert,
  output_parser: FileText,
  memory_read: Database,
  memory_write: DatabaseZap,
  identify_user: UserSearch,
  skill: GraduationCap,
  reply_chat: MessageSquare,
  validate_gherkin: CheckSquare,
  validate_topology: FileCheck,
  assertion: ClipboardCheck,
  mailbox_action: Mail,
  mailbox_parse: MailSearch,
  binary_op: Boxes,
  binary_auth: IdCard,
}

const NODE_CATEGORIES = [
  { label: "Triggers", types: ["trigger_chat", "trigger_telegram", "trigger_schedule", "trigger_manual", "trigger_workflow", "trigger_error"] },
  { label: "AI", types: ["ai_model", "agent", "deep_agent", "skill"] },
  { label: "Routing", types: ["categorizer", "extractor", "router"] },
  { label: "Memory", types: ["memory_read", "memory_write", "identify_user"] },
  { label: "Agent", types: ["whoami", "create_agent_user", "get_totp_code", "platform_api", "scheduler_tools", "system_health", "spawn_and_await", "workflow_create"] },
  { label: "Tools", types: ["run_command", "workflow_discover", "validate_gherkin", "validate_topology"] },
  { label: "Mail", types: ["mailbox_action", "mailbox_parse"] },
  { label: "Logic", types: ["switch", "loop", "filter", "merge", "wait", "assertion"] },
  { label: "Output", types: ["reply_chat"] },
  { label: "Other", types: ["workflow", "code", "human_confirmation", "error_handler", "output_parser"] },
] as const satisfies readonly { label: string; types: readonly ComponentType[] }[]

/**
 * Every ComponentType must appear in NODE_CATEGORIES above.
 *
 * A type missing here still exists in the API, still renders on the canvas, and
 * still round-trips — it simply can never be *added* from the palette, which
 * looks like the node not existing at all. ICONS is a `Record<ComponentType, …>`
 * so the compiler has always enforced that one; this array was a plain list and
 * drifted unnoticed, which is how `router` sat unreachable from the UI until
 * 2026-08-16. Registering a node type touches five places on the backend and
 * these two on the frontend.
 *
 * If this line errors, the type it names needs a home in a category above.
 *
 * `binary_op` and `binary_auth` are excluded deliberately, NOT because they are
 * unreachable: they have no category of their own because they are added
 * through the per-binary plugin groups below — one entry per (binary, domain)
 * plus an identity entry per binary, each preseeding extra_config.
 */
type PalettedType = (typeof NODE_CATEGORIES)[number]["types"][number]
const _everyTypeIsInThePalette: Exclude<
  BuiltinComponentType,
  PalettedType | "binary_op" | "binary_auth"
> extends never
  ? true
  : Exclude<BuiltinComponentType, PalettedType | "binary_op" | "binary_auth"> = true
void _everyTypeIsInThePalette

function derivedLabel(type: ComponentType): string {
  return type.replace(/^trigger_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function NodePalette({ slug }: { slug: string }) {
  const createNode = useCreateNode(slug)
  // The backend already names every node type. Deriving a label from the
  // component_type string instead produced "Mailbox Action" for a node the
  // registry calls "Mailbox", and "Ai Model" for "AI Model" — the same
  // duplication that let NODE_CATEGORIES drift. Fall back to the derived form
  // only while the registry is still loading.
  const { data: registry } = useNodeTypes()

  // Grouped by binary rather than listed flat: an admin binary's domain and a
  // customer binary's domain are different authorities, and a single "Binaries"
  // heading would leave that difference to be read off the end of a label. One
  // entry per (binary, domain) plus one identity entry per binary — NOT an
  // operation list; the operation is chosen in the details panel, never here.
  // A catalog whose file is unreadable (schema: null) still gets its identity
  // entry: the auth verbs are static and need no catalog.
  const { data: catalogs } = useBinaryCatalogs()
  const binaryGroups = (catalogs?.items ?? []).map((cat) => {
    const operations = (cat.schema?.["x-operations"] ?? {}) as Record<string, { domain?: string }>
    const domains = [...new Set(
      Object.values(operations).map((op) => op.domain).filter((d): d is string => Boolean(d)),
    )].sort()
    return { binary: cat.binary, domains }
  })

  const handleAdd = useCallback((type: ComponentType, extraConfig?: Record<string, unknown>) => {
    createNode.mutate({
      component_type: type,
      position_x: 250,
      position_y: 150,
      // Preseed the binary (and domain) so the node knows whose catalog governs
      // it. Deliberately NO operation: a binary's operations mostly
      // write real customer state — a silently-defaulted operation is a loaded
      // gun. The operation is chosen, visibly, in the details panel.
      ...(extraConfig ? { config: { extra_config: extraConfig } } : {}),
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
                  {registry?.[type]?.display_name ?? derivedLabel(type)}
                </Button>
              )
            })}
          </div>
        </div>
      ))}

      {binaryGroups.map(({ binary, domains }) => (
        <div key={binary}>
          <div className="text-xs font-semibold text-muted-foreground mb-1">{binary}</div>
          <div className="space-y-1">
            {domains.map((domain) => (
              <Button
                key={domain}
                variant="ghost"
                size="sm"
                className="w-full justify-start text-xs gap-2"
                onClick={() => handleAdd("binary_op", { binary, domain })}
                disabled={createNode.isPending}
              >
                <Boxes className="h-3.5 w-3.5 shrink-0" />
                {derivedLabel(domain)}
              </Button>
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-xs gap-2"
              onClick={() => handleAdd("binary_auth", { binary })}
              disabled={createNode.isPending}
            >
              <IdCard className="h-3.5 w-3.5 shrink-0" />
              Identity
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}
