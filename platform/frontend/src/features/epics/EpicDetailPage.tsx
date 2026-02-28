import { useState } from "react"
import { useParams } from "react-router-dom"
import { useEpic, useEpicTasks } from "@/api/epics"
import { useBatchDeleteTasks } from "@/api/tasks"
import { useSubscription } from "@/hooks/useWebSocket"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { PaginationControls } from "@/components/ui/pagination-controls"
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react"
import { format } from "date-fns"
import type { Task } from "@/types/models"

const PAGE_SIZE = 50

const EPIC_STATUS_COLORS: Record<string, string> = {
  planning: "bg-yellow-100 text-yellow-800",
  active: "bg-blue-100 text-blue-800",
  paused: "bg-orange-100 text-orange-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
}

const TASK_STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  blocked: "bg-orange-100 text-orange-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
}

export default function EpicDetailPage() {
  const { epicId = "" } = useParams<{ epicId: string }>()
  const { data: epic, isLoading } = useEpic(epicId)
  const [taskPage, setTaskPage] = useState(1)
  const { data: tasksData } = useEpicTasks(epicId, { limit: PAGE_SIZE, offset: (taskPage - 1) * PAGE_SIZE })
  const tasks = tasksData?.items
  const taskTotal = tasksData?.total ?? 0
  const batchDeleteTasks = useBatchDeleteTasks()
  useSubscription(epicId ? `epic:${epicId}` : null)

  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set())

  function toggleTaskSelect(id: string) {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function toggleAllTasks() {
    if (!tasks) return
    if (selectedTaskIds.size === tasks.length) {
      setSelectedTaskIds(new Set())
    } else {
      setSelectedTaskIds(new Set(tasks.map((t) => t.id)))
    }
  }

  function handleBatchDeleteTasks() {
    batchDeleteTasks.mutate([...selectedTaskIds], {
      onSuccess: () => { setSelectedTaskIds(new Set()); setConfirmBatchDelete(false) },
    })
  }

  function toggleExpand(id: string) {
    setExpandedTasks((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  if (!epicId) {
    return <div className="p-6"><div className="text-destructive">Epic ID is required</div></div>
  }

  if (isLoading || !epic) {
    return <div className="p-6"><div className="animate-pulse text-muted-foreground">Loading epic...</div></div>
  }

  const budgetLabel = epic.budget_usd != null
    ? `$${epic.budget_usd.toFixed(2)}`
    : epic.budget_tokens != null
      ? `${epic.budget_tokens.toLocaleString()} tokens`
      : "No budget"
  const costLabel = epic.spent_usd != null
    ? `$${epic.spent_usd.toFixed(4)}`
    : epic.spent_tokens != null
      ? `${epic.spent_tokens.toLocaleString()} tokens`
      : "No cost"

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{epic.title}</h1>
        <p className="text-sm text-muted-foreground font-mono">{epic.id}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Status</CardTitle></CardHeader>
          <CardContent><Badge className={EPIC_STATUS_COLORS[epic.status] ?? ""}>{epic.status}</Badge></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Progress</CardTitle></CardHeader>
          <CardContent className="text-sm font-medium">{epic.completed_tasks}/{epic.total_tasks} tasks</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Budget</CardTitle></CardHeader>
          <CardContent className="text-sm font-medium">{budgetLabel}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Cost</CardTitle></CardHeader>
          <CardContent className="text-sm font-medium">{costLabel}</CardContent>
        </Card>
      </div>

      {epic.description && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Description</CardTitle></CardHeader>
          <CardContent><p className="text-sm whitespace-pre-wrap">{epic.description}</p></CardContent>
        </Card>
      )}

      {epic.result_summary && (epic.status === "completed" || epic.status === "failed") && (
        <Card className={epic.status === "failed" ? "border-destructive" : ""}>
          <CardHeader><CardTitle className="text-sm">{epic.status === "failed" ? "Error" : "Result Summary"}</CardTitle></CardHeader>
          <CardContent><pre className="text-xs whitespace-pre-wrap">{epic.result_summary}</pre></CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Tasks</CardTitle>
            {selectedTaskIds.size > 0 && (
              <Button variant="destructive" size="sm" onClick={() => setConfirmBatchDelete(true)}>
                <Trash2 className="h-3 w-3 mr-1" />Delete ({selectedTaskIds.size})
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"></TableHead>
                <TableHead className="w-10">
                  <Checkbox checked={tasks?.length ? selectedTaskIds.size === tasks.length : false} onCheckedChange={toggleAllTasks} />
                </TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Workflow</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks?.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  isExpanded={expandedTasks.has(task.id)}
                  isSelected={selectedTaskIds.has(task.id)}
                  onToggleExpand={() => toggleExpand(task.id)}
                  onToggleSelect={() => toggleTaskSelect(task.id)}
                />
              ))}
              {tasks?.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">No tasks found.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <PaginationControls page={taskPage} pageSize={PAGE_SIZE} total={taskTotal} onPageChange={(p) => { setTaskPage(p); setSelectedTaskIds(new Set()) }} />
        </CardContent>
      </Card>

      <Dialog open={confirmBatchDelete} onOpenChange={setConfirmBatchDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {selectedTaskIds.size} Tasks</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete {selectedTaskIds.size} tasks? This cannot be undone.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleBatchDeleteTasks} disabled={batchDeleteTasks.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function TaskRow({ task, isExpanded, isSelected, onToggleExpand, onToggleSelect }: {
  task: Task; isExpanded: boolean; isSelected: boolean; onToggleExpand: () => void; onToggleSelect: () => void
}) {
  const hasDetails = !!(task.description || task.result_summary || task.error_message || task.depends_on.length > 0)
  const durationLabel = task.duration_ms > 0 ? `${(task.duration_ms / 1000).toFixed(1)}s` : "-"

  return (
    <>
      <TableRow className={hasDetails ? "cursor-pointer" : ""} onClick={() => hasDetails && onToggleExpand()}>
        <TableCell className="w-8 px-2">
          {hasDetails && (isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />)}
        </TableCell>
        <TableCell onClick={(e) => e.stopPropagation()}>
          <Checkbox checked={isSelected} onCheckedChange={onToggleSelect} />
        </TableCell>
        <TableCell className="font-medium">{task.title}</TableCell>
        <TableCell>
          <Badge className={TASK_STATUS_COLORS[task.status] ?? ""}>{task.status}</Badge>
        </TableCell>
        <TableCell className="text-xs">{task.workflow_slug ?? "-"}</TableCell>
        <TableCell className="text-xs">{durationLabel}</TableCell>
        <TableCell className="text-xs">{task.created_at ? format(new Date(task.created_at), "MMM d, HH:mm") : "-"}</TableCell>
      </TableRow>
      {isExpanded && hasDetails && (
        <TableRow>
          <TableCell colSpan={7} className="bg-muted/50 p-0">
            <div className="p-3 space-y-2 text-xs">
              {task.description && (
                <div><span className="font-semibold">Description:</span> <span className="whitespace-pre-wrap">{task.description}</span></div>
              )}
              {task.depends_on.length > 0 && (
                <div><span className="font-semibold">Dependencies:</span> <span className="font-mono">{task.depends_on.join(", ")}</span></div>
              )}
              {task.result_summary && (
                <div><span className="font-semibold">Result:</span> <span className="whitespace-pre-wrap">{task.result_summary}</span></div>
              )}
              {task.error_message && (
                <div className="text-red-600"><span className="font-semibold">Error:</span> <span className="whitespace-pre-wrap">{task.error_message}</span></div>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
