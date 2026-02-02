import { useCallback, useEffect, useMemo, useState } from "react"
import { useTheme } from "@/hooks/useTheme"
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome"
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core"
import {
  faMicrochip, faRobot, faDiagramProject, faTags, faCodeBranch, faWrench, faMagnifyingGlassChart, faBrain,
  faSitemap, faCode, faGlobe, faTriangleExclamation, faUserCheck, faLayerGroup,
  faFileExport, faRepeat, faGripVertical, faClock, faCodeMerge, faFilter,
  faArrowsRotate, faArrowUpAZ, faGauge, faBolt, faCalendarDays, faHandPointer,
  faPlay, faBug, faComments, faSpinner, faCircleCheck, faCircleXmark, faCircle,
} from "@fortawesome/free-solid-svg-icons"
import { faTelegram } from "@fortawesome/free-brands-svg-icons"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type Node,
  type Edge,
  type EdgeProps,
  type OnConnect,
  type OnNodesDelete,
  type OnEdgesDelete,
  type NodeTypes,
  type EdgeTypes,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
  applyEdgeChanges,
  Handle,
  Position,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import type { WorkflowDetail, ComponentType, EdgeLabel } from "@/types/models"
import type { NodeStatus } from "@/types/nodeIO"
import { useCreateEdge, useDeleteEdge } from "@/api/edges"
import { useUpdateNode, useDeleteNode } from "@/api/nodes"
import { useCredentials } from "@/api/credentials"
import { useNodeTypes } from "@/api/workflows"
import { wsManager } from "@/lib/wsManager"

const NODE_STATUS_COLORS: Record<NodeStatus, string> = {
  pending: "#94a3b8",
  running: "#3b82f6",
  success: "#10b981",
  failed: "#ef4444",
  skipped: "#f59e0b",
}

const COMPONENT_COLORS: Record<string, string> = {
  ai_model: "#3b82f6",
  simple_agent: "#8b5cf6",
  planner_agent: "#8b5cf6",
  categorizer: "#8b5cf6",
  router: "#8b5cf6",
  extractor: "#8b5cf6",
  tool_node: "#10b981",
  workflow: "#6366f1",
  code: "#64748b",
  http_request: "#06b6d4",
  error_handler: "#ef4444",
  human_confirmation: "#ec4899",
  trigger_telegram: "#f97316",
  trigger_webhook: "#f97316",
  trigger_schedule: "#f97316",
  trigger_manual: "#f97316",
  trigger_workflow: "#f97316",
  trigger_error: "#f97316",
  trigger_chat: "#f97316",
  default: "#94a3b8",
}

const COMPONENT_ICONS: Record<string, IconDefinition> = {
  ai_model: faMicrochip, simple_agent: faRobot, planner_agent: faDiagramProject,
  categorizer: faTags, router: faCodeBranch, extractor: faMagnifyingGlassChart, tool_node: faWrench, workflow: faSitemap,
  code: faCode, http_request: faGlobe, error_handler: faTriangleExclamation,
  human_confirmation: faUserCheck, aggregator: faLayerGroup, output_parser: faFileExport,
  loop: faRepeat, parallel: faGripVertical, wait: faClock, merge: faCodeMerge,
  filter: faFilter, transform: faArrowsRotate, sort: faArrowUpAZ, limit: faGauge,
  trigger_telegram: faTelegram, trigger_webhook: faBolt, trigger_schedule: faCalendarDays,
  trigger_manual: faHandPointer, trigger_workflow: faPlay, trigger_error: faBug,
  trigger_chat: faComments,
}

function formatDisplayName(s: string) {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function getColor(type: string) {
  return COMPONENT_COLORS[type] || COMPONENT_COLORS.default
}

function WorkflowNodeComponent({ data, selected }: { data: { label: string; componentType: ComponentType; isEntryPoint: boolean; modelName?: string; providerType?: string; executionStatus?: NodeStatus; executable?: boolean }; selected?: boolean }) {
  const statusColor = data.executionStatus ? NODE_STATUS_COLORS[data.executionStatus] : undefined
  const color = statusColor || getColor(data.componentType)
  const isTrigger = data.componentType.startsWith("trigger_")
  const isFixedWidth = ["router", "categorizer", "planner_agent", "simple_agent", "extractor"].includes(data.componentType)
  const isSubComponent = ["ai_model", "tool_node", "output_parser"].includes(data.componentType)
  const isAiModel = data.componentType === "ai_model"
  const hasModel = ["simple_agent", "planner_agent", "categorizer", "router", "extractor"].includes(data.componentType)
  const hasTools = ["simple_agent", "planner_agent"].includes(data.componentType)
  const hasMemory = ["simple_agent", "planner_agent", "categorizer", "router", "extractor"].includes(data.componentType)
  const hasOutputParser = ["categorizer", "router", "extractor"].includes(data.componentType)
  const displayType = isAiModel
    ? formatDisplayName(data.providerType || "ai_model")
    : formatDisplayName(isTrigger ? data.componentType.replace("trigger_", "") : data.componentType)
  const displayLabel = data.label.startsWith(data.componentType + "_")
    ? data.label.slice(data.componentType.length + 1)
    : data.label
  const isRunning = data.executionStatus === "running"
  const isSuccess = data.executionStatus === "success"
  const isFailed = data.executionStatus === "failed"
  return (
    <div
      className={`relative px-3 py-2 rounded-lg border-2 bg-card shadow-sm ${isFixedWidth ? "w-[250px]" : "min-w-[140px]"} ${selected ? "ring-2 ring-primary" : ""}`}
      style={{ borderColor: color }}
    >
      {!isTrigger && !isSubComponent && <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />}
      {isSubComponent && <Handle type="source" position={Position.Top} className="!bg-muted-foreground !w-2 !h-2 !rounded-none !rotate-45" />}
      {data.executable !== false && (
        <div className="absolute -top-2 -right-2 rounded-full bg-card p-0.5">
          {isRunning
            ? <FontAwesomeIcon icon={faSpinner} className="w-3.5 h-3.5 animate-spin" style={{ color: NODE_STATUS_COLORS.running }} />
            : isSuccess
            ? <FontAwesomeIcon icon={faCircleCheck} className="w-3.5 h-3.5" style={{ color: NODE_STATUS_COLORS.success }} />
            : isFailed
            ? <FontAwesomeIcon icon={faCircleXmark} className="w-3.5 h-3.5" style={{ color: NODE_STATUS_COLORS.failed }} />
            : <FontAwesomeIcon icon={faCircle} className="w-3.5 h-3.5 opacity-40" style={{ color: "#94a3b8" }} />
          }
        </div>
      )}
      <div className="flex items-center gap-2">
        {COMPONENT_ICONS[data.componentType] && (
          <FontAwesomeIcon icon={COMPONENT_ICONS[data.componentType]} className="w-5 h-5 shrink-0" style={{ color }} />
        )}
        <div>
          <div className="text-xs font-medium text-muted-foreground" style={{ color }}>{displayType}</div>
          <div className="text-sm font-semibold">{isAiModel ? (data.modelName || "undefined") : displayLabel}</div>
        </div>
      </div>
      {data.isEntryPoint && <div className="text-[10px] text-primary mt-1">Entry Point</div>}
      {isFixedWidth && <hr className="border-muted-foreground/30 my-1" />}
      {isFixedWidth && (
        <div className="flex mt-1">
          {hasModel && (
            <div className="relative p-1.5 bg-background rounded-[10px]" style={{ color: "#3b82f6", borderColor: "#3b82f6", borderWidth: 1, borderStyle: "solid" }} title="model">
              <FontAwesomeIcon icon={faMicrochip} className="w-3 h-3" />
              <Handle type="target" position={Position.Bottom} id="model" className="!w-2 !h-2 !rounded-none !rotate-45 !-bottom-1.5" style={{ backgroundColor: "#3b82f6", left: "calc(50% + 1px)" }} />
            </div>
          )}
          <div className="flex gap-1.5 ml-auto">
            {hasTools && (
              <div className="relative p-1.5 bg-background rounded-[10px]" style={{ color: "#10b981", borderColor: "#10b981", borderWidth: 1, borderStyle: "solid" }} title="tools">
                <FontAwesomeIcon icon={faWrench} className="w-3 h-3" />
                <Handle type="target" position={Position.Bottom} id="tools" className="!w-2 !h-2 !rounded-none !rotate-45 !-bottom-1.5" style={{ backgroundColor: "#10b981", left: "calc(50% + 1px)" }} />
              </div>
            )}
            {hasMemory && (
              <div className="relative p-1.5 bg-background rounded-[10px]" style={{ color: "#f59e0b", borderColor: "#f59e0b", borderWidth: 1, borderStyle: "solid" }} title="memory">
                <FontAwesomeIcon icon={faBrain} className="w-3 h-3" />
                <Handle type="target" position={Position.Bottom} id="memory" className="!w-2 !h-2 !rounded-none !rotate-45 !-bottom-1.5" style={{ backgroundColor: "#f59e0b", left: "calc(50% + 1px)" }} />
              </div>
            )}
            {hasOutputParser && (
              <div className="relative p-1.5 bg-background rounded-[10px]" style={{ color: "#94a3b8", borderColor: "#94a3b8", borderWidth: 1, borderStyle: "solid" }} title="output_parser">
                <FontAwesomeIcon icon={faFileExport} className="w-3 h-3" />
                <Handle type="target" position={Position.Bottom} id="output_parser" className="!w-2 !h-2 !rounded-none !rotate-45 !-bottom-1.5" style={{ backgroundColor: "#94a3b8", left: "calc(50% + 1px)" }} />
              </div>
            )}
          </div>
        </div>
      )}
      {!isSubComponent && <Handle type="source" position={Position.Right} className="!bg-muted-foreground !w-2 !h-2" />}
    </div>
  )
}

function LabelEdge({
  sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  style, label, markerEnd, animated,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} className={animated ? "react-flow__edge-animated" : ""} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "none",
            }}
          >
            <span className="text-[10px] bg-background px-1 rounded border">{label}</span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const nodeTypes: NodeTypes = { workflowNode: WorkflowNodeComponent }
const edgeTypes: EdgeTypes = { deletable: LabelEdge }

interface Props {
  slug: string
  workflow: WorkflowDetail
  selectedNodeId: string | null
  onSelectNode: (id: string | null) => void
}

export default function WorkflowCanvas({ slug, workflow, selectedNodeId, onSelectNode }: Props) {
  const { resolvedTheme } = useTheme()
  const createEdge = useCreateEdge(slug)
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const deleteEdge = useDeleteEdge(slug)
  const { data: credentials } = useCredentials()
  const { data: nodeTypeRegistry } = useNodeTypes()

  // Track node execution status from WebSocket events
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatus>>({})

  useEffect(() => {
    const handlerId = `canvas-node-status-${slug}`
    wsManager.registerHandler(handlerId, (msg) => {
      if (msg.type === "node_status" && msg.data) {
        const nodeId = msg.data.node_id as string
        const status = msg.data.status as NodeStatus
        if (nodeId && status) {
          setNodeStatuses((prev) => ({ ...prev, [nodeId]: status }))
        }
      }
      // Don't clear — keep last run results visible
    })
    return () => { wsManager.unregisterHandler(handlerId) }
  }, [slug])

  const credentialMap = useMemo(() => {
    const map: Record<number, string> = {}
    for (const c of credentials ?? []) {
      if (c.credential_type === "llm") {
        map[c.id] = c.name
      }
    }
    return map
  }, [credentials])

  const initialNodes: Node[] = useMemo(() => workflow.nodes.map((n) => {
    const providerType = n.config?.llm_credential_id ? credentialMap[n.config.llm_credential_id] : undefined
    return {
      id: n.node_id,
      type: "workflowNode",
      position: { x: n.position_x, y: n.position_y },
      data: { label: n.node_id, componentType: n.component_type, isEntryPoint: n.is_entry_point, modelName: n.config?.model_name || undefined, providerType, executionStatus: nodeStatuses[n.node_id], executable: nodeTypeRegistry?.[n.component_type]?.executable },
      selected: n.node_id === selectedNodeId,
    }
  }), [workflow.nodes, selectedNodeId, credentialMap, nodeStatuses, nodeTypeRegistry])

  const initialEdges: Edge[] = useMemo(() => workflow.edges.map((e) => {
    const labelColors: Record<string, string> = { tool: "#10b981", memory: "#f59e0b", output_parser: "#8b5cf6" }
    const LABEL_TO_HANDLE: Record<string, string> = { llm: "model", tool: "tools", memory: "memory", output_parser: "output_parser" }
    const edgeColor = e.edge_label ? labelColors[e.edge_label] : undefined
    const targetHandle = e.edge_label ? LABEL_TO_HANDLE[e.edge_label] : undefined
    return {
      id: String(e.id),
      type: "deletable",
      source: e.source_node_id,
      target: e.target_node_id,
      targetHandle,
      animated: e.edge_type === "conditional",
      label: e.edge_label || undefined,
      style: {
        strokeDasharray: e.edge_type === "conditional" ? "5,5" : undefined,
        stroke: edgeColor,
      },
    }
  }), [workflow.edges])

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

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((eds) => applyEdgeChanges(changes, eds))
  }, [setEdges])

  const onConnect: OnConnect = useCallback((params) => {
    if (params.source && params.target) {
      const HANDLE_TO_LABEL: Record<string, EdgeLabel> = { model: "llm", tools: "tool", memory: "memory", output_parser: "output_parser" }
      const edge_label = (params.targetHandle && HANDLE_TO_LABEL[params.targetHandle]) || ""
      createEdge.mutate({ source_node_id: params.source, target_node_id: params.target, edge_label })
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
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onNodeDragStop={onNodeDragStop}
      onNodesDelete={onNodesDelete}
      onEdgesDelete={onEdgesDelete}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      deleteKeyCode={["Delete", "Backspace"]}
      colorMode={resolvedTheme}
      className="bg-background"
    >
      <Background />
      <Controls />
      <MiniMap />
    </ReactFlow>
  )
}
