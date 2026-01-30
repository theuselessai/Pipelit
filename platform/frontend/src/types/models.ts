// Component types
export type ComponentType = "categorizer" | "router" | "chat_model" | "react_agent" | "plan_and_execute" | "tool_node" | "aggregator" | "human_confirmation" | "parallel" | "workflow" | "code" | "loop" | "wait" | "merge" | "filter" | "transform" | "sort" | "limit" | "http_request" | "error_handler" | "output_parser"
export type TriggerType = "telegram_message" | "telegram_chat" | "schedule" | "webhook" | "manual" | "workflow" | "error"
export type EdgeType = "direct" | "conditional"
export type CredentialType = "git" | "llm" | "telegram" | "tool"
export type ExecutionStatus = "pending" | "running" | "interrupted" | "completed" | "failed" | "cancelled"

// Workflow
export interface Workflow { id: number; name: string; slug: string; description: string; is_active: boolean; is_public: boolean; is_default: boolean; error_handler_workflow_id: number | null; input_schema: Record<string, unknown> | null; output_schema: Record<string, unknown> | null; node_count: number; edge_count: number; trigger_count: number; created_at: string; updated_at: string }
export interface WorkflowDetail extends Workflow { nodes: WorkflowNode[]; edges: WorkflowEdge[]; triggers: WorkflowTrigger[] }
export interface WorkflowCreate { name: string; slug: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }
export interface WorkflowUpdate { name?: string; slug?: string; description?: string; is_active?: boolean; is_public?: boolean; is_default?: boolean }

// Node
export interface ComponentConfigData { system_prompt: string; extra_config: Record<string, unknown>; llm_model_id: number | null; llm_credential_id: number | null }
export interface WorkflowNode { id: number; node_id: string; component_type: ComponentType; is_entry_point: boolean; interrupt_before: boolean; interrupt_after: boolean; position_x: number; position_y: number; config: ComponentConfigData; subworkflow_id: number | null; code_block_id: number | null; updated_at: string }
export interface NodeCreate { node_id: string; component_type: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }
export interface NodeUpdate { node_id?: string; component_type?: ComponentType; is_entry_point?: boolean; interrupt_before?: boolean; interrupt_after?: boolean; position_x?: number; position_y?: number; config?: Partial<ComponentConfigData>; subworkflow_id?: number | null; code_block_id?: number | null }

// Edge
export interface WorkflowEdge { id: number; source_node_id: string; target_node_id: string; edge_type: EdgeType; condition_mapping: Record<string, unknown> | null; priority: number }
export interface EdgeCreate { source_node_id: string; target_node_id: string; edge_type?: EdgeType; condition_mapping?: Record<string, unknown> | null; priority?: number }
export interface EdgeUpdate { source_node_id?: string; target_node_id?: string; edge_type?: EdgeType; condition_mapping?: Record<string, unknown> | null; priority?: number }

// Trigger
export interface WorkflowTrigger { id: number; trigger_type: TriggerType; credential_id: number | null; config: Record<string, unknown>; is_active: boolean; priority: number; created_at: string }
export interface TriggerCreate { trigger_type: TriggerType; credential_id?: number | null; config?: Record<string, unknown>; is_active?: boolean; priority?: number }
export interface TriggerUpdate { trigger_type?: TriggerType; credential_id?: number | null; config?: Record<string, unknown>; is_active?: boolean; priority?: number }

// Execution
export interface Execution { execution_id: string; workflow_slug: string; status: ExecutionStatus; error_message: string; started_at: string | null; completed_at: string | null }
export interface ExecutionLog { id: number; node_id: string; status: string; input: unknown; output: unknown; error: string; duration_ms: number; timestamp: string }
export interface ExecutionDetail extends Execution { final_output: unknown; trigger_payload: unknown; logs: ExecutionLog[] }

// Credential
export interface Credential { id: number; name: string; credential_type: CredentialType; detail: Record<string, unknown>; created_at: string; updated_at: string }
export interface CredentialCreate { name: string; credential_type: CredentialType; detail?: Record<string, unknown> }
export interface CredentialUpdate { name?: string; detail?: Record<string, unknown> }

// LLM
export interface LLMProvider { id: number; name: string; provider_type: string }
export interface LLMModel { id: number; provider_id: number; provider_name: string; model_name: string; default_temperature: number; context_window: number }
