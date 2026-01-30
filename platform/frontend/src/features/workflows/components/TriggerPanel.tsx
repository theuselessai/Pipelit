import { useState } from "react"
import { useCreateTrigger, useDeleteTrigger } from "@/api/triggers"
import { useCredentials } from "@/api/credentials"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Plus, Trash2 } from "lucide-react"
import type { WorkflowTrigger, TriggerType } from "@/types/models"

const TRIGGER_TYPES: TriggerType[] = ["telegram_message", "telegram_chat", "schedule", "webhook", "manual", "workflow", "error"]

interface Props {
  slug: string
  triggers: WorkflowTrigger[]
}

export default function TriggerPanel({ slug, triggers }: Props) {
  const createTrigger = useCreateTrigger(slug)
  const deleteTrigger = useDeleteTrigger(slug)
  const { data: credentials } = useCredentials()
  const [adding, setAdding] = useState(false)
  const [triggerType, setTriggerType] = useState<TriggerType>("manual")
  const [credentialId, setCredentialId] = useState("")
  const [config, setConfig] = useState("{}")

  async function handleAdd() {
    let parsedConfig = {}
    try { parsedConfig = JSON.parse(config) } catch { /* keep empty */ }
    await createTrigger.mutateAsync({
      trigger_type: triggerType,
      credential_id: credentialId ? Number(credentialId) : null,
      config: parsedConfig,
    })
    setAdding(false)
    setConfig("{}")
  }

  return (
    <div className="space-y-2">
      {triggers.map((t) => (
        <Card key={t.id} className="p-2">
          <CardContent className="p-0">
            <div className="flex items-center justify-between">
              <div>
                <Badge variant="outline" className="text-[10px]">{t.trigger_type}</Badge>
                <div className="text-[10px] text-muted-foreground mt-1">
                  {t.is_active ? "Active" : "Inactive"}
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => deleteTrigger.mutate(t.id)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}

      {adding ? (
        <div className="space-y-2 border rounded p-2">
          <Select value={triggerType} onValueChange={(v) => setTriggerType(v as TriggerType)}>
            <SelectTrigger className="text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {TRIGGER_TYPES.map((t) => <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={credentialId} onValueChange={setCredentialId}>
            <SelectTrigger className="text-xs"><SelectValue placeholder="Credential (optional)" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">None</SelectItem>
              {credentials?.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Textarea value={config} onChange={(e) => setConfig(e.target.value)} rows={3} className="text-xs font-mono" placeholder="Config JSON" />
          <div className="flex gap-1">
            <Button size="sm" className="flex-1 text-xs" onClick={handleAdd}>Add</Button>
            <Button size="sm" variant="outline" className="text-xs" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" size="sm" className="w-full text-xs" onClick={() => setAdding(true)}>
          <Plus className="h-3 w-3 mr-1" /> Add Trigger
        </Button>
      )}
    </div>
  )
}
