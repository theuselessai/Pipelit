// Component types
export type ComponentType = "categorizer" | "router" | "extractor" | "ai_model" | "agent" | "run_command" | "http_request" | "web_search" | "calculator" | "datetime" | "aggregator" | "human_confirmation" | "parallel" | "workflow" | "code" | "code_execute" | "loop" | "wait" | "merge" | "filter" | "transform" | "sort" | "limit" | "error_handler" | "output_parser" | "memory_read" | "memory_write" | "identify_user" | "trigger_telegram" | "trigger_webhook" | "trigger_schedule" | "trigger_manual" | "trigger_workflow" | "trigger_error" | "trigger_chat"
export type EdgeType = "direct" | "conditional"
export type EdgeLabel = "" | "llm" | "tool" | "memory" | "output_parser"
export type CredentialType = "git" | "llm" | "telegram" | "tool"
export type ExecutionStatus = "pending" | "running" | "interrupted" | "completed" | "failed" | "cancelled"

// Workflow
export interface Workflow { id: number; name: string; slug: string; description: string; is_active: boolean; is_public: boolean; is_default: boolean; error_handler_workflow_id: number | null; input_schema: Record<string, unknown> | null; output_schema: Record<string, unknown> | null; node_count: number; edge_count: number; trigger_count: number; created_at: string; updated_at: string }
export interface WorkflowDetail extends Workflow { nodes: WorkflowNode[]; edges: WorkflowEdge[] }
export interface WorkflowCreate { name: string; slug: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }
export interface WorkflowUpdate { name?: string; slug?: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }

// Node
export interface ComponentConfigData { system_prompt: string; extra_config: Record<string, unknown>; llm_credential_id: number | null; model_name: string; temperature: number | null; max_tokens: number | null; frequency_penalty: number | null; presence_penalty: number | null; top_p: number | null; timeout: number | null; max_retries: number | null; response_format: Record<string, unknown> | null; credential_id: number | null; is_active: boolean; priority: number; trigger_config: Record<string, unknown> }
export interface WorkflowNode { id: number; node_id: string; component_type: ComponentType; is_entry_point: boolean; interrupt_before: boolean; interrupt_after: boolean; position_x: number; position_y: number; config: ComponentConfigData; subworkflow_id: number | null; code_block_id: number | null; updated_at: string }
export interface NodeCreate { node_id: string; component_type: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }
export interface NodeUpdate { node_id?: string; component_type?: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }

// Edge
export interface WorkflowEdge { id: number; source_node_id: string; target_node_id: string; edge_type: EdgeType; edge_label: EdgeLabel; condition_mapping: Record<string, unknown> | null; priority: number }
export interface EdgeCreate { source_node_id: string; target_node_id: string; edge_type?: EdgeType; edge_label?: EdgeLabel; condition_mapping?: Record<string, unknown> | null; priority?: number }
export interface EdgeUpdate { source_node_id?: string; target_node_id?: string; edge_type?: EdgeType; edge_label?: EdgeLabel; condition_mapping?: Record<string, unknown> | null; priority?: number }

// Execution
export interface Execution { execution_id: string; workflow_slug: string; status: ExecutionStatus; error_message: string; started_at: string | null; completed_at: string | null }
export interface ExecutionLog { id: number; node_id: string; status: string; input: unknown; output: unknown; error: string; error_code: string | null; metadata: Record<string, unknown> | null; duration_ms: number; timestamp: string }
export interface ExecutionDetail extends Execution { final_output: unknown; trigger_payload: unknown; logs: ExecutionLog[] }

// Credential
export interface Credential { id: number; name: string; credential_type: CredentialType; detail: Record<string, unknown>; created_at: string; updated_at: string }
export interface CredentialCreate { name: string; credential_type: CredentialType; detail?: Record<string, unknown> }
export interface CredentialUpdate { name?: string; detail?: Record<string, unknown> }

// Credential test/models
// Chat
export interface ChatMessage { role: "user" | "assistant"; text: string }
export interface ChatResponse { execution_id: string; status: string; response: string }

export interface CredentialTestResult { ok: boolean; error: string }
export interface CredentialModel { id: string; name: string }

// Memory
export interface MemoryFact { id: string; scope: string; agent_id: string | null; user_id: string | null; key: string; value: unknown; fact_type: string; confidence: number; times_confirmed: number; access_count: number; created_at: string; updated_at: string }
export interface MemoryEpisode { id: string; agent_id: string; user_id: string | null; trigger_type: string; success: boolean; error_code: string | null; summary: string | null; started_at: string; ended_at: string | null; duration_ms: number | null; created_at: string }
export interface MemoryProcedure { id: string; agent_id: string; name: string; description: string; procedure_type: string; times_used: number; times_succeeded: number; times_failed: number; success_rate: number; is_active: boolean; created_at: string }
export interface MemoryUser { id: string; canonical_id: string; display_name: string | null; telegram_id: string | null; email: string | null; total_conversations: number; last_seen_at: string; created_at: string }
