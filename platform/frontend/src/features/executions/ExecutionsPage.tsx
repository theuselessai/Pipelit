import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useExecutions, useBatchDeleteExecutions } from "@/api/executions"
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
import type { ExecutionStatus } from "@/types/models"

const PAGE_SIZE = 50

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
  interrupted: "bg-orange-100 text-orange-800",
}

const STATUSES: ExecutionStatus[] = ["pending", "running", "interrupted", "completed", "failed", "cancelled"]

export default function ExecutionsPage() {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [page, setPage] = useState(1)
  const { data, isLoading } = useExecutions({
    status: statusFilter === "all" ? undefined : statusFilter,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })
  const executions = data?.items
  const total = data?.total ?? 0
  const batchDelete = useBatchDeleteExecutions()
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
    if (!executions) return
    if (selectedIds.size === executions.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(executions.map((ex) => ex.execution_id)))
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
        <h1 className="text-2xl font-bold">Executions</h1>
        <div className="flex gap-2">
          {selectedIds.size > 0 && (
            <Button variant="destructive" onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="h-4 w-4 mr-2" />Delete Selected ({selectedIds.size})
            </Button>
          )}
          <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1) }}>
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
                  <Checkbox checked={executions?.length ? selectedIds.size === executions.length : false} onCheckedChange={toggleAll} />
                </TableHead>
                <TableHead>Execution ID</TableHead>
                <TableHead>Workflow</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Completed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {executions?.map((ex) => (
                <TableRow key={ex.execution_id} className="cursor-pointer" onClick={() => navigate(`/executions/${ex.execution_id}`)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selectedIds.has(ex.execution_id)} onCheckedChange={() => toggleSelect(ex.execution_id)} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{ex.execution_id.slice(0, 8)}...</TableCell>
                  <TableCell>{ex.workflow_slug}</TableCell>
                  <TableCell>
                    <Badge className={STATUS_COLORS[ex.status] ?? ""}>{ex.status}</Badge>
                  </TableCell>
                  <TableCell>{ex.started_at ? format(new Date(ex.started_at), "MMM d, HH:mm") : "-"}</TableCell>
                  <TableCell>{ex.completed_at ? format(new Date(ex.completed_at), "MMM d, HH:mm") : "-"}</TableCell>
                </TableRow>
              ))}
              {executions?.length === 0 && (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No executions found.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedIds.size} Executions</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedIds.size} executions? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDelete.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
