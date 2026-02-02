// Node I/O types mirroring Python schemas

export type NodeStatus = "pending" | "running" | "success" | "failed" | "skipped"

export interface NodeError {
  code: string
  message: string
  details: Record<string, unknown>
  recoverable: boolean
  node_id: string
}

export interface NodeResult {
  status: NodeStatus
  data: Record<string, unknown>
  error: NodeError | null
  metadata: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
}

export type DataType = "string" | "number" | "boolean" | "object" | "array" | "message" | "messages" | "image" | "file" | "any"

export interface PortDefinition {
  name: string
  data_type: DataType
  description: string
  required: boolean
  default: unknown
}

export interface NodeTypeSpec {
  component_type: string
  display_name: string
  description: string
  category: string
  inputs: PortDefinition[]
  outputs: PortDefinition[]
  requires_model: boolean
  requires_tools: boolean
  requires_memory: boolean
  requires_output_parser: boolean
  executable: boolean
  config_schema: Record<string, unknown>
}

export interface ValidationError {
  errors: string[]
}
