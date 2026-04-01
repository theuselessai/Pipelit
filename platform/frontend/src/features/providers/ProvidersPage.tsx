import { useState } from "react"
import { useProviders, useCreateProvider, useDeleteProvider, useFetchProviderModels, useAddModels, useDeleteModel } from "@/api/providers"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Plus, Trash2, ChevronDown, ChevronRight, Loader2, Download } from "lucide-react"
import { toast } from "sonner"
import type { Provider, FetchedModel } from "@/types/models"

const PROVIDER_TYPES = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openai_compatible", label: "OpenAI Compatible" },
  { value: "glm", label: "GLM (Z.AI)" },
]

function ProviderRow({ provider }: { provider: Provider }) {
  const [expanded, setExpanded] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [addModelsOpen, setAddModelsOpen] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<FetchedModel[]>([])
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set())
  const [fetching, setFetching] = useState(false)

  const deleteProvider = useDeleteProvider()
  const deleteModel = useDeleteModel()
  const addModels = useAddModels()
  const fetchModels = useFetchProviderModels(provider.provider)

  async function handleFetchModels() {
    setFetching(true)
    try {
      const result = await fetchModels.refetch()
      if (result.data) {
        setFetchedModels(result.data)
        setSelectedModels(new Set())
        setAddModelsOpen(true)
      }
    } catch (err) {
      toast.error("Failed to fetch models from provider")
    } finally {
      setFetching(false)
    }
  }

  function toggleModel(id: string) {
    setSelectedModels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  async function handleAddModels() {
    const models = fetchedModels
      .filter((m) => selectedModels.has(m.id))
      .map((m) => ({ slug: m.id.replace(/[^a-zA-Z0-9_-]/g, "-"), model_name: m.id }))
    if (models.length === 0) return
    try {
      await addModels.mutateAsync({ provider: provider.provider, models })
      setAddModelsOpen(false)
      toast.success(`Added ${models.length} model(s)`)
    } catch (err) {
      toast.error("Failed to add models")
    }
  }

  function handleDeleteModel(modelSlug: string) {
    deleteModel.mutate(
      { provider: provider.provider, modelSlug },
      { onSuccess: () => toast.success("Model deleted") },
    )
  }

  function handleDeleteProvider() {
    deleteProvider.mutate(provider.provider, {
      onSuccess: () => { setDeleteConfirm(false); toast.success("Provider deleted") },
    })
  }

  return (
    <>
      <TableRow className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <TableCell className="w-8">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </TableCell>
        <TableCell className="font-medium">{provider.provider}</TableCell>
        <TableCell><Badge variant="outline">{provider.provider_type}</Badge></TableCell>
        <TableCell>{provider.models.length} model(s)</TableCell>
        <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
          <div className="flex gap-1 justify-end">
            <Button variant="outline" size="sm" onClick={handleFetchModels} disabled={fetching}>
              {fetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
              {!fetching && "Fetch Models"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(true)}>
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </TableCell>
      </TableRow>

      {expanded && provider.models.length > 0 && (
        <TableRow>
          <TableCell />
          <TableCell colSpan={4}>
            <div className="py-2">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead>Route</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {provider.models.map((model) => (
                    <TableRow key={model.slug}>
                      <TableCell className="text-sm">{model.model_name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{model.slug}</TableCell>
                      <TableCell className="text-sm text-muted-foreground font-mono">{model.route}</TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" onClick={() => handleDeleteModel(model.slug)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TableCell>
        </TableRow>
      )}

      {expanded && provider.models.length === 0 && (
        <TableRow>
          <TableCell />
          <TableCell colSpan={4} className="text-muted-foreground text-sm py-4">
            No models configured. Use "Fetch Models" to discover and add models.
          </TableCell>
        </TableRow>
      )}

      {/* Delete provider confirmation */}
      <Dialog open={deleteConfirm} onOpenChange={setDeleteConfirm}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete Provider</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete provider "{provider.provider}" and all its models? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleDeleteProvider} disabled={deleteProvider.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add models dialog */}
      <Dialog open={addModelsOpen} onOpenChange={setAddModelsOpen}>
        <DialogContent className="max-w-lg max-h-[80vh] flex flex-col">
          <DialogHeader><DialogTitle>Add Models from {provider.provider}</DialogTitle></DialogHeader>
          <div className="flex-1 overflow-auto space-y-1 py-2">
            {fetchedModels.length === 0 && (
              <p className="text-muted-foreground text-sm">No models available from this provider.</p>
            )}
            {fetchedModels.map((model) => {
              const alreadyAdded = provider.models.some((m) => m.model_name === model.id)
              return (
                <label
                  key={model.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded text-sm hover:bg-muted/50 ${alreadyAdded ? "opacity-50" : ""}`}
                >
                  <Checkbox
                    checked={selectedModels.has(model.id)}
                    onCheckedChange={() => toggleModel(model.id)}
                    disabled={alreadyAdded}
                  />
                  <span className="truncate">{model.name || model.id}</span>
                  {alreadyAdded && <Badge variant="secondary" className="ml-auto text-xs">added</Badge>}
                </label>
              )
            })}
          </div>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button onClick={handleAddModels} disabled={selectedModels.size === 0 || addModels.isPending}>
              Add {selectedModels.size} Model(s)
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export default function ProvidersPage() {
  const { data: providers, isLoading, isError } = useProviders()
  const createProvider = useCreateProvider()
  const [open, setOpen] = useState(false)
  const [providerName, setProviderName] = useState("")
  const [providerType, setProviderType] = useState("openai")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    try {
      await createProvider.mutateAsync({
        provider: providerName,
        provider_type: providerType,
        api_key: apiKey,
        base_url: baseUrl,
      })
      setOpen(false)
      setProviderName("")
      setProviderType("openai")
      setApiKey("")
      setBaseUrl("")
      toast.success("Provider created")
    } catch (err) {
      toast.error("Failed to create provider")
    }
  }

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" />
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Providers & Models</h1>
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            Unable to load providers. The agentgateway may not be configured.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Providers & Models</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />Add Provider
        </Button>
      </div>

      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Provider</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Models</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers?.map((p) => (
                <ProviderRow key={p.provider} provider={p} />
              ))}
              {providers?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                    No providers configured. Add a provider to get started.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Add Provider dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Provider</DialogTitle></DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label>Provider Name</Label>
              <Input value={providerName} onChange={(e) => setProviderName(e.target.value)} placeholder="my-openai" required />
            </div>
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
              <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} required />
            </div>
            {providerType === "openai_compatible" && (
              <div className="space-y-2">
                <Label>Base URL</Label>
                <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
              </div>
            )}
            <DialogFooter>
              <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
              <Button type="submit" disabled={createProvider.isPending}>Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
