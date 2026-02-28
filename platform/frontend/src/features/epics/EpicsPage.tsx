import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useEpics, useBatchDeleteEpics } from "@/api/epics"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { Trash2 } from "lucide-react"
import { format } from "date-fns"
import type { EpicStatus } from "@/types/models"

const PAGE_SIZE = 50

const STATUS_COLORS: Record<string, string> = {
  planning: "bg-yellow-100 text-yellow-800",
  active: "bg-blue-100 text-blue-800",
  paused: "bg-orange-100 text-orange-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
}

const STATUSES: EpicStatus[] = ["planning", "active", "paused", "completed", "failed", "cancelled"]

export default function EpicsPage() {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [page, setPage] = useState(1)
  const { data, isLoading } = useEpics({
    status: statusFilter === "all" ? undefined : statusFilter,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })
  const epics = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteEpics()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (!epics) return
    if (selectedIds.size === epics.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(epics.map((e) => e.id)))
    }
  }

  function handleBatchDelete() {
    batchDelete.mutate([...selectedIds], {
      onSuccess: () => { setSelectedIds(new Set()); setConfirmBatchDelete(false) },
    })
  }

  if (isLoading) {
    return <div className="p-6"><div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" /><div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}</div></div>
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Epics</h1>
        <div className="flex gap-2">
          {selectedIds.size > 0 && (
            <Button variant="destructive" onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
            </Button>
          )}
          <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1); setSelectedIds(new Set()) }}>
            <SelectTrigger className="w-40"><SelectValue placeholder="All statuses" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={epics?.length ? selectedIds.size === epics.length && epics.every(e => selectedIds.has(e.id)) : false} onCheckedChange={toggleAll} />
                </TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {epics?.map((epic) => (
                <TableRow key={epic.id} className="cursor-pointer" onClick={() => navigate(`/epics/${epic.id}`)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selectedIds.has(epic.id)} onCheckedChange={() => toggleSelect(epic.id)} />
                  </TableCell>
                  <TableCell className="font-medium">{epic.title}</TableCell>
                  <TableCell>
                    <Badge className={STATUS_COLORS[epic.status] ?? ""}>{epic.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">{epic.completed_tasks}/{epic.total_tasks} tasks</TableCell>
                  <TableCell className="text-sm">{epic.priority}</TableCell>
                  <TableCell className="text-sm">{epic.created_at && !isNaN(new Date(epic.created_at).getTime()) ? format(new Date(epic.created_at), "MMM d, HH:mm") : "-"}</TableCell>
                </TableRow>
              ))}
              {epics?.length === 0 && (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No epics found.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={(p) => { setPage(p); setSelectedIds(new Set()) }} />
        </CardContent>
      </Card>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Epics</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedIds.size} epics? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
