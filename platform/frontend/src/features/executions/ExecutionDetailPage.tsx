import { useState } from "react"
import { useParams } from "react-router-dom"
import type { ExecutionLog } from "@/types/models"
import { useExecution, useCancelExecution } from "@/api/executions"
import { useSubscription } from "@/hooks/useWebSocket"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ChevronDown, ChevronRight } from "lucide-react"
import { format } from "date-fns"

export default function ExecutionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: execution, isLoading } = useExecution(id!)
  const cancelExecution = useCancelExecution()
  useSubscription(id ? `execution:${id}` : null)

  if (isLoading || !execution) {
    return <div className="p-6"><div className="animate-pulse text-muted-foreground">Loading execution...</div></div>
  }

  const canCancel = ["pending", "running", "interrupted"].includes(execution.status)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Execution</h1>
          <p className="text-sm text-muted-foreground font-mono">{execution.execution_id}</p>
        </div>
        {canCancel && (
          <Button variant="destructive" onClick={() => cancelExecution.mutate(execution.execution_id)}>
            Cancel Execution
          </Button>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Workflow</CardTitle></CardHeader>
          <CardContent className="text-sm font-medium">{execution.workflow_slug}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Status</CardTitle></CardHeader>
          <CardContent><Badge>{execution.status}</Badge></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Started</CardTitle></CardHeader>
          <CardContent className="text-sm">{execution.started_at ? format(new Date(execution.started_at), "MMM d, HH:mm:ss") : "-"}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Completed</CardTitle></CardHeader>
          <CardContent className="text-sm">{execution.completed_at ? format(new Date(execution.completed_at), "MMM d, HH:mm:ss") : "-"}</CardContent>
        </Card>
      </div>

      {execution.error_message && (
        <Card className="border-destructive">
          <CardHeader><CardTitle className="text-sm text-destructive">Error</CardTitle></CardHeader>
          <CardContent><pre className="text-xs whitespace-pre-wrap">{execution.error_message}</pre></CardContent>
        </Card>
      )}

      {execution.trigger_payload != null ? (
        <Card>
          <CardHeader><CardTitle className="text-sm">Trigger Payload</CardTitle></CardHeader>
          <CardContent><pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-48">{JSON.stringify(execution.trigger_payload, null, 2)}</pre></CardContent>
        </Card>
      ) : null}

      {execution.final_output != null ? (
        <Card>
          <CardHeader><CardTitle className="text-sm">Final Output</CardTitle></CardHeader>
          <CardContent><pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-48">{JSON.stringify(execution.final_output, null, 2)}</pre></CardContent>
        </Card>
      ) : null}

      <LogsTable logs={execution.logs} />
    </div>
  )
}

function LogsTable({ logs }: { logs: ExecutionLog[] }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Node Execution Logs</CardTitle></CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8"></TableHead>
              <TableHead>Node</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Timestamp</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logs.map((log) => {
              const hasOutput = log.output != null
              const isOpen = expanded.has(log.id)
              return (
                <>
                  <TableRow key={log.id} className={hasOutput ? "cursor-pointer" : ""} onClick={() => hasOutput && toggle(log.id)}>
                    <TableCell className="w-8 px-2">
                      {hasOutput && (isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />)}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{log.node_id}</TableCell>
                    <TableCell><Badge variant="outline">{log.status}</Badge></TableCell>
                    <TableCell className="text-xs">{log.duration_ms}ms</TableCell>
                    <TableCell className="text-xs">{format(new Date(log.timestamp), "HH:mm:ss")}</TableCell>
                  </TableRow>
                  {isOpen && hasOutput && (
                    <TableRow key={`${log.id}-output`}>
                      <TableCell colSpan={5} className="bg-muted/50 p-0">
                        <pre className="text-xs p-3 whitespace-pre-wrap break-all max-h-48 overflow-auto font-mono">
                          {typeof log.output === "string" ? log.output : JSON.stringify(log.output, null, 2)}
                        </pre>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              )
            })}
            {logs.length === 0 && (
              <TableRow><TableCell colSpan={5} className="text-center py-4 text-muted-foreground">No logs yet.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
