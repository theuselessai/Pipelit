/** Activity step for a tool invocation (nested under parent agent step). */
export interface ActivityToolStep {
  tool_name: string
  tool_node_id: string
  status: "running" | "success" | "failed"
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
}

/** Aggregate stats for a completed execution. */
export interface ActivitySummary {
  total_steps: number
  total_duration_ms: number
  total_tokens: number
  total_cost_usd: number
  llm_calls: number
  tool_invocations: number
}
