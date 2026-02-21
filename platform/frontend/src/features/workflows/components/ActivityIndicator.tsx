import { Loader2, Check, X, Minus, ChevronDown, ChevronRight } from "lucide-react"
import type { ActivityStep, ActivityToolStep, ActivityChildStep, ActivitySummary } from "@/types/activity"

/** Human-readable descriptions for tool_name values. */
const TOOL_DESCRIPTIONS: Record<string, string> = {
  web_search: "Searching the web",
  run_command: "Running command",
  http_request: "Making HTTP request",
  calculator: "Calculating",
  datetime: "Getting date/time",
  memory_read: "Reading memory",
  memory_write: "Writing memory",
  spawn_and_await: "Spawning child workflows",
}

function getToolDescription(toolName: string): string {
  return TOOL_DESCRIPTIONS[toolName] || `Using ${toolName}`
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3 w-3 animate-spin text-blue-500 shrink-0" />
    case "success":
      return <Check className="h-3 w-3 text-emerald-500 shrink-0" />
    case "failed":
      return <X className="h-3 w-3 text-red-500 shrink-0" />
    case "waiting":
      return <Loader2 className="h-3 w-3 animate-spin text-amber-500 shrink-0" />
    default:
      return <Minus className="h-3 w-3 text-muted-foreground shrink-0" />
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function ToolStepRow({ step }: { step: ActivityToolStep }) {
  return (
    <div className="flex items-center gap-1.5 pl-5 py-0.5">
      <StatusIcon status={step.status} />
      <span className="text-[11px] text-muted-foreground">
        {getToolDescription(step.tool_name)}
      </span>
      {step.duration_ms != null && step.status !== "running" && step.status !== "waiting" && (
        <span className="text-[10px] text-muted-foreground/70">({formatDuration(step.duration_ms)})</span>
      )}
      {step.error && (
        <span className="text-[10px] text-red-400 truncate max-w-[200px]">{step.error}</span>
      )}
    </div>
  )
}

function ChildStepRow({ step }: { step: ActivityChildStep }) {
  return (
    <div className="flex items-center gap-1.5 pl-7 py-0.5">
      <StatusIcon status={step.status} />
      <span className="text-[11px] text-muted-foreground">
        {step.display_name || step.node_id}
      </span>
      {step.duration_ms != null && step.status !== "running" && step.status !== "waiting" && (
        <span className="text-[10px] text-muted-foreground/70">({formatDuration(step.duration_ms)})</span>
      )}
      {step.error && (
        <span className="text-[10px] text-red-400 truncate max-w-[200px]">{step.error}</span>
      )}
    </div>
  )
}

function StepRow({ step }: { step: ActivityStep }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 py-0.5">
        <StatusIcon status={step.status} />
        <span className="text-xs">{step.display_name}</span>
        {step.duration_ms != null && step.status !== "running" && step.status !== "waiting" && (
          <span className="text-[10px] text-muted-foreground">({formatDuration(step.duration_ms)})</span>
        )}
        {step.error && (
          <span className="text-[10px] text-red-400 truncate max-w-[200px]">{step.error}</span>
        )}
      </div>
      {step.tool_steps.map((ts) => (
        <ToolStepRow key={`${ts.tool_node_id}-${ts.started_at}`} step={ts} />
      ))}
      {step.child_steps.length > 0 && (
        <div className="border-l border-amber-500/30 ml-1.5 pl-1">
          {step.child_steps.map((cs) => (
            <ChildStepRow key={`${cs.child_execution_id}-${cs.node_id}`} step={cs} />
          ))}
        </div>
      )}
    </div>
  )
}

interface Props {
  steps: ActivityStep[]
  summary: ActivitySummary | null
  expanded: boolean
  onToggle: () => void
}

export default function ActivityIndicator({ steps, summary, expanded, onToggle }: Props) {
  if (steps.length === 0) return null

  const isRunning = steps.some(
    (s) =>
      s.status === "running" ||
      s.status === "waiting" ||
      s.tool_steps.some((ts) => ts.status === "running" || ts.status === "waiting") ||
      s.child_steps.some((cs) => cs.status === "running" || cs.status === "waiting")
  )

  // Build summary line
  let summaryLine: string
  if (summary) {
    const childSuffix = summary.child_count ? ` \u00b7 ${summary.child_count} child${summary.child_count !== 1 ? "ren" : ""}` : ""
    summaryLine = `${summary.total_steps} step${summary.total_steps !== 1 ? "s" : ""} \u00b7 ${formatDuration(summary.total_duration_ms)}${summary.total_tokens > 0 ? ` \u00b7 ${formatTokens(summary.total_tokens)} tok` : ""}${childSuffix}`
  } else {
    summaryLine = `${steps.length} step${steps.length !== 1 ? "s" : ""}${isRunning ? " \u00b7 running..." : ""}`
  }

  return (
    <div className="flex justify-start">
      <div className="bg-muted/50 rounded-lg px-3 py-1.5 max-w-[85%]">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors w-full"
        >
          {expanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
          {isRunning && <Loader2 className="h-3 w-3 animate-spin shrink-0" />}
          <span>{summaryLine}</span>
        </button>
        {expanded && (
          <div className="mt-1 space-y-0.5">
            {steps.map((step) => (
              <StepRow key={step.node_id} step={step} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
