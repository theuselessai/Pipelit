import { useState } from "react"
import { useCredentials, useCreateCredential, useUpdateCredential, useDeleteCredential, useTestCredential, useBatchDeleteCredentials } from "@/api/credentials"
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
import { Plus, Trash2, CheckCircle, XCircle, Loader2, Star } from "lucide-react"
import { format } from "date-fns"
import type { CredentialType } from "@/types/models"

const PAGE_SIZE = 50
const CREDENTIAL_TYPES: CredentialType[] = ["llm", "telegram", "git", "tool"]
const PROVIDER_TYPES = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "glm", label: "GLM (Z.AI)" },
  { value: "openai_compatible", label: "OpenAI Compatible" },
]

export default function CredentialsPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useCredentials({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const credentials = data?.items
  const total = data?.total ?? 0
  const createCredential = useCreateCredential()
  const updateCredential = useUpdateCredential()
  const deleteCredential = useDeleteCredential()
  const testCredential = useTestCredential()
  const batchDelete = useBatchDeleteCredentials()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [credType, setCredType] = useState<CredentialType>("llm")
  const [providerType, setProviderType] = useState("openai_compatible")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [organizationId, setOrganizationId] = useState("")
  const [botToken, setBotToken] = useState("")
  const [toolType, setToolType] = useState("searxng")
  const [toolUrl, setToolUrl] = useState("")
  const [toolPreferred, setToolPreferred] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; error: string } | "loading">>({})
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    let detail: Record<string, unknown> = {}
    if (credType === "llm") detail = { provider_type: providerType, api_key: apiKey, base_url: baseUrl, organization_id: organizationId }
    else if (credType === "telegram") detail = { bot_token: botToken }
    else if (credType === "tool") detail = { tool_type: toolType, config: { url: toolUrl }, is_preferred: toolPreferred }
    await createCredential.mutateAsync({ name, credential_type: credType, detail })
    setOpen(false)
    setName("")
    setApiKey("")
    setBaseUrl("")
    setOrganizationId("")
    setBotToken("")
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
          <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4 mr-2" />Add Credential</Button>
        </div>
      </div>

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
                return (
                  <TableRow key={cred.id}>
                    <TableCell>
                      <Checkbox checked={selectedIds.has(cred.id)} onCheckedChange={() => toggleSelect(cred.id)} />
                    </TableCell>
                    <TableCell className="font-medium">{cred.name}</TableCell>
                    <TableCell><Badge variant="outline">{cred.credential_type}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {cred.credential_type === "llm" && (cred.detail.provider_type as string ?? "")}
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
                            data: { detail: { is_preferred: !(cred.detail as Record<string, unknown>).is_preferred } },
                          })}
                        >
                          <Star className={`h-4 w-4 ${(cred.detail as Record<string, unknown>).is_preferred ? "fill-amber-400 text-amber-400" : "text-muted-foreground"}`} />
                        </Button>
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
                  {CREDENTIAL_TYPES.map((t) => <SelectItem key={t} value={t}>{t.toUpperCase()}</SelectItem>)}
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
            {credType === "telegram" && (
              <div className="space-y-2">
                <Label>Bot Token</Label>
                <Input type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} />
              </div>
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
                  <Input value={toolUrl} onChange={(e) => setToolUrl(e.target.value)} placeholder="http://localhost:8888" />
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
