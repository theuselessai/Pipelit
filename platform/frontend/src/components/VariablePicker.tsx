import { useMemo } from "react"
import { useNodeTypes } from "@/api/workflows"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import type { WorkflowDetail } from "@/types/models"
import type { PortDefinition } from "@/types/nodeIO"

interface VariablePickerProps {
  slug: string
  nodeId: string
  workflow: WorkflowDetail
  onInsert: (expr: string) => void
}

interface UpstreamNode {
  nodeId: string
  componentType: string
  outputs: PortDefinition[]
}

/** BFS backward through direct edges to find all upstream nodes */
function getUpstreamNodes(
  workflow: WorkflowDetail,
  currentNodeId: string,
  nodeTypeRegistry: Record<string, { outputs: PortDefinition[] }>,
): UpstreamNode[] {
  const visited = new Set<string>()
  const queue: string[] = []
  const result: UpstreamNode[] = []

  // Seed with direct parent nodes (via direct/conditional edges, excluding sub-component edges)
  for (const edge of workflow.edges) {
    if (edge.target_node_id === currentNodeId && !edge.edge_label) {
      if (!visited.has(edge.source_node_id)) {
        visited.add(edge.source_node_id)
        queue.push(edge.source_node_id)
      }
    }
  }

  // BFS backward
  while (queue.length > 0) {
    const nid = queue.shift()!
    const node = workflow.nodes.find((n) => n.node_id === nid)
    if (!node) continue

    const spec = nodeTypeRegistry[node.component_type]
    if (spec?.outputs?.length) {
      result.push({
        nodeId: nid,
        componentType: node.component_type,
        outputs: spec.outputs,
      })
    }

    // Continue backward from this node
    for (const edge of workflow.edges) {
      if (edge.target_node_id === nid && !edge.edge_label) {
        if (!visited.has(edge.source_node_id)) {
          visited.add(edge.source_node_id)
          queue.push(edge.source_node_id)
        }
      }
    }
  }

  return result
}

export default function VariablePicker({ slug: _slug, nodeId, workflow, onInsert }: VariablePickerProps) {
  const { data: nodeTypeRegistry } = useNodeTypes()

  const upstreamNodes = useMemo(() => {
    if (!nodeTypeRegistry) return []
    return getUpstreamNodes(workflow, nodeId, nodeTypeRegistry)
  }, [workflow, nodeId, nodeTypeRegistry])

  // Find trigger nodes for trigger pseudo-variables
  const triggerNodes = useMemo(() => {
    return workflow.nodes.filter((n) => n.component_type.startsWith("trigger_"))
  }, [workflow.nodes])

  const hasTrigger = triggerNodes.length > 0

  if (!nodeTypeRegistry) return null
  if (upstreamNodes.length === 0 && !hasTrigger) return null

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-6 px-2 text-xs font-mono" title="Insert variable expression">
          {"{ }"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 max-h-72 overflow-y-auto p-2" align="end">
        <div className="text-xs font-semibold text-muted-foreground mb-2">Insert Variable</div>
        {hasTrigger && (
          <div className="mb-2">
            <div className="text-[10px] font-semibold text-muted-foreground mb-1 uppercase tracking-wider">Trigger</div>
            <button
              className="w-full text-left px-2 py-1 text-xs hover:bg-accent rounded font-mono"
              onClick={() => onInsert("{{ trigger.text }}")}
            >
              trigger.text
            </button>
            <button
              className="w-full text-left px-2 py-1 text-xs hover:bg-accent rounded font-mono"
              onClick={() => onInsert("{{ trigger.payload }}")}
            >
              trigger.payload
            </button>
          </div>
        )}
        {upstreamNodes.map((upstream) => (
          <div key={upstream.nodeId} className="mb-2">
            <div className="text-[10px] font-semibold text-muted-foreground mb-1 uppercase tracking-wider truncate" title={upstream.nodeId}>
              {upstream.nodeId}
            </div>
            {upstream.outputs.map((port) => (
              <button
                key={port.name}
                className="w-full text-left px-2 py-1 text-xs hover:bg-accent rounded font-mono"
                onClick={() => onInsert(`{{ ${upstream.nodeId}.${port.name} }}`)}
              >
                {upstream.nodeId}.{port.name}
                <span className="ml-1 text-muted-foreground">({port.data_type})</span>
              </button>
            ))}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  )
}
