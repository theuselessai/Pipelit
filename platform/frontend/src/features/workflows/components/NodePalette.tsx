import { useCreateNode } from "@/api/nodes"
import { Button } from "@/components/ui/button"
import type { ComponentType } from "@/types/models"

const NODE_CATEGORIES: { label: string; types: ComponentType[] }[] = [
  { label: "AI", types: ["chat_model", "react_agent", "plan_and_execute"] },
  { label: "Routing", types: ["categorizer", "router"] },
  { label: "Tools", types: ["tool_node", "http_request"] },
  { label: "Logic", types: ["loop", "parallel", "wait", "merge", "filter", "transform", "sort", "limit"] },
  { label: "Other", types: ["workflow", "code", "human_confirmation", "aggregator", "error_handler", "output_parser"] },
]

export default function NodePalette({ slug }: { slug: string }) {
  const createNode = useCreateNode(slug)

  function handleAdd(type: ComponentType) {
    const nodeId = `${type}_${Date.now().toString(36)}`
    createNode.mutate({
      node_id: nodeId,
      component_type: type,
      position_x: 250,
      position_y: 150,
    })
  }

  return (
    <div className="space-y-4">
      {NODE_CATEGORIES.map((cat) => (
        <div key={cat.label}>
          <div className="text-xs font-semibold text-muted-foreground mb-1">{cat.label}</div>
          <div className="space-y-1">
            {cat.types.map((type) => (
              <Button
                key={type}
                variant="ghost"
                size="sm"
                className="w-full justify-start text-xs"
                onClick={() => handleAdd(type)}
                disabled={createNode.isPending}
              >
                {type.replace(/_/g, " ")}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
