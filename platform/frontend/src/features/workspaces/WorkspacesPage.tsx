import { useState } from "react"
import { Link } from "react-router-dom"
import { useWorkspaces, useCreateWorkspace, useDeleteWorkspace, useBatchDeleteWorkspaces } from "@/api/workspaces"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Plus, Trash2 } from "lucide-react"
import { format } from "date-fns"

const PAGE_SIZE = 50

export default function WorkspacesPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useWorkspaces({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const workspaces = data?.items
  const total = data?.total ?? 0
  const createWorkspace = useCreateWorkspace()
  const deleteWorkspace = useDeleteWorkspace()
  const batchDelete = useBatchDeleteWorkspaces()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [path, setPath] = useState("")
  const [allowNetwork, setAllowNetwork] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    await createWorkspace.mutateAsync({ name, path: path || undefined, allow_network: allowNetwork })
    setOpen(false)
    setName("")
    setPath("")
    setAllowNetwork(false)
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (!workspaces) return
    if (selectedIds.size === workspaces.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(workspaces.map((w) => w.id)))
    }
  }

  function handleBatchDelete() {
    const defaultIds = new Set(workspaces?.filter((w) => w.name === "default").map((w) => w.id) ?? [])
    const ids = [...selectedIds].filter((id) => !defaultIds.has(id))
    if (ids.length === 0) { setConfirmBatchDelete(false); return }
    batchDelete.mutate(ids, {
      onSuccess: () => { setSelectedIds(new Set()); setConfirmBatchDelete(false) },
    })
  }

  if (isLoading) {
    return <div className="p-6"><div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" /><div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}</div></div>
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Workspaces</h1>
        <div className="flex gap-2">
          {selectedIds.size > 0 && (
            <Button variant="destructive" onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
            </Button>
          )}
          <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4 mr-2" />Add Workspace</Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={workspaces?.length ? selectedIds.size === workspaces.length : false} onCheckedChange={toggleAll} />
                </TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Path</TableHead>
                <TableHead>Network</TableHead>
                <TableHead>Env Vars</TableHead>
                <TableHead>Created</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaces?.map((ws) => (
                <TableRow key={ws.id}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selectedIds.has(ws.id)} onCheckedChange={() => toggleSelect(ws.id)} />
                  </TableCell>
                  <TableCell className="font-medium">
                    <Link to={`/workspaces/${ws.id}`} className="text-blue-600 hover:underline dark:text-blue-400">
                      {ws.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground font-mono max-w-[300px] truncate">{ws.path}</TableCell>
                  <TableCell>
                    {ws.allow_network ? <Badge variant="outline" className="text-green-600">Yes</Badge> : <Badge variant="outline" className="text-muted-foreground">No</Badge>}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">{ws.env_vars?.length || 0}</span>
                  </TableCell>
                  <TableCell>{format(new Date(ws.created_at), "MMM d, yyyy")}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDeleteId(ws.id)}
                      disabled={ws.name === "default"}
                      title={ws.name === "default" ? "Cannot delete the default workspace" : "Delete"}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {workspaces?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">No workspaces yet.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Workspace</DialogTitle></DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} required placeholder="my-project" />
            </div>
            <div className="space-y-2">
              <Label>Path (optional)</Label>
              <Input value={path} onChange={(e) => setPath(e.target.value)} placeholder="Auto-derived from name" />
              {!path && name && (
                <p className="text-xs text-muted-foreground">Will use: ~/.config/pipelit/workspaces/{name}</p>
              )}
            </div>
            <div className="flex items-center justify-between">
              <div>
                <Label>Network Access</Label>
                <p className="text-xs text-muted-foreground">Allow outbound network in sandbox</p>
              </div>
              <Switch checked={allowNetwork} onCheckedChange={setAllowNetwork} />
            </div>
            <DialogFooter>
              <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
              <Button type="submit" disabled={createWorkspace.isPending}>Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete Workspace</DialogTitle></DialogHeader>
          <p>Are you sure? The workspace directory will not be removed from disk.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={() => { if (deleteId) { deleteWorkspace.mutate(deleteId); setDeleteId(null) } }}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Workspaces</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedIds.size} workspaces? The "default" workspace will be skipped. Directories will not be removed from disk.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
