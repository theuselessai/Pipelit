/** Activity step for a tool invocation (nested under parent agent step). */
export interface ActivityToolStep {
  tool_name: string
  tool_node_id: string
  status: "running" | "success" | "failed" | "waiting"
  started_at: number // timestamp ms
  duration_ms?: number
  error?: string
}

/** Activity step for a child execution node (nested under parent agent step). */
export interface ActivityChildStep {
  child_execution_id: string
  node_id: string
  component_type: string
  display_name: string
  status: "running" | "success" | "failed" | "waiting" | "skipped"
  started_at: number // timestamp ms
  duration_ms?: number
  error?: string
}

/** Activity step for a single node execution. */
export interface ActivityStep {
  node_id: string
  component_type: string
  display_name: string
  node_label: string
  status: "running" | "success" | "failed" | "waiting" | "skipped"
  started_at: number // timestamp ms
  duration_ms?: number
  error?: string
  tool_steps: ActivityToolStep[]
  child_steps: ActivityChildStep[]
}

/** Aggregate stats for a completed execution. */
export interface ActivitySummary {
  total_steps: number
  total_duration_ms: number
  total_tokens: number
  total_cost_usd: number
  llm_calls: number
  tool_invocations: number
  child_count?: number
}
