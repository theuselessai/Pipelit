import { useParams } from "react-router-dom"
import { useWorkflow } from "@/api/workflows"
import WorkflowCanvas from "./components/WorkflowCanvas"
import NodePalette from "./components/NodePalette"
import NodeDetailsPanel from "./components/NodeDetailsPanel"
import { useState } from "react"

export default function WorkflowEditorPage() {
  const { slug } = useParams<{ slug: string }>()
  const { data: workflow, isLoading } = useWorkflow(slug!)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  if (isLoading || !workflow) {
    return <div className="flex items-center justify-center h-full"><div className="animate-pulse text-muted-foreground">Loading workflow...</div></div>
  }

  const selectedNode = workflow.nodes.find((n) => n.node_id === selectedNodeId)

  return (
    <div className="flex h-full">
      {/* Left: Palette */}
      <div className="w-60 border-r flex flex-col overflow-auto p-2">
        <NodePalette slug={slug!} />
      </div>

      {/* Center: Canvas */}
      <div className="flex-1">
        <WorkflowCanvas
          slug={slug!}
          workflow={workflow}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
        />
      </div>

      {/* Right: Details */}
      {selectedNode && (
        <div className="w-80 border-l overflow-auto">
          <NodeDetailsPanel slug={slug!} node={selectedNode} onClose={() => setSelectedNodeId(null)} />
        </div>
      )}
    </div>
  )
}
