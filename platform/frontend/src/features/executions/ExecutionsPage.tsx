import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useExecutions } from "@/api/executions"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { format } from "date-fns"
import type { ExecutionStatus } from "@/types/models"

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
  const { data: executions, isLoading } = useExecutions({ status: statusFilter === "all" ? undefined : statusFilter })

  if (isLoading) {
    return <div className="p-6"><div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" /><div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}</div></div>
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Executions</h1>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40"><SelectValue placeholder="All statuses" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            {STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
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
                <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">No executions found.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
