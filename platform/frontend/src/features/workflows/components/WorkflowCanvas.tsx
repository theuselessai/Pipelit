import { useCallback, useEffect, useMemo } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type OnConnect,
  type OnNodesDelete,
  type OnEdgesDelete,
  type NodeTypes,
  type NodeChange,
  applyNodeChanges,
  Handle,
  Position,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import type { WorkflowDetail, ComponentType } from "@/types/models"
import { useCreateEdge, useDeleteEdge } from "@/api/edges"
import { useUpdateNode, useDeleteNode } from "@/api/nodes"

const COMPONENT_COLORS: Record<string, string> = {
  chat_model: "#3b82f6",
  react_agent: "#8b5cf6",
  plan_and_execute: "#a855f7",
  categorizer: "#f59e0b",
  router: "#f97316",
  tool_node: "#10b981",
  workflow: "#6366f1",
  code: "#64748b",
  http_request: "#06b6d4",
  error_handler: "#ef4444",
  human_confirmation: "#ec4899",
  default: "#94a3b8",
}

function getColor(type: string) {
  return COMPONENT_COLORS[type] || COMPONENT_COLORS.default
}

function WorkflowNodeComponent({ data, selected }: { data: { label: string; componentType: ComponentType; isEntryPoint: boolean }; selected?: boolean }) {
  const color = getColor(data.componentType)
  return (
    <div
      className={`px-3 py-2 rounded-lg border-2 bg-card shadow-sm min-w-[140px] ${selected ? "ring-2 ring-primary" : ""}`}
      style={{ borderColor: color }}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />
      <div className="text-xs font-medium text-muted-foreground" style={{ color }}>{data.componentType}</div>
      <div className="text-sm font-semibold">{data.label}</div>
      {data.isEntryPoint && <div className="text-[10px] text-primary mt-1">Entry Point</div>}
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  )
}

const nodeTypes: NodeTypes = { workflowNode: WorkflowNodeComponent }

interface Props {
  slug: string
  workflow: WorkflowDetail
  selectedNodeId: string | null
  onSelectNode: (id: string | null) => void
}

export default function WorkflowCanvas({ slug, workflow, selectedNodeId, onSelectNode }: Props) {
  const createEdge = useCreateEdge(slug)
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const deleteEdge = useDeleteEdge(slug)

  const initialNodes: Node[] = useMemo(() => workflow.nodes.map((n) => ({
    id: n.node_id,
    type: "workflowNode",
    position: { x: n.position_x, y: n.position_y },
    data: { label: n.node_id, componentType: n.component_type, isEntryPoint: n.is_entry_point },
    selected: n.node_id === selectedNodeId,
  })), [workflow.nodes, selectedNodeId])

  const initialEdges: Edge[] = useMemo(() => workflow.edges.map((e) => ({
    id: String(e.id),
    source: e.source_node_id,
    target: e.target_node_id,
    animated: e.edge_type === "conditional",
    style: { strokeDasharray: e.edge_type === "conditional" ? "5,5" : undefined },
  })), [workflow.edges])

  const [nodes, setNodes] = useNodesState(initialNodes)
  const [edges, setEdges] = useEdgesState(initialEdges)

  useEffect(() => { setNodes(initialNodes) }, [initialNodes, setNodes])
  useEffect(() => { setEdges(initialEdges) }, [initialEdges, setEdges])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
    // Handle selection
    for (const change of changes) {
      if (change.type === "select" && change.selected) {
        onSelectNode(change.id)
      }
    }
  }, [setNodes, onSelectNode])

  const onConnect: OnConnect = useCallback((params) => {
    if (params.source && params.target) {
      createEdge.mutate({ source_node_id: params.source, target_node_id: params.target })
    }
  }, [createEdge])

  const onNodeDragStop = useCallback((_: unknown, node: Node) => {
    updateNode.mutate({ nodeId: node.id, data: { position_x: Math.round(node.position.x), position_y: Math.round(node.position.y) } })
  }, [updateNode])

  const onNodesDelete: OnNodesDelete = useCallback((deleted) => {
    for (const node of deleted) {
      deleteNode.mutate(node.id)
    }
  }, [deleteNode])

  const onEdgesDelete: OnEdgesDelete = useCallback((deleted) => {
    for (const edge of deleted) {
      deleteEdge.mutate(Number(edge.id))
    }
  }, [deleteEdge])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onConnect={onConnect}
      onNodeDragStop={onNodeDragStop}
      onNodesDelete={onNodesDelete}
      onEdgesDelete={onEdgesDelete}
      nodeTypes={nodeTypes}
      fitView
      deleteKeyCode="Delete"
      className="bg-background"
    >
      <Background />
      <Controls />
      <MiniMap />
    </ReactFlow>
  )
}
