import { useState } from "react"
import { Link } from "react-router-dom"
import { useCredentials, useCreateCredential, useUpdateCredential, useDeleteCredential, useTestCredential, useBatchDeleteCredentials, useActivateCredential, useDeactivateCredential } from "@/api/credentials"
import { useAvailableModels } from "@/api/available_models"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Plus, Trash2, CheckCircle, XCircle, Loader2, Star, Power, PowerOff, Info } from "lucide-react"
import { format } from "date-fns"
import type { CredentialType } from "@/types/models"

const PAGE_SIZE = 50
const ALL_CREDENTIAL_TYPES: CredentialType[] = ["llm", "gateway", "git", "tool"]
const PROVIDER_TYPES = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "glm", label: "GLM (Z.AI)" },
  { value: "openai_compatible", label: "OpenAI Compatible" },
]

export default function CredentialsPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useCredentials({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const { data: availableModels } = useAvailableModels()
  const agentgatewayEnabled = (availableModels?.length ?? 0) > 0
  const credentialTypes = agentgatewayEnabled
    ? ALL_CREDENTIAL_TYPES.filter((t) => t !== "llm")
    : ALL_CREDENTIAL_TYPES
  const credentials = data?.items
  const total = data?.total ?? 0
  const createCredential = useCreateCredential()
  const updateCredential = useUpdateCredential()
  const deleteCredential = useDeleteCredential()
  const testCredential = useTestCredential()
  const batchDelete = useBatchDeleteCredentials()
  const activateCredential = useActivateCredential()
  const deactivateCredential = useDeactivateCredential()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [credType, setCredType] = useState<CredentialType>("llm")
  const [providerType, setProviderType] = useState("openai_compatible")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [organizationId, setOrganizationId] = useState("")
  const [toolType, setToolType] = useState("searxng")
  const [toolUrl, setToolUrl] = useState("")
  const [toolPreferred, setToolPreferred] = useState(false)
  const [gatewayAdapterType, setGatewayAdapterType] = useState("telegram")
  const [gatewayToken, setGatewayToken] = useState("")
  const [gatewayConfig, setGatewayConfig] = useState("")
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; error: string } | "loading">>({})
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (credType === "tool" && !toolUrl.trim()) {
      return // URL is required
    }
    let detail: Record<string, unknown> = {}
    if (credType === "llm") detail = { provider_type: providerType, api_key: apiKey, base_url: baseUrl, organization_id: organizationId }
    else if (credType === "gateway") {
      detail = { adapter_type: gatewayAdapterType, token: gatewayToken }
      if (gatewayConfig.trim()) {
        try {
          detail.config = JSON.parse(gatewayConfig)
        } catch {
          alert("Invalid JSON in config field")
          return
        }
      }
    }
    else if (credType === "tool") detail = { tool_type: toolType, config: { url: toolUrl }, is_preferred: toolPreferred }
    await createCredential.mutateAsync({ name, credential_type: credType, detail })
    setOpen(false)
    setCredType(agentgatewayEnabled ? "gateway" : "llm")
    setProviderType("openai_compatible")
    setName("")
    setApiKey("")
    setBaseUrl("")
    setOrganizationId("")
    setGatewayAdapterType("telegram")
    setGatewayToken("")
    setGatewayConfig("")
    setToolType("searxng")
    setToolUrl("")
    setToolPreferred(false)
  }

  async function handleTest(id: number) {
    setTestResults((prev) => ({ ...prev, [id]: "loading" }))
    try {
      const result = await testCredential.mutateAsync(id)
      setTestResults((prev) => ({ ...prev, [id]: result }))
    } catch {
      setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: "Request failed" } }))
    }
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (!credentials) return
    if (selectedIds.size === credentials.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(credentials.map((c) => c.id)))
    }
  }

  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], {
      onSuccess: () => { setSelectedIds(new Set()); setConfirmBatchDelete(false) },
    })
  }

  if (isLoading) {
    return <div className="p-6"><div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" /><div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}</div></div>
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Credentials</h1>
        <div className="flex gap-2">
          {selectedIds.size > 0 && (
            <Button variant="destructive" onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
            </Button>
          )}
          <Button onClick={() => { setCredType(agentgatewayEnabled ? "gateway" : "llm"); setOpen(true) }}><Plus className="h-4 w-4 mr-2" />Add Credential</Button>
        </div>
      </div>

      {agentgatewayEnabled && (
        <div className="flex items-center gap-2 mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
          <Info className="h-4 w-4 shrink-0" />
          <span>
            LLM providers are managed on the{" "}
            <Link to="/providers" className="font-medium underline underline-offset-2">
              Providers page
            </Link>
            .
          </span>
        </div>
      )}

      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={credentials?.length ? selectedIds.size === credentials.length : false} onCheckedChange={toggleAll} />
                </TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Detail</TableHead>
                <TableHead>Created</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {credentials?.map((cred) => {
                const tr = testResults[cred.id]
                const isLlmDimmed = agentgatewayEnabled && cred.credential_type === "llm"
                return (
                  <TableRow key={cred.id} className={isLlmDimmed ? "opacity-50" : undefined}>
                    <TableCell>
                      <Checkbox checked={selectedIds.has(cred.id)} onCheckedChange={() => toggleSelect(cred.id)} />
                    </TableCell>
                    <TableCell className="font-medium">{cred.name}</TableCell>
                    <TableCell><Badge variant="outline">{cred.credential_type}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {cred.credential_type === "llm" && (cred.detail.provider_type as string ?? "")}
                      {cred.credential_type === "gateway" && (cred.detail.adapter_type as string ?? "")}
                      {cred.credential_type === "tool" && (
                        <span className="flex items-center gap-1">
                          {cred.detail.tool_type as string ?? ""}
                          {!!(cred.detail as Record<string, unknown>).is_preferred && (
                            <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
                          )}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{format(new Date(cred.created_at), "MMM d, yyyy")}</TableCell>
                    <TableCell className="flex gap-1">
                      {cred.credential_type === "llm" && (
                        <Button variant="outline" size="sm" onClick={() => handleTest(cred.id)} disabled={tr === "loading"}>
                          {tr === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : tr && typeof tr === "object" ? (tr.ok ? <CheckCircle className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-destructive" />) : "Test"}
                        </Button>
                      )}
                      {cred.credential_type === "tool" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          title={`${(cred.detail as Record<string, unknown>).is_preferred ? "Unset" : "Set"} as preferred`}
                          onClick={() => updateCredential.mutate({
                            id: cred.id,
                            data: { detail: { ...cred.detail, is_preferred: !(cred.detail as Record<string, unknown>).is_preferred } },
                          })}
                        >
                          <Star className={`h-4 w-4 ${(cred.detail as Record<string, unknown>).is_preferred ? "fill-amber-400 text-amber-400" : "text-muted-foreground"}`} />
                        </Button>
                      )}
                      {cred.credential_type === "gateway" && (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Activate"
                            onClick={() => activateCredential.mutate(cred.id)}
                            disabled={activateCredential.isPending}
                          >
                            <Power className="h-4 w-4 text-green-500" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Deactivate"
                            onClick={() => deactivateCredential.mutate(cred.id)}
                            disabled={deactivateCredential.isPending}
                          >
                            <PowerOff className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </>
                      )}
                      <Button variant="ghost" size="sm" onClick={() => setDeleteId(cred.id)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
              {credentials?.length === 0 && (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No credentials yet.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Credential</DialogTitle></DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={credType} onValueChange={(v) => setCredType(v as CredentialType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {credentialTypes.map((t) => <SelectItem key={t} value={t}>{t.toUpperCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {credType === "llm" && (
              <>
                <div className="space-y-2">
                  <Label>Provider Type</Label>
                  <Select value={providerType} onValueChange={setProviderType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PROVIDER_TYPES.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>API Key</Label>
                  <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Base URL (optional)</Label>
                  <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
                </div>
                <div className="space-y-2">
                  <Label>Organization ID (optional)</Label>
                  <Input value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} />
                </div>
              </>
            )}
            {credType === "gateway" && (
              <>
                <div className="space-y-2">
                  <Label>Adapter Type</Label>
                  <Select value={gatewayAdapterType} onValueChange={setGatewayAdapterType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="telegram">Telegram</SelectItem>
                      <SelectItem value="generic">Generic</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Token</Label>
                  <Input type="password" value={gatewayToken} onChange={(e) => setGatewayToken(e.target.value)} required />
                </div>
                <div className="space-y-2">
                  <Label>Config (optional JSON)</Label>
                  <Input value={gatewayConfig} onChange={(e) => setGatewayConfig(e.target.value)} placeholder='{"key": "value"}' />
                </div>
              </>
            )}
            {credType === "tool" && (
              <>
                <div className="space-y-2">
                  <Label>Tool Type</Label>
                  <Select value={toolType} onValueChange={setToolType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="searxng">SearXNG</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>URL</Label>
                  <Input value={toolUrl} onChange={(e) => setToolUrl(e.target.value)} placeholder="http://localhost:8888" required />
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox checked={toolPreferred} onCheckedChange={(v) => setToolPreferred(v === true)} />
                  <Label className="text-sm">Preferred (use this credential when multiple are available)</Label>
                </div>
              </>
            )}
            <DialogFooter>
              <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
              <Button type="submit" disabled={createCredential.isPending}>Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete Credential</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={() => { if (deleteId) { deleteCredential.mutate(deleteId); setDeleteId(null) } }}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Credentials</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedIds.size} credentials? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
