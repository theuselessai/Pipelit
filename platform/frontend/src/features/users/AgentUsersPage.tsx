import { useState } from "react"
import { useAgentUsers, useDeleteAgentUser } from "@/api/users"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Trash2, Bot, Key } from "lucide-react"
import { format } from "date-fns"

export default function AgentUsersPage() {
  const { data: agentUsers, isLoading } = useAgentUsers()
  const deleteAgentUser = useDeleteAgentUser()
  const [deleteId, setDeleteId] = useState<number | null>(null)

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="h-8 w-48 bg-muted animate-pulse rounded mb-6" />
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 bg-muted animate-pulse rounded" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Bot className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Agent Users</h1>
        </div>
        <Badge variant="secondary">{agentUsers?.length ?? 0} users</Badge>
      </div>

      <p className="text-muted-foreground mb-4">
        Agent users are API credentials created by agents using the Create API User tool.
        These users can be used by agents to interact with the platform API.
      </p>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead>Purpose</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>Created At</TableHead>
                <TableHead>Created By</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agentUsers?.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-medium font-mono">{user.username}</TableCell>
                  <TableCell className="max-w-xs truncate">{user.purpose || <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell>
                    <code className="text-xs bg-muted px-2 py-1 rounded flex items-center gap-1 w-fit">
                      <Key className="h-3 w-3" />
                      {user.api_key_preview}
                    </code>
                  </TableCell>
                  <TableCell>{format(new Date(user.created_at), "MMM d, yyyy HH:mm")}</TableCell>
                  <TableCell>{user.created_by || <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setDeleteId(user.id)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {agentUsers?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    No agent users yet. Agents can create users using the Create API User tool.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Agent User</DialogTitle>
          </DialogHeader>
          <p>
            Are you sure you want to delete this agent user? Their API key will be revoked
            and they will no longer be able to access the platform.
          </p>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={() => {
                if (deleteId) {
                  deleteAgentUser.mutate(deleteId)
                  setDeleteId(null)
                }
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
