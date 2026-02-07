import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useWorkflows, useCreateWorkflow, useDeleteWorkflow, useBatchDeleteWorkflows } from "@/api/workflows"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Plus, Trash2 } from "lucide-react"
import { format } from "date-fns"

const PAGE_SIZE = 50

function slugify(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const { data, isLoading } = useWorkflows({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const workflows = data?.items
  const total = data?.total ?? 0
  const createWorkflow = useCreateWorkflow()
  const deleteWorkflow = useDeleteWorkflow()
  const batchDelete = useBatchDeleteWorkflows()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")
  const [description, setDescription] = useState("")
  const [deleteSlug, setDeleteSlug] = useState<string | null>(null)
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  function handleNameChange(value: string) {
    setName(value)
    setSlug(slugify(value))
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    await createWorkflow.mutateAsync({ name, slug, description })
    setOpen(false)
    setName("")
    setSlug("")
    setDescription("")
  }

  async function handleDelete() {
    if (deleteSlug) {
      await deleteWorkflow.mutateAsync(deleteSlug)
      setDeleteSlug(null)
    }
  }

  function toggleSelect(s: string) {
    setSelectedSlugs((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })
  }

  function toggleAll() {
    if (!workflows) return
    if (selectedSlugs.size === workflows.length) {
      setSelectedSlugs(new Set())
    } else {
      setSelectedSlugs(new Set(workflows.map((wf) => wf.slug)))
    }
  }

  function handleBatchDelete() {
    batchDelete.mutate([...selectedSlugs], {
      onSuccess: () => { setSelectedSlugs(new Set()); setConfirmBatchDelete(false) },
    })
  }

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" />
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-muted animate-pulse rounded" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Workflows</h1>
        <div className="flex gap-2">
          {selectedSlugs.size > 0 && (
            <Button variant="destructive" onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedSlugs.size})
            </Button>
          )}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4 mr-2" />Create Workflow</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Workflow</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="space-y-4">
                <div className="space-y-2">
                  <Label>Name</Label>
                  <Input value={name} onChange={(e) => handleNameChange(e.target.value)} required />
                </div>
                <div className="space-y-2">
                  <Label>Slug</Label>
                  <Input value={slug} onChange={(e) => setSlug(e.target.value)} required />
                </div>
                <div className="space-y-2">
                  <Label>Description</Label>
                  <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
                </div>
                <DialogFooter>
                  <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
                  <Button type="submit" disabled={createWorkflow.isPending}>Create</Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={workflows?.length ? selectedSlugs.size === workflows.length : false} onCheckedChange={toggleAll} />
                </TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Nodes</TableHead>
                <TableHead>Edges</TableHead>
                <TableHead>Triggers</TableHead>
                <TableHead>Created</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workflows?.map((wf) => (
                <TableRow key={wf.id} className="cursor-pointer" onClick={() => navigate(`/workflows/${wf.slug}`)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selectedSlugs.has(wf.slug)} onCheckedChange={() => toggleSelect(wf.slug)} />
                  </TableCell>
                  <TableCell className="font-medium">{wf.name}</TableCell>
                  <TableCell className="text-muted-foreground">{wf.slug}</TableCell>
                  <TableCell>
                    <Badge variant={wf.is_active ? "default" : "secondary"}>
                      {wf.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>{wf.node_count}</TableCell>
                  <TableCell>{wf.edge_count}</TableCell>
                  <TableCell>{wf.trigger_count}</TableCell>
                  <TableCell>{format(new Date(wf.created_at), "MMM d, yyyy")}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setDeleteSlug(wf.slug) }}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {workflows?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
                    No workflows yet. Create one to get started.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog open={!!deleteSlug} onOpenChange={() => setDeleteSlug(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Workflow</DialogTitle>
          </DialogHeader>
          <p>Are you sure you want to delete this workflow? This action cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleDelete}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedSlugs.size} Workflows</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedSlugs.size} workflows? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
