// Component types
export type ComponentType = "categorizer" | "router" | "extractor" | "ai_model" | "agent" | "switch" | "run_command" | "http_request" | "web_search" | "calculator" | "datetime" | "create_agent_user" | "get_totp_code" | "platform_api" | "whoami" | "epic_tools" | "task_tools" | "scheduler_tools" | "system_health" | "spawn_and_await" | "workflow_create" | "workflow_discover" | "aggregator" | "human_confirmation" | "workflow" | "code" | "code_execute" | "loop" | "wait" | "merge" | "filter" | "error_handler" | "output_parser" | "memory_read" | "memory_write" | "identify_user" | "trigger_telegram" | "trigger_schedule" | "trigger_manual" | "trigger_workflow" | "trigger_error" | "trigger_chat"
export type EdgeType = "direct" | "conditional"
// "memory" was removed — migration 0d301d48b86a converts all memory edges to tool edges.
export type EdgeLabel = "" | "llm" | "tool" | "output_parser" | "loop_body" | "loop_return"
export type CredentialType = "git" | "llm" | "telegram" | "tool"
export type ExecutionStatus = "pending" | "running" | "interrupted" | "completed" | "failed" | "cancelled"

// Workflow
export interface Workflow { id: number; name: string; slug: string; description: string; is_active: boolean; is_public: boolean; is_default: boolean; error_handler_workflow_id: number | null; input_schema: Record<string, unknown> | null; output_schema: Record<string, unknown> | null; node_count: number; edge_count: number; trigger_count: number; created_at: string; updated_at: string }
export interface WorkflowDetail extends Workflow { nodes: WorkflowNode[]; edges: WorkflowEdge[] }
export interface WorkflowCreate { name: string; slug: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }
export interface WorkflowUpdate { name?: string; slug?: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }

// Node
export interface ComponentConfigData { system_prompt: string; extra_config: Record<string, unknown>; llm_credential_id: number | null; model_name: string; temperature: number | null; max_tokens: number | null; frequency_penalty: number | null; presence_penalty: number | null; top_p: number | null; timeout: number | null; max_retries: number | null; response_format: Record<string, unknown> | null; credential_id: number | null; is_active: boolean; priority: number; trigger_config: Record<string, unknown> }
export interface ScheduleJobInfo { id: string; status: string; run_count: number; error_count: number; current_repeat: number; current_retry: number; total_repeats: number; max_retries: number; timeout_seconds: number; interval_seconds: number; last_run_at: string | null; next_run_at: string | null; last_error: string | null; created_at: string | null }
export interface WorkflowNode { id: number; node_id: string; label: string | null; component_type: ComponentType; is_entry_point: boolean; interrupt_before: boolean; interrupt_after: boolean; position_x: number; position_y: number; config: ComponentConfigData; subworkflow_id: number | null; code_block_id: number | null; updated_at: string; schedule_job?: ScheduleJobInfo | null }
// node_id is intentionally optional — backend auto-generates "{type}_{hex}" when omitted.
// WorkflowNode.node_id is always present (populated after creation).
export interface NodeCreate { node_id?: string; label?: string | null; component_type: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }
export interface NodeUpdate { node_id?: string; label?: string | null; component_type?: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }

// Edge
export interface WorkflowEdge { id: number; source_node_id: string; target_node_id: string; edge_type: EdgeType; edge_label: EdgeLabel; condition_mapping: Record<string, unknown> | null; condition_value: string; priority: number }
export interface EdgeCreate { source_node_id: string; target_node_id: string; edge_type?: EdgeType; edge_label?: EdgeLabel; condition_mapping?: Record<string, unknown> | null; condition_value?: string; priority?: number }
export interface EdgeUpdate { source_node_id?: string; target_node_id?: string; edge_type?: EdgeType; edge_label?: EdgeLabel; condition_mapping?: Record<string, unknown> | null; condition_value?: string; priority?: number }

// Execution
export interface Execution { execution_id: string; workflow_slug: string; status: ExecutionStatus; error_message: string; started_at: string | null; completed_at: string | null; total_tokens: number; total_cost_usd: number; llm_calls: number }
export interface ExecutionLog { id: number; node_id: string; status: string; input: unknown; output: unknown; error: string; error_code: string | null; metadata: Record<string, unknown> | null; duration_ms: number; timestamp: string }
export interface ExecutionDetail extends Execution { final_output: unknown; trigger_payload: unknown; logs: ExecutionLog[] }

// Credential
export interface Credential { id: number; name: string; credential_type: CredentialType; detail: Record<string, unknown>; created_at: string; updated_at: string }
export interface CredentialCreate { name: string; credential_type: CredentialType; detail?: Record<string, unknown> }
export interface CredentialUpdate { name?: string; detail?: Record<string, unknown> }

// Credential test/models
// Chat
export interface ChatMessage { role: "user" | "assistant"; text: string; timestamp?: string }
export interface ChatResponse { execution_id: string; status: string; response: string }

export interface CredentialTestResult { ok: boolean; error: string }
export interface CredentialModel { id: string; name: string }

// Memory
export interface MemoryFact { id: string; scope: string; agent_id: string | null; user_id: string | null; key: string; value: unknown; fact_type: string; confidence: number; times_confirmed: number; access_count: number; created_at: string; updated_at: string }
export interface MemoryEpisode { id: string; agent_id: string; user_id: string | null; trigger_type: string; success: boolean; error_code: string | null; summary: string | null; started_at: string; ended_at: string | null; duration_ms: number | null; created_at: string }
export interface MemoryProcedure { id: string; agent_id: string; name: string; description: string; procedure_type: string; times_used: number; times_succeeded: number; times_failed: number; success_rate: number; is_active: boolean; created_at: string }
export interface MemoryUser { id: string; canonical_id: string; display_name: string | null; telegram_id: string | null; email: string | null; total_conversations: number; last_seen_at: string; created_at: string }

// Agent Users
export interface AgentUser { id: number; username: string; purpose: string; api_key_preview: string; created_at: string; created_by: string | null }

// Paginated response
export interface PaginatedResponse<T> { items: T[]; total: number }

// Switch rules
export interface SwitchRule { id: string; field: string; operator: string; value: string; label: string }

// Filter rules
export interface FilterRule { id: string; field: string; operator: string; value: string }

// Checkpoints
export interface Checkpoint { thread_id: string; checkpoint_ns: string; checkpoint_id: string; parent_checkpoint_id: string | null; step: number | null; source: string | null; blob_size: number }

// Epic status + types
export type EpicStatus = "planning" | "active" | "paused" | "completed" | "failed" | "cancelled"
export type TaskStatus = "pending" | "blocked" | "running" | "completed" | "failed" | "cancelled"

export interface Epic {
  id: string; title: string; description: string; tags: string[]
  created_by_node_id: string | null; workflow_id: number | null; user_profile_id: number | null
  status: EpicStatus; priority: number
  budget_tokens: number | null; budget_usd: number | null
  spent_tokens: number; spent_usd: number
  agent_overhead_tokens: number; agent_overhead_usd: number
  total_tasks: number; completed_tasks: number; failed_tasks: number
  created_at: string | null; updated_at: string | null; completed_at: string | null
  result_summary: string | null
}

export interface Task {
  id: string; epic_id: string; title: string; description: string; tags: string[]
  created_by_node_id: string | null; status: TaskStatus; priority: number
  workflow_id: number | null; workflow_slug: string | null
  execution_id: string | null; workflow_source: string
  depends_on: string[]; requirements: Record<string, unknown> | null
  estimated_tokens: number | null; actual_tokens: number; actual_usd: number
  llm_calls: number; tool_invocations: number; duration_ms: number
  created_at: string | null; updated_at: string | null
  started_at: string | null; completed_at: string | null
  result_summary: string | null; error_message: string | null
  retry_count: number; max_retries: number; notes: unknown[]
}

export interface EpicCreate { title: string; description?: string; tags?: string[]; priority?: number; budget_tokens?: number | null; budget_usd?: number | null; workflow_id?: number | null }
export interface EpicUpdate { title?: string; description?: string; tags?: string[]; status?: EpicStatus; priority?: number; budget_tokens?: number | null; budget_usd?: number | null; result_summary?: string | null }
export interface TaskCreate { epic_id: string; title: string; description?: string; tags?: string[]; depends_on?: string[]; priority?: number; workflow_slug?: string | null; estimated_tokens?: number | null; max_retries?: number; requirements?: Record<string, unknown> | null }
export interface TaskUpdate { title?: string; description?: string; tags?: string[]; status?: TaskStatus; priority?: number; workflow_slug?: string | null; execution_id?: string | null; result_summary?: string | null; error_message?: string | null; notes?: unknown[] }
