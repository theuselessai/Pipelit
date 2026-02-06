import { useParams } from "react-router-dom"
import { useWorkflow } from "@/api/workflows"
import WorkflowCanvas from "./components/WorkflowCanvas"
import NodePalette from "./components/NodePalette"
import NodeDetailsPanel from "./components/NodeDetailsPanel"
import { useState } from "react"
import { useSubscription } from "@/hooks/useWebSocket"

export default function WorkflowEditorPage() {
  const { slug } = useParams<{ slug: string }>()
  const { data: workflow, isLoading } = useWorkflow(slug!)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [chatNodeId, setChatNodeId] = useState<string | null>(null)
  useSubscription(slug ? `workflow:${slug}` : null)

  if (isLoading || !workflow) {
    return <div className="flex items-center justify-center h-full"><div className="animate-pulse text-muted-foreground">Loading workflow...</div></div>
  }

  const selectedNode = workflow.nodes.find((n) => n.node_id === selectedNodeId)
  const chatNode = workflow.nodes.find((n) => n.node_id === chatNodeId)

  // Handle double-click - open chat panel for trigger_chat nodes
  const handleNodeDoubleClick = (nodeId: string) => {
    const node = workflow.nodes.find((n) => n.node_id === nodeId)
    if (node?.component_type === "trigger_chat") {
      setChatNodeId(nodeId)
    }
  }

  // Determine which node to show in details panel
  // For trigger_chat, only show when double-clicked (chatNodeId), not when selected
  const detailsNode = chatNode || selectedNode

  return (
    <div className="flex h-full">
      {/* Left: Palette */}
      <div className="w-60 border-r flex flex-col overflow-auto p-2">
        <NodePalette slug={slug!} />
      </div>

      {/* Center: Canvas */}
      <div className="flex-1 h-full">
        <WorkflowCanvas
          slug={slug!}
          workflow={workflow}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          onNodeDoubleClick={handleNodeDoubleClick}
        />
      </div>

      {/* Right: Details */}
      {detailsNode && (
        <div className="w-80 border-l overflow-auto">
          <NodeDetailsPanel
            slug={slug!}
            node={detailsNode}
            workflow={workflow}
            onClose={() => {
              if (chatNodeId) setChatNodeId(null)
              else setSelectedNodeId(null)
            }}
          />
        </div>
      )}
    </div>
  )
}
