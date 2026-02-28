import { useState } from "react"
import { useMemoryFacts, useMemoryEpisodes, useMemoryProcedures, useMemoryUsers, useMemoryCheckpoints, useBatchDeleteFacts, useBatchDeleteEpisodes, useBatchDeleteProcedures, useBatchDeleteMemoryUsers, useBatchDeleteCheckpoints } from "@/api/memory"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Trash2 } from "lucide-react"
import { format } from "date-fns"

const PAGE_SIZE = 50

function truncate(s: unknown, max = 60): string {
  const str = typeof s === "string" ? s : JSON.stringify(s) ?? ""
  return str.length > max ? str.slice(0, max) + "..." : str
}

function FactsTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useMemoryFacts({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const facts = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteFacts()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)

  function toggleSelect(id: string) {
    setSelectedIds((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    if (!facts) return
    setSelectedIds(selectedIds.size === facts.length ? new Set() : new Set(facts.map((f) => f.id)))
  }
  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], { onSuccess: () => { setSelectedIds(new Set()); setConfirmDelete(false) } })
  }

  if (isLoading) return <Skeleton />

  return (
    <>
      {selectedIds.size > 0 && (
        <div className="mb-2">
          <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
          </Button>
        </div>
      )}
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><Checkbox checked={facts?.length ? selectedIds.size === facts.length : false} onCheckedChange={toggleAll} /></TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Confidence</TableHead>
                <TableHead className="text-right">Accessed</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {facts?.length === 0 && (
                <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">No facts stored yet</TableCell></TableRow>
              )}
              {facts?.map((f) => (
                <TableRow key={f.id}>
                  <TableCell><Checkbox checked={selectedIds.has(f.id)} onCheckedChange={() => toggleSelect(f.id)} /></TableCell>
                  <TableCell className="font-medium max-w-[200px] truncate">{f.key}</TableCell>
                  <TableCell className="max-w-[200px] truncate">{truncate(f.value)}</TableCell>
                  <TableCell><Badge variant="outline">{f.scope}</Badge></TableCell>
                  <TableCell><Badge variant="secondary">{f.fact_type}</Badge></TableCell>
                  <TableCell className="text-right">{(f.confidence * 100).toFixed(0)}%</TableCell>
                  <TableCell className="text-right">{f.access_count}</TableCell>
                  <TableCell className="text-muted-foreground">{format(new Date(f.updated_at), "MMM d, HH:mm")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Facts</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function EpisodesTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useMemoryEpisodes({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const episodes = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteEpisodes()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)

  function toggleSelect(id: string) {
    setSelectedIds((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    if (!episodes) return
    setSelectedIds(selectedIds.size === episodes.length ? new Set() : new Set(episodes.map((e) => e.id)))
  }
  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], { onSuccess: () => { setSelectedIds(new Set()); setConfirmDelete(false) } })
  }

  if (isLoading) return <Skeleton />

  return (
    <>
      {selectedIds.size > 0 && (
        <div className="mb-2">
          <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
          </Button>
        </div>
      )}
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><Checkbox checked={episodes?.length ? selectedIds.size === episodes.length : false} onCheckedChange={toggleAll} /></TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Success</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Started</TableHead>
                <TableHead className="text-right">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {episodes?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">No episodes recorded yet</TableCell></TableRow>
              )}
              {episodes?.map((e) => (
                <TableRow key={e.id}>
                  <TableCell><Checkbox checked={selectedIds.has(e.id)} onCheckedChange={() => toggleSelect(e.id)} /></TableCell>
                  <TableCell className="font-medium">{e.agent_id}</TableCell>
                  <TableCell><Badge variant="outline">{e.trigger_type}</Badge></TableCell>
                  <TableCell><Badge variant={e.success ? "default" : "destructive"}>{e.success ? "Yes" : "No"}</Badge></TableCell>
                  <TableCell className="max-w-[300px] truncate">{e.summary ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{format(new Date(e.started_at), "MMM d, HH:mm")}</TableCell>
                  <TableCell className="text-right">{e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)}s` : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Episodes</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function CheckpointsTab() {
  const [page, setPage] = useState(1)
  const [threadFilter, setThreadFilter] = useState<string>("all")
  const { data, isLoading } = useMemoryCheckpoints({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    thread_id: threadFilter === "all" ? undefined : threadFilter,
  })
  const checkpoints = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteCheckpoints()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Collect distinct thread_ids from current page
  const threadIds = [...new Set(checkpoints?.map((c) => c.thread_id) ?? [])]

  function toggleSelect(id: string) {
    setSelectedIds((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    if (!checkpoints) return
    setSelectedIds(selectedIds.size === checkpoints.length ? new Set() : new Set(checkpoints.map((c) => c.checkpoint_id)))
  }
  function handleBatchDelete() {
    batchDelete.mutate({ checkpoint_ids: [...selectedIds] }, {
      onSuccess: () => { setSelectedIds(new Set()); setConfirmDelete(false) },
    })
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1048576).toFixed(1)} MB`
  }

  if (isLoading) return <Skeleton />

  return (
    <>
      <div className="flex gap-2 mb-2">
        {selectedIds.size > 0 && (
          <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
          </Button>
        )}
        <Select value={threadFilter} onValueChange={(v) => { setThreadFilter(v); setPage(1) }}>
          <SelectTrigger className="w-60"><SelectValue placeholder="All threads" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All threads</SelectItem>
            {threadIds.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><Checkbox checked={checkpoints?.length ? selectedIds.size === checkpoints.length : false} onCheckedChange={toggleAll} /></TableHead>
                <TableHead>Thread ID</TableHead>
                <TableHead>Checkpoint ID</TableHead>
                <TableHead>Parent</TableHead>
                <TableHead className="text-right">Step</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Blob Size</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {checkpoints?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">No checkpoints found</TableCell></TableRow>
              )}
              {checkpoints?.map((c) => (
                <TableRow key={`${c.thread_id}-${c.checkpoint_id}`}>
                  <TableCell><Checkbox checked={selectedIds.has(c.checkpoint_id)} onCheckedChange={() => toggleSelect(c.checkpoint_id)} /></TableCell>
                  <TableCell className="font-mono text-xs">{c.thread_id}</TableCell>
                  <TableCell className="font-mono text-xs">{c.checkpoint_id.slice(0, 12)}...</TableCell>
                  <TableCell className="font-mono text-xs">{c.parent_checkpoint_id ? c.parent_checkpoint_id.slice(0, 12) + "..." : "—"}</TableCell>
                  <TableCell className="text-right">{c.step ?? "—"}</TableCell>
                  <TableCell><Badge variant="outline">{c.source ?? "—"}</Badge></TableCell>
                  <TableCell className="text-right">{formatBytes(c.blob_size)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Checkpoints</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function ProceduresTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useMemoryProcedures({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const procedures = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteProcedures()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)

  function toggleSelect(id: string) {
    setSelectedIds((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    if (!procedures) return
    setSelectedIds(selectedIds.size === procedures.length ? new Set() : new Set(procedures.map((p) => p.id)))
  }
  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], { onSuccess: () => { setSelectedIds(new Set()); setConfirmDelete(false) } })
  }

  if (isLoading) return <Skeleton />

  return (
    <>
      {selectedIds.size > 0 && (
        <div className="mb-2">
          <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
          </Button>
        </div>
      )}
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><Checkbox checked={procedures?.length ? selectedIds.size === procedures.length : false} onCheckedChange={toggleAll} /></TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Used</TableHead>
                <TableHead className="text-right">Success Rate</TableHead>
                <TableHead>Active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {procedures?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">No procedures learned yet</TableCell></TableRow>
              )}
              {procedures?.map((p) => (
                <TableRow key={p.id}>
                  <TableCell><Checkbox checked={selectedIds.has(p.id)} onCheckedChange={() => toggleSelect(p.id)} /></TableCell>
                  <TableCell className="font-medium">{p.name}</TableCell>
                  <TableCell>{p.agent_id}</TableCell>
                  <TableCell><Badge variant="secondary">{p.procedure_type}</Badge></TableCell>
                  <TableCell className="text-right">{p.times_used}</TableCell>
                  <TableCell className="text-right">{(p.success_rate * 100).toFixed(0)}%</TableCell>
                  <TableCell><Badge variant={p.is_active ? "default" : "outline"}>{p.is_active ? "Yes" : "No"}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Procedures</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function UsersTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useMemoryUsers({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  const users = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteMemoryUsers()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)

  function toggleSelect(id: string) {
    setSelectedIds((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    if (!users) return
    setSelectedIds(selectedIds.size === users.length ? new Set() : new Set(users.map((u) => u.id)))
  }
  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], { onSuccess: () => { setSelectedIds(new Set()); setConfirmDelete(false) } })
  }

  if (isLoading) return <Skeleton />

  return (
    <>
      {selectedIds.size > 0 && (
        <div className="mb-2">
          <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
          </Button>
        </div>
      )}
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"><Checkbox checked={users?.length ? selectedIds.size === users.length : false} onCheckedChange={toggleAll} /></TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Canonical ID</TableHead>
                <TableHead>Telegram</TableHead>
                <TableHead>Email</TableHead>
                <TableHead className="text-right">Conversations</TableHead>
                <TableHead>Last Seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">No users identified yet</TableCell></TableRow>
              )}
              {users?.map((u) => (
                <TableRow key={u.id}>
                  <TableCell><Checkbox checked={selectedIds.has(u.id)} onCheckedChange={() => toggleSelect(u.id)} /></TableCell>
                  <TableCell className="font-medium">{u.display_name ?? "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{u.canonical_id}</TableCell>
                  <TableCell>{u.telegram_id ?? "—"}</TableCell>
                  <TableCell>{u.email ?? "—"}</TableCell>
                  <TableCell className="text-right">{u.total_conversations}</TableCell>
                  <TableCell className="text-muted-foreground">{format(new Date(u.last_seen_at), "MMM d, HH:mm")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Users</DialogTitle></DialogHeader>
          <p>Are you sure? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-12 bg-muted animate-pulse rounded" />
      ))}
    </div>
  )
}

export default function MemoriesPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Memories</h1>
      <Tabs defaultValue="facts">
        <TabsList>
          <TabsTrigger value="facts">Facts</TabsTrigger>
          <TabsTrigger value="episodes">Episodes</TabsTrigger>
          <TabsTrigger value="checkpoints">Checkpoints</TabsTrigger>
          <TabsTrigger value="procedures">Procedures</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
        </TabsList>
        <TabsContent value="facts"><FactsTab /></TabsContent>
        <TabsContent value="episodes"><EpisodesTab /></TabsContent>
        <TabsContent value="checkpoints"><CheckpointsTab /></TabsContent>
        <TabsContent value="procedures"><ProceduresTab /></TabsContent>
        <TabsContent value="users"><UsersTab /></TabsContent>
      </Tabs>
    </div>
  )
}
