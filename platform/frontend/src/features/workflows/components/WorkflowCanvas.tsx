import { useCallback, useEffect, useMemo, useState } from "react"
import { useTheme } from "@/hooks/useTheme"
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome"
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core"
import {
  faMicrochip, faRobot, faTags, faCodeBranch, faWrench, faMagnifyingGlassChart, faBrain,
  faSitemap, faCode, faGlobe, faTriangleExclamation, faUserCheck, faLayerGroup,
  faFileExport, faRepeat, faGripVertical, faClock, faCodeMerge, faFilter,
  faArrowsRotate, faArrowUpAZ, faGauge, faBolt, faCalendarDays, faHandPointer,
  faPlay, faBug, faComments, faCircleNotch, faCircleCheck, faCircleXmark, faMinus,
  faTerminal, faMagnifyingGlass, faCalculator, faUserPlus, faPlug, faFingerprint,
  faDatabase, faFloppyDisk, faIdCard, faLaptopCode,
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
  agent: "#8b5cf6",
  categorizer: "#8b5cf6",
  router: "#8b5cf6",
  extractor: "#8b5cf6",
  run_command: "#10b981",
  http_request: "#10b981",
  web_search: "#10b981",
  calculator: "#10b981",
  datetime: "#10b981",
  create_agent_user: "#14b8a6",
  platform_api: "#14b8a6",
  whoami: "#14b8a6",
  workflow: "#6366f1",
  code: "#64748b",
  code_execute: "#10b981",
  memory_read: "#f59e0b",
  memory_write: "#f59e0b",
  identify_user: "#0ea5e9",
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
  ai_model: faMicrochip, agent: faRobot,
  categorizer: faTags, router: faCodeBranch, extractor: faMagnifyingGlassChart,
  run_command: faTerminal, http_request: faGlobe, web_search: faMagnifyingGlass, calculator: faCalculator, datetime: faClock,
  create_agent_user: faUserPlus, platform_api: faPlug, whoami: faFingerprint,
  workflow: faSitemap,
  code: faCode, code_execute: faLaptopCode, error_handler: faTriangleExclamation,
  memory_read: faDatabase, memory_write: faFloppyDisk, identify_user: faIdCard,
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
  const iconColor = getColor(data.componentType)
  const isRunning = data.executionStatus === "running"
  const isTrigger = data.componentType.startsWith("trigger_")
  const isFixedWidth = ["router", "categorizer", "agent", "extractor"].includes(data.componentType)
  const isTool = ["run_command", "http_request", "web_search", "calculator", "datetime", "memory_read", "memory_write", "code_execute", "create_agent_user", "platform_api", "whoami"].includes(data.componentType)
  const isSubComponent = ["ai_model", "run_command", "http_request", "web_search", "calculator", "datetime", "output_parser", "memory_read", "memory_write", "code_execute", "create_agent_user", "platform_api", "whoami"].includes(data.componentType)
  const isAiModel = data.componentType === "ai_model"
  const hasModel = ["agent", "categorizer", "router", "extractor"].includes(data.componentType)
  const hasTools = ["agent"].includes(data.componentType)
  const hasMemory = ["agent", "categorizer", "router", "extractor"].includes(data.componentType)
  const hasOutputParser = ["categorizer", "router", "extractor"].includes(data.componentType)
  const displayType = isAiModel
    ? formatDisplayName(data.providerType || "ai_model")
    : formatDisplayName(isTrigger ? data.componentType.replace("trigger_", "") : data.componentType)
  const displayLabel = data.label.startsWith(data.componentType + "_")
    ? data.label.slice(data.componentType.length + 1)
    : data.label
  const isSuccess = data.executionStatus === "success"
  const isFailed = data.executionStatus === "failed"
  return (
    <div
      className={`relative px-3 py-2 rounded-lg border-2 border-muted-foreground/50 bg-card shadow-sm ${isFixedWidth ? "w-[250px]" : "min-w-[140px]"} ${selected ? "ring-2 ring-primary" : ""}`}
    >
      {!isTrigger && !isSubComponent && <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />}
      {isSubComponent && <Handle type="source" position={Position.Top} className="!bg-muted-foreground !w-2 !h-2 !rounded-none !rotate-45" />}
      {data.executable !== false && (
        <div
          className={`absolute rounded-sm border flex items-center justify-center ${isTool ? "bottom-[5px] right-[5px]" : "top-1.5 right-1.5"}`}
          style={{
            borderColor: isRunning ? NODE_STATUS_COLORS.running : isSuccess ? NODE_STATUS_COLORS.success : isFailed ? NODE_STATUS_COLORS.failed : "#94a3b8",
            width: isTool ? 14 : 20,
            height: isTool ? 14 : 20,
          }}
        >
          {isRunning
            ? <FontAwesomeIcon icon={faCircleNotch} className="animate-spin" style={{ color: NODE_STATUS_COLORS.running, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
            : isSuccess
            ? <FontAwesomeIcon icon={faCircleCheck} style={{ color: NODE_STATUS_COLORS.success, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
            : isFailed
            ? <FontAwesomeIcon icon={faCircleXmark} style={{ color: NODE_STATUS_COLORS.failed, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
            : <FontAwesomeIcon icon={faMinus} className="opacity-40" style={{ color: "#94a3b8", width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
          }
        </div>
      )}
      <div className="flex items-center gap-2">
        {COMPONENT_ICONS[data.componentType] && (
          <FontAwesomeIcon icon={COMPONENT_ICONS[data.componentType]} className="w-5 h-5 shrink-0" style={{ color: iconColor }} />
        )}
        <div>
          <div className="text-xs font-medium text-muted-foreground">{displayType}</div>
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
  onNodeDoubleClick?: (nodeId: string) => void
}

export default function WorkflowCanvas({ slug, workflow, selectedNodeId, onSelectNode, onNodeDoubleClick }: Props) {
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
      if (msg.type === "execution_started") {
        // Reset all node statuses when a new execution starts
        setNodeStatuses({})
      } else if (msg.type === "node_status" && msg.data) {
        const nodeId = msg.data.node_id as string
        const status = msg.data.status as NodeStatus
        if (nodeId && status) {
          setNodeStatuses((prev) => ({ ...prev, [nodeId]: status }))
        }
      }
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
    const LABEL_TO_HANDLE: Record<string, string> = { llm: "model", tool: "tools", memory: "memory", output_parser: "output_parser" }
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
      },
    }
  }), [workflow.edges])

  const [nodes, setNodes] = useNodesState(initialNodes)
  const [edges, setEdges] = useEdgesState(initialEdges)

  useEffect(() => { setNodes(initialNodes) }, [initialNodes, setNodes])
  useEffect(() => { setEdges(initialEdges) }, [initialEdges, setEdges])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
    // Handle selection - skip trigger_chat (opens on double-click)
    for (const change of changes) {
      if (change.type === "select" && change.selected) {
        const node = workflow.nodes.find((n) => n.node_id === change.id)
        if (node?.component_type !== "trigger_chat") {
          onSelectNode(change.id)
        }
      }
    }
  }, [setNodes, onSelectNode, workflow.nodes])

  const handleNodeDoubleClick = useCallback((_: unknown, node: Node) => {
    onNodeDoubleClick?.(node.id)
  }, [onNodeDoubleClick])

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
      onNodeDoubleClick={handleNodeDoubleClick}
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
