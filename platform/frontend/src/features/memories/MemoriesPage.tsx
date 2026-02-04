import { useMemoryFacts, useMemoryEpisodes, useMemoryProcedures, useMemoryUsers } from "@/api/memory"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { format } from "date-fns"

function truncate(s: unknown, max = 60): string {
  const str = typeof s === "string" ? s : JSON.stringify(s) ?? ""
  return str.length > max ? str.slice(0, max) + "..." : str
}

function FactsTab() {
  const { data: facts, isLoading } = useMemoryFacts()

  if (isLoading) return <Skeleton />

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
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
              <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground py-8">No facts stored yet</TableCell></TableRow>
            )}
            {facts?.map((f) => (
              <TableRow key={f.id}>
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
      </CardContent>
    </Card>
  )
}

function EpisodesTab() {
  const { data: episodes, isLoading } = useMemoryEpisodes()

  if (isLoading) return <Skeleton />

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
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
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No episodes recorded yet</TableCell></TableRow>
            )}
            {episodes?.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="font-medium">{e.agent_id}</TableCell>
                <TableCell><Badge variant="outline">{e.trigger_type}</Badge></TableCell>
                <TableCell>
                  <Badge variant={e.success ? "default" : "destructive"}>
                    {e.success ? "Yes" : "No"}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-[300px] truncate">{e.summary ?? "—"}</TableCell>
                <TableCell className="text-muted-foreground">{format(new Date(e.started_at), "MMM d, HH:mm")}</TableCell>
                <TableCell className="text-right">{e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)}s` : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function ProceduresTab() {
  const { data: procedures, isLoading } = useMemoryProcedures()

  if (isLoading) return <Skeleton />

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
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
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No procedures learned yet</TableCell></TableRow>
            )}
            {procedures?.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.name}</TableCell>
                <TableCell>{p.agent_id}</TableCell>
                <TableCell><Badge variant="secondary">{p.procedure_type}</Badge></TableCell>
                <TableCell className="text-right">{p.times_used}</TableCell>
                <TableCell className="text-right">{(p.success_rate * 100).toFixed(0)}%</TableCell>
                <TableCell>
                  <Badge variant={p.is_active ? "default" : "outline"}>
                    {p.is_active ? "Yes" : "No"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function UsersTab() {
  const { data: users, isLoading } = useMemoryUsers()

  if (isLoading) return <Skeleton />

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
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
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No users identified yet</TableCell></TableRow>
            )}
            {users?.map((u) => (
              <TableRow key={u.id}>
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
      </CardContent>
    </Card>
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
          <TabsTrigger value="procedures">Procedures</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
        </TabsList>
        <TabsContent value="facts"><FactsTab /></TabsContent>
        <TabsContent value="episodes"><EpisodesTab /></TabsContent>
        <TabsContent value="procedures"><ProceduresTab /></TabsContent>
        <TabsContent value="users"><UsersTab /></TabsContent>
      </Tabs>
    </div>
  )
}
