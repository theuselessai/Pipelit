import { useCallback, useEffect, useMemo, useState } from "react"
import { useTheme } from "@/hooks/useTheme"
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome"
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core"
import {
  faMicrochip, faRobot, faTags, faCodeBranch, faWrench, faMagnifyingGlassChart, faBrain,
  faSitemap, faCode, faGlobe, faTriangleExclamation, faUserCheck, faLayerGroup,
  faFileExport, faRepeat, faClock, faCodeMerge, faFilter,
  faBolt, faCalendarDays, faHandPointer, faHourglass,
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
import type { WorkflowDetail, ComponentType, EdgeLabel, SwitchRule } from "@/types/models"
import type { NodeStatus } from "@/types/nodeIO"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
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
  waiting: "#0ea5e9",
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
  switch: "#6366f1",
  loop: "#6366f1",
  filter: "#6366f1",
  merge: "#6366f1",
  wait: "#6366f1",
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
  categorizer: faTags, router: faCodeBranch, switch: faCodeBranch, extractor: faMagnifyingGlassChart,
  run_command: faTerminal, http_request: faGlobe, web_search: faMagnifyingGlass, calculator: faCalculator, datetime: faClock,
  create_agent_user: faUserPlus, platform_api: faPlug, whoami: faFingerprint,
  workflow: faSitemap,
  code: faCode, code_execute: faLaptopCode, error_handler: faTriangleExclamation,
  memory_read: faDatabase, memory_write: faFloppyDisk, identify_user: faIdCard,
  human_confirmation: faUserCheck, aggregator: faLayerGroup, output_parser: faFileExport,
  loop: faRepeat, wait: faClock, merge: faCodeMerge, filter: faFilter,
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

function WorkflowNodeComponent({ data, selected }: { data: { label: string; componentType: ComponentType; isEntryPoint: boolean; modelName?: string; providerType?: string; executionStatus?: NodeStatus; executable?: boolean; rules?: SwitchRule[]; enableFallback?: boolean; nodeOutput?: Record<string, unknown> }; selected?: boolean }) {
  const iconColor = getColor(data.componentType)
  const isRunning = data.executionStatus === "running"
  const isWaiting = data.executionStatus === "waiting"
  const isTrigger = data.componentType.startsWith("trigger_")
  const isLoop = data.componentType === "loop"
  const isFixedWidth = ["router", "categorizer", "agent", "extractor", "switch", "loop"].includes(data.componentType)
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
  const isSwitch = data.componentType === "switch"
  const switchHandles = isSwitch ? (data.rules ?? []) : []
  const showFallbackHandle = isSwitch && data.enableFallback
  return (
    <div
      className={`relative px-3 py-2 rounded-lg border-2 border-muted-foreground/50 bg-card shadow-sm ${isFixedWidth ? "w-[250px]" : "min-w-[140px]"} ${selected ? "ring-2 ring-primary" : ""}`}
    >
      {!isTrigger && !isSubComponent && <Handle type="target" position={Position.Left} className="!bg-muted-foreground !w-2 !h-2" />}
      {isSubComponent && <Handle type="source" position={Position.Top} id="sub-source" className="!bg-muted-foreground !w-2 !h-2 !rounded-none !rotate-45" />}
      {data.executable !== false && (
        <div className={`absolute flex flex-col items-center gap-0.5 ${isTool ? "bottom-[5px] right-[5px]" : "top-1.5 right-1.5"}`}>
          <div
            className="rounded-sm border flex items-center justify-center"
            style={{
              borderColor: isRunning ? NODE_STATUS_COLORS.running : isWaiting ? NODE_STATUS_COLORS.waiting : isSuccess ? NODE_STATUS_COLORS.success : isFailed ? NODE_STATUS_COLORS.failed : "#94a3b8",
              width: isTool ? 14 : 20,
              height: isTool ? 14 : 20,
            }}
          >
            {isRunning
              ? <FontAwesomeIcon icon={faCircleNotch} className="animate-spin" style={{ color: NODE_STATUS_COLORS.running, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
              : isWaiting
              ? <FontAwesomeIcon icon={faHourglass} className="animate-pulse" style={{ color: NODE_STATUS_COLORS.waiting, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
              : isSuccess
              ? <FontAwesomeIcon icon={faCircleCheck} style={{ color: NODE_STATUS_COLORS.success, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
              : isFailed
              ? <FontAwesomeIcon icon={faCircleXmark} style={{ color: NODE_STATUS_COLORS.failed, width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
              : <FontAwesomeIcon icon={faMinus} className="opacity-40" style={{ color: "#94a3b8", width: isTool ? 8 : 10, height: isTool ? 8 : 10 }} />
            }
          </div>
          {isSwitch && (
            <FontAwesomeIcon icon={faCodeBranch} className="text-muted-foreground/70" style={{ width: 8, height: 8, margin: "6px 0" }} title="Conditional routing" />
          )}
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
      {isSuccess && data.nodeOutput && (
        <Popover>
          <PopoverTrigger asChild>
            <button className="text-[10px] text-emerald-500 hover:underline mt-0.5 cursor-pointer">output</button>
          </PopoverTrigger>
          <PopoverContent className="w-80 max-h-64 overflow-auto p-2" align="start">
            <pre className="text-[11px] whitespace-pre-wrap break-all font-mono">{JSON.stringify(data.nodeOutput, null, 2)}</pre>
          </PopoverContent>
        </Popover>
      )}
      {isFailed && data.nodeOutput && (
        <Popover>
          <PopoverTrigger asChild>
            <button className="text-[10px] text-red-500 hover:underline mt-0.5 cursor-pointer">error</button>
          </PopoverTrigger>
          <PopoverContent className="w-80 max-h-64 overflow-auto p-2" align="start">
            <pre className="text-[11px] whitespace-pre-wrap break-all font-mono text-red-500">{JSON.stringify(data.nodeOutput, null, 2)}</pre>
          </PopoverContent>
        </Popover>
      )}
      {isFixedWidth && !isSwitch && !isLoop && <hr className="border-muted-foreground/30 my-1" />}
      {isFixedWidth && !isSwitch && !isLoop && (
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
      {isSwitch && (switchHandles.length > 0 || showFallbackHandle) && (
        <>
          <hr className="border-muted-foreground/30 my-1" />
          <div className="flex flex-col gap-1">
            {switchHandles.map((rule) => (
              <div key={rule.id} className="relative flex items-center justify-end pr-4">
                <span className="text-[10px] text-muted-foreground truncate">{rule.label || rule.id}</span>
                <Handle type="source" position={Position.Right} id={rule.id} className="!bg-indigo-400 !w-2 !h-2" />
              </div>
            ))}
            {showFallbackHandle && (
              <div className="relative flex items-center justify-end pr-4">
                <span className="text-[10px] text-muted-foreground italic">other</span>
                <Handle type="source" position={Position.Right} id="__other__" className="!bg-muted-foreground !w-2 !h-2" />
              </div>
            )}
          </div>
        </>
      )}
      {isLoop && (
        <>
          <hr className="border-muted-foreground/30 my-1" />
          <div className="flex flex-col gap-1">
            <div className="relative flex items-center justify-end pr-4">
              <span className="text-[10px] text-emerald-500 font-medium">Done</span>
              <Handle type="source" position={Position.Right} id="done" className="!bg-emerald-500 !w-2 !h-2" />
            </div>
            <div className="relative flex items-center justify-end pr-4">
              <span className="text-[10px] text-amber-500 font-medium">Each Item</span>
              <Handle type="source" position={Position.Right} id="loop_body" className="!bg-amber-500 !w-2 !h-2" />
            </div>
          </div>
          {/* Return handle on left side, below main input */}
          <Handle
            type="target"
            position={Position.Left}
            id="loop_return"
            className="!bg-amber-500 !w-2 !h-2"
            style={{ top: "auto", bottom: 8 }}
          />
        </>
      )}
      {!isSubComponent && !(isSwitch && (switchHandles.length > 0 || showFallbackHandle)) && !isLoop && <Handle type="source" position={Position.Right} className="!bg-muted-foreground !w-2 !h-2" />}
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

function SmoothStepLabelEdge({
  sourceX, sourceY, targetX, targetY,
  style, label, markerEnd, animated,
}: EdgeProps) {
  // Route below both nodes with rounded 90-degree corners
  const r = 16
  const gap = 30
  const bottomY = Math.max(sourceY, targetY) + 80
  const x1 = sourceX + gap
  const x2 = targetX - gap
  const edgePath = [
    `M ${sourceX},${sourceY}`,
    `L ${x1 - r},${sourceY}`,
    `Q ${x1},${sourceY} ${x1},${sourceY + r}`,
    `L ${x1},${bottomY - r}`,
    `Q ${x1},${bottomY} ${x1 - r},${bottomY}`,
    `L ${x2 + r},${bottomY}`,
    `Q ${x2},${bottomY} ${x2},${bottomY - r}`,
    `L ${x2},${targetY + r}`,
    `Q ${x2},${targetY} ${x2 + r},${targetY}`,
    `L ${targetX},${targetY}`,
  ].join(" ")
  const labelX = (x1 + x2) / 2
  const labelY = bottomY
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
const edgeTypes: EdgeTypes = { deletable: LabelEdge, smoothstep: SmoothStepLabelEdge }

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

  // Track node execution status and outputs from WebSocket events
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatus>>({})
  const [nodeOutputs, setNodeOutputs] = useState<Record<string, Record<string, unknown>>>({})

  useEffect(() => {
    const handlerId = `canvas-node-status-${slug}`
    wsManager.registerHandler(handlerId, (msg) => {
      if (msg.type === "execution_started") {
        // Reset all node statuses and outputs when a new execution starts
        setNodeStatuses({})
        setNodeOutputs({})
      } else if (msg.type === "node_status" && msg.data) {
        const nodeId = msg.data.node_id as string
        const status = msg.data.status as NodeStatus
        if (nodeId && status) {
          setNodeStatuses((prev) => ({ ...prev, [nodeId]: status }))
          // Store output if present (on success), or error info (on failure)
          if (status === "success" && msg.data.output != null) {
            setNodeOutputs((prev) => ({ ...prev, [nodeId]: msg.data!.output as Record<string, unknown> }))
          } else if (status === "failed" && msg.data.error != null) {
            setNodeOutputs((prev) => ({ ...prev, [nodeId]: { error: msg.data!.error, ...(msg.data!.error_code ? { error_code: msg.data!.error_code } : {}) } as Record<string, unknown> }))
          }
        }
      }
    })
    return () => { wsManager.unregisterHandler(handlerId) }
  }, [slug])

  const credentialMap = useMemo(() => {
    const map: Record<number, string> = {}
    for (const c of credentials?.items ?? []) {
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
      data: { label: n.node_id, componentType: n.component_type, isEntryPoint: n.is_entry_point, modelName: n.config?.model_name || undefined, providerType, executionStatus: nodeStatuses[n.node_id], executable: nodeTypeRegistry?.[n.component_type]?.executable, rules: n.component_type === "switch" ? ((n.config?.extra_config?.rules as SwitchRule[]) ?? []) : undefined, enableFallback: n.component_type === "switch" ? Boolean(n.config?.extra_config?.enable_fallback) : false, nodeOutput: nodeOutputs[n.node_id] },
      selected: n.node_id === selectedNodeId,
    }
  }), [workflow.nodes, selectedNodeId, credentialMap, nodeStatuses, nodeOutputs, nodeTypeRegistry])

  const initialEdges: Edge[] = useMemo(() => workflow.edges.map((e) => {
    const LABEL_TO_HANDLE: Record<string, string> = { llm: "model", tool: "tools", memory: "memory", output_parser: "output_parser" }
    const targetHandle = (e.edge_label && e.edge_label !== "loop_body" && e.edge_label !== "loop_return")
      ? LABEL_TO_HANDLE[e.edge_label]
      : e.edge_label === "loop_return" ? "loop_return" : undefined
    const sourceHandle = e.edge_label === "loop_body" ? "loop_body"
      : e.edge_label === "loop_return" ? undefined
      : e.edge_label ? "sub-source"
      : (e.edge_type === "conditional" && e.condition_value) ? e.condition_value
      : (() => {
          // If source is a loop node and this is a direct edge, use "done" handle
          const srcNode = workflow.nodes.find((n) => n.node_id === e.source_node_id)
          return srcNode?.component_type === "loop" ? "done" : undefined
        })()
    // For conditional edge labels, find the rule label from the source switch node
    let condLabel: string | undefined
    if (e.edge_type === "conditional" && e.condition_value) {
      const srcNode = workflow.nodes.find((n) => n.node_id === e.source_node_id)
      if (srcNode?.component_type === "switch") {
        const rules = (srcNode.config?.extra_config?.rules as SwitchRule[]) ?? []
        const rule = rules.find((r) => r.id === e.condition_value)
        condLabel = rule?.label || e.condition_value
      } else {
        condLabel = e.condition_value
      }
    }
    const edgeLabel = e.edge_label === "loop_body" ? "each item"
      : e.edge_label === "loop_return" ? "return"
      : (e.edge_label || condLabel)
    return {
      id: String(e.id),
      type: e.edge_label === "loop_return" ? "smoothstep" : "deletable",
      source: e.source_node_id,
      target: e.target_node_id,
      sourceHandle,
      targetHandle,
      animated: !e.edge_label || e.edge_label === "loop_return",
      label: edgeLabel,
      style: {
        strokeDasharray: (!e.edge_label || e.edge_label === "loop_return") ? "5,5" : undefined,
      },
    }
  }), [workflow.edges, workflow.nodes])

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
      const HANDLE_TO_LABEL: Record<string, EdgeLabel> = { model: "llm", tools: "tool", memory: "memory", output_parser: "output_parser", loop_return: "loop_return" }
      const edge_label = (params.targetHandle && HANDLE_TO_LABEL[params.targetHandle]) || ""

      // Check if source is a loop node with loop_body handle
      const sourceNode = workflow.nodes.find((n) => n.node_id === params.source)
      if (sourceNode?.component_type === "loop" && params.sourceHandle === "loop_body" && !edge_label) {
        createEdge.mutate({
          source_node_id: params.source,
          target_node_id: params.target,
          edge_label: "loop_body",
        })
        return
      }
      if (sourceNode?.component_type === "switch" && !edge_label) {
        // If dragged from a specific rule handle, auto-create conditional edge
        const ruleId = params.sourceHandle
        if (ruleId) {
          createEdge.mutate({
            source_node_id: params.source,
            target_node_id: params.target,
            edge_type: "conditional",
            edge_label,
            condition_value: ruleId,
          })
        } else {
          // No rules configured yet — fall back to manual prompt
          const conditionValue = prompt("Enter condition value for this route (e.g. 'chat', 'research'):")
          if (!conditionValue) return
          createEdge.mutate({
            source_node_id: params.source,
            target_node_id: params.target,
            edge_type: "conditional",
            edge_label,
            condition_value: conditionValue,
          })
        }
      } else {
        createEdge.mutate({ source_node_id: params.source, target_node_id: params.target, edge_label })
      }
    }
  }, [createEdge, workflow.nodes])

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
