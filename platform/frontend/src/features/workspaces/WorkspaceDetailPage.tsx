import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useWorkspace, useUpdateWorkspace, useDeleteWorkspace, useResetWorkspace } from "@/api/workspaces"
import { useCredentials } from "@/api/credentials"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Trash2, Plus, ArrowLeft } from "lucide-react"
import { toast } from "sonner"
import type { WorkspaceEnvVar } from "@/types/models"

const CREDENTIAL_FIELDS = [
  { value: "api_key", label: "API Key" },
  { value: "base_url", label: "Base URL" },
  { value: "organization_id", label: "Organization ID" },
  { value: "bot_token", label: "Bot Token" },
  { value: "access_token", label: "Access Token" },
  { value: "ssh_private_key", label: "SSH Private Key" },
  { value: "webhook_secret", label: "Webhook Secret" },
]

export default function WorkspaceDetailPage() {
  const { id = "" } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: workspace, isLoading } = useWorkspace(id)
  const { data: credsData } = useCredentials({ limit: 100 })
  const credentials = credsData?.items ?? []
  const updateWorkspace = useUpdateWorkspace()
  const deleteWorkspace = useDeleteWorkspace()
  const resetWorkspace = useResetWorkspace()

  const [allowNetwork, setAllowNetwork] = useState<boolean | null>(null)
  const [envVars, setEnvVars] = useState<WorkspaceEnvVar[] | null>(null)
  const [showAddVar, setShowAddVar] = useState(false)
  const [newVarKey, setNewVarKey] = useState("")
  const [newVarSource, setNewVarSource] = useState<"raw" | "credential">("raw")
  const [newVarValue, setNewVarValue] = useState("")
  const [newVarCredentialId, setNewVarCredentialId] = useState<string>("")
  const [newVarCredentialField, setNewVarCredentialField] = useState("api_key")
  const [confirmReset, setConfirmReset] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [dirty, setDirty] = useState(false)

  // Use local state if edited, otherwise workspace data
  const currentNetwork = allowNetwork ?? workspace?.allow_network ?? false
  const currentEnvVars = envVars ?? workspace?.env_vars ?? []

  function handleNetworkToggle(checked: boolean) {
    setAllowNetwork(checked)
    setDirty(true)
  }

  function handleSave() {
    if (!workspace) return
    updateWorkspace.mutate(
      { id: workspace.id, data: { allow_network: currentNetwork, env_vars: currentEnvVars } },
      {
        onSuccess: () => {
          toast.success("Workspace updated")
          setDirty(false)
          setAllowNetwork(null)
          setEnvVars(null)
        },
        onError: () => toast.error("Failed to update workspace"),
      },
    )
  }

  function handleAddEnvVar() {
    if (!newVarKey.trim()) return
    const newVar: WorkspaceEnvVar = newVarSource === "raw"
      ? { key: newVarKey.trim(), value: newVarValue, source: "raw" }
      : { key: newVarKey.trim(), credential_id: Number(newVarCredentialId), credential_field: newVarCredentialField, source: "credential" }

    const updated = [...currentEnvVars, newVar]
    setEnvVars(updated)
    setDirty(true)
    setShowAddVar(false)
    setNewVarKey("")
    setNewVarValue("")
    setNewVarSource("raw")
    setNewVarCredentialId("")
    setNewVarCredentialField("api_key")
  }

  function handleRemoveEnvVar(index: number) {
    const updated = currentEnvVars.filter((_, i) => i !== index)
    setEnvVars(updated)
    setDirty(true)
  }

  function handleReset() {
    if (!workspace) return
    resetWorkspace.mutate(workspace.id, {
      onSuccess: (data) => { toast.success(data.message); setConfirmReset(false) },
      onError: () => { toast.error("Failed to reset workspace"); setConfirmReset(false) },
    })
  }

  function handleDelete() {
    if (!workspace) return
    deleteWorkspace.mutate(workspace.id, {
      onSuccess: () => { toast.success("Workspace deleted"); navigate("/workspaces") },
      onError: () => toast.error("Failed to delete workspace"),
    })
  }

  if (isLoading || !workspace) {
    return <div className="p-6"><div className="animate-pulse text-muted-foreground">Loading workspace...</div></div>
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <Button variant="ghost" size="sm" className="mb-2" onClick={() => navigate("/workspaces")}>
          <ArrowLeft className="h-4 w-4 mr-1" />Back to Workspaces
        </Button>
        <h1 className="text-2xl font-bold">{workspace.name}</h1>
        <p className="text-sm text-muted-foreground font-mono">{workspace.path}</p>
      </div>

      {/* Sticky save bar */}
      {dirty && (
        <div className="sticky top-0 z-10 flex items-center justify-between rounded-md border bg-muted/80 backdrop-blur px-4 py-2">
          <span className="text-sm text-muted-foreground">Unsaved changes</span>
          <Button size="sm" onClick={handleSave} disabled={updateWorkspace.isPending}>
            {updateWorkspace.isPending ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      )}

      {/* Settings Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <Label>Network Access</Label>
              <p className="text-xs text-muted-foreground">Allow outbound network in sandbox</p>
            </div>
            <Switch checked={currentNetwork} onCheckedChange={handleNetworkToggle} />
          </div>
        </CardContent>
      </Card>

      {/* Environment Variables Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">Environment Variables</CardTitle>
              <CardDescription>Variables injected into the sandbox at execution time</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => setShowAddVar(true)}>
              <Plus className="h-3 w-3 mr-1" />Add Variable
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {currentEnvVars.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="w-10"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {currentEnvVars.map((ev, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-sm">{ev.key}</TableCell>
                    <TableCell className="text-sm">
                      {ev.source === "credential" ? (
                        <span className="text-muted-foreground italic">
                          {credentials.find(c => c.id === ev.credential_id)?.name ?? `Credential #${ev.credential_id}`}
                          {" "}.{ev.credential_field}
                        </span>
                      ) : (
                        <span className="font-mono">{ev.value ? "********" : "(empty)"}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {ev.source === "credential" ? "credential" : "raw"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" onClick={() => handleRemoveEnvVar(i)}>
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">No environment variables configured.</div>
          )}
        </CardContent>
      </Card>

      {/* Add Variable Dialog */}
      <Dialog open={showAddVar} onOpenChange={setShowAddVar}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Environment Variable</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Key</Label>
              <Input value={newVarKey} onChange={(e) => setNewVarKey(e.target.value)} placeholder="API_KEY" className="font-mono" />
            </div>
            <div className="space-y-2">
              <Label>Source</Label>
              <Select value={newVarSource} onValueChange={(v) => setNewVarSource(v as "raw" | "credential")}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="raw">Raw Value</SelectItem>
                  <SelectItem value="credential">From Credential</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {newVarSource === "raw" ? (
              <div className="space-y-2">
                <Label>Value</Label>
                <Input value={newVarValue} onChange={(e) => setNewVarValue(e.target.value)} placeholder="sk-..." className="font-mono" />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label>Credential</Label>
                  <Select value={newVarCredentialId} onValueChange={setNewVarCredentialId}>
                    <SelectTrigger><SelectValue placeholder="Select credential..." /></SelectTrigger>
                    <SelectContent>
                      {credentials.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.name} ({c.credential_type})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Field</Label>
                  <Select value={newVarCredentialField} onValueChange={setNewVarCredentialField}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {CREDENTIAL_FIELDS.map((f) => (
                        <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button
              onClick={handleAddEnvVar}
              disabled={!newVarKey.trim() || (newVarSource === "credential" && !newVarCredentialId)}
            >
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-sm text-destructive">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Reset Workspace</p>
              <p className="text-xs text-muted-foreground">Delete all files, rootfs, venv, and temp data. Re-creates empty workspace directory.</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => setConfirmReset(true)}>Reset</Button>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Delete Workspace</p>
              <p className="text-xs text-muted-foreground">Remove workspace from database. Files on disk are not deleted.</p>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setConfirmDelete(true)}
              disabled={workspace.name === "default"}
              title={workspace.name === "default" ? "Cannot delete the default workspace" : undefined}
            >
              Delete
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Confirm Reset Dialog */}
      <Dialog open={confirmReset} onOpenChange={setConfirmReset}>
        <DialogContent>
          <DialogHeader><DialogTitle>Reset Workspace</DialogTitle></DialogHeader>
          <p>This will delete <strong>everything</strong> inside the workspace directory: all files, .rootfs, .venv, .tmp, etc. The empty workspace will be re-created.</p>
          <p className="text-sm text-muted-foreground font-mono">{workspace.path}</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleReset} disabled={resetWorkspace.isPending}>
              {resetWorkspace.isPending ? "Resetting..." : "Reset Workspace"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm Delete Dialog */}
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete Workspace</DialogTitle></DialogHeader>
          <p>Are you sure you want to delete this workspace? The directory will not be removed from disk.</p>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteWorkspace.isPending}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
