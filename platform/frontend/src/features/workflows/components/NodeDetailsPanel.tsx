import { useState, useEffect } from "react"
import { useUpdateNode, useDeleteNode } from "@/api/nodes"
import { useLLMModels, useCredentials } from "@/api/credentials"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { X, Trash2 } from "lucide-react"
import type { WorkflowNode } from "@/types/models"

interface Props {
  slug: string
  node: WorkflowNode
  onClose: () => void
}

export default function NodeDetailsPanel({ slug, node, onClose }: Props) {
  const updateNode = useUpdateNode(slug)
  const deleteNode = useDeleteNode(slug)
  const { data: models } = useLLMModels()
  const { data: credentials } = useCredentials()
  const llmCredentials = credentials?.filter((c) => c.credential_type === "llm") ?? []

  const [systemPrompt, setSystemPrompt] = useState(node.config.system_prompt)
  const [extraConfig, setExtraConfig] = useState(JSON.stringify(node.config.extra_config, null, 2))
  const [llmModelId, setLlmModelId] = useState<string>(node.config.llm_model_id?.toString() ?? "")
  const [llmCredentialId, setLlmCredentialId] = useState<string>(node.config.llm_credential_id?.toString() ?? "")
  const [isEntryPoint, setIsEntryPoint] = useState(node.is_entry_point)
  const [interruptBefore, setInterruptBefore] = useState(node.interrupt_before)
  const [interruptAfter, setInterruptAfter] = useState(node.interrupt_after)

  useEffect(() => {
    setSystemPrompt(node.config.system_prompt)
    setExtraConfig(JSON.stringify(node.config.extra_config, null, 2))
    setLlmModelId(node.config.llm_model_id?.toString() ?? "")
    setLlmCredentialId(node.config.llm_credential_id?.toString() ?? "")
    setIsEntryPoint(node.is_entry_point)
    setInterruptBefore(node.interrupt_before)
    setInterruptAfter(node.interrupt_after)
  }, [node])

  const isLLMNode = ["chat_model", "react_agent", "plan_and_execute", "categorizer", "router"].includes(node.component_type)

  function handleSave() {
    let parsedExtra = {}
    try { parsedExtra = JSON.parse(extraConfig) } catch { /* keep empty */ }
    updateNode.mutate({
      nodeId: node.node_id,
      data: {
        is_entry_point: isEntryPoint,
        interrupt_before: interruptBefore,
        interrupt_after: interruptAfter,
        config: {
          system_prompt: systemPrompt,
          extra_config: parsedExtra,
          llm_model_id: llmModelId ? Number(llmModelId) : null,
          llm_credential_id: llmCredentialId ? Number(llmCredentialId) : null,
        },
      },
    })
  }

  function handleDelete() {
    deleteNode.mutate(node.node_id)
    onClose()
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{node.node_id}</h3>
        <Button variant="ghost" size="sm" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>
      <div className="text-xs text-muted-foreground">{node.component_type}</div>

      <Separator />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="text-xs">Entry Point</Label>
          <Switch checked={isEntryPoint} onCheckedChange={setIsEntryPoint} />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt Before</Label>
          <Switch checked={interruptBefore} onCheckedChange={setInterruptBefore} />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Interrupt After</Label>
          <Switch checked={interruptAfter} onCheckedChange={setInterruptAfter} />
        </div>
      </div>

      <Separator />

      {isLLMNode && (
        <>
          <div className="space-y-2">
            <Label className="text-xs">LLM Model</Label>
            <Select value={llmModelId} onValueChange={setLlmModelId}>
              <SelectTrigger><SelectValue placeholder="Select model" /></SelectTrigger>
              <SelectContent>
                {models?.map((m) => (
                  <SelectItem key={m.id} value={String(m.id)}>
                    {m.provider_name}/{m.model_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label className="text-xs">LLM Credential</Label>
            <Select value={llmCredentialId} onValueChange={setLlmCredentialId}>
              <SelectTrigger><SelectValue placeholder="Select credential" /></SelectTrigger>
              <SelectContent>
                {llmCredentials.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      <div className="space-y-2">
        <Label className="text-xs">System Prompt</Label>
        <Textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} rows={6} className="text-xs" />
      </div>

      <div className="space-y-2">
        <Label className="text-xs">Extra Config (JSON)</Label>
        <Textarea value={extraConfig} onChange={(e) => setExtraConfig(e.target.value)} rows={4} className="text-xs font-mono" />
      </div>

      <div className="flex gap-2">
        <Button size="sm" onClick={handleSave} disabled={updateNode.isPending} className="flex-1">Save</Button>
        <Button size="sm" variant="destructive" onClick={handleDelete}><Trash2 className="h-4 w-4" /></Button>
      </div>
    </div>
  )
}
