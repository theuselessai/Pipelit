import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useWorkflows, useCreateWorkflow, useDeleteWorkflow } from "@/api/workflows"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, Trash2 } from "lucide-react"
import { format } from "date-fns"

function slugify(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data: workflows, isLoading } = useWorkflows()
  const createWorkflow = useCreateWorkflow()
  const deleteWorkflow = useDeleteWorkflow()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")
  const [description, setDescription] = useState("")
  const [deleteSlug, setDeleteSlug] = useState<string | null>(null)

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

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
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
                  <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                    No workflows yet. Create one to get started.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
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
    </div>
  )
}
