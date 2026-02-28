import { useEffect, useState } from "react"
import { QRCodeSVG } from "qrcode.react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useTheme } from "@/hooks/useTheme"
import { useColorTheme } from "@/hooks/useColorTheme"
import { COLOR_THEMES, COLOR_THEME_KEYS, type ColorThemeKey } from "@/lib/colorThemes"
import { useEditorTheme, EDITOR_THEMES, type EditorThemeKey } from "@/hooks/useEditorTheme"
import CodeMirrorEditor from "@/components/CodeMirrorEditor"
import { mfaSetup, mfaVerify, mfaDisable, mfaStatus, type MFASetupResult } from "@/api/auth"
import { useSettings, useUpdateSettings, useRecheckEnvironment } from "@/api/settings"
import type { EnvironmentInfo } from "@/types/models"
import type { PlatformConfigOut } from "@/api/settings"

const themes = [
  { value: "system" as const, label: "System" },
  { value: "light" as const, label: "Light" },
  { value: "dark" as const, label: "Dark" },
]

const PREVIEW_SNIPPET = `def greet(name: str) -> str:
    """Return a greeting message."""
    message = f"Hello, {name}!"
    return message

# Call the function
print(greet("world"))  # Hello, world!`

const themeKeys = Object.keys(EDITOR_THEMES) as EditorThemeKey[]

const TIER1_TOOLS = [
  "bash", "python3", "pip3", "cat", "ls", "cp", "mv", "mkdir",
  "rm", "chmod", "grep", "sed", "head", "tail", "wc",
]

const TIER2_TOOLS = [
  "find", "sort", "awk", "xargs", "tee", "curl", "wget",
  "git", "tar", "unzip", "jq", "node", "npm",
]

function EnvironmentCard({ environment, onRecheck }: { environment: EnvironmentInfo; onRecheck: () => void }) {
  const recheckEnv = useRecheckEnvironment()

  const handleRecheck = () => {
    recheckEnv.mutate(undefined, { onSuccess: () => onRecheck() })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Environment</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRecheck}
            disabled={recheckEnv.isPending}
          >
            {recheckEnv.isPending ? "Checking..." : "Re-check"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* System Info */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">OS:</span>{" "}
            <span className="font-medium">{environment.os}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Arch:</span>{" "}
            <span className="font-medium">{environment.arch}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Container:</span>{" "}
            <span className="font-medium">{environment.container || "none"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Sandbox:</span>{" "}
            <span className="font-medium">{environment.sandbox_mode}</span>
          </div>
          <div>
            <span className="text-muted-foreground">bwrap:</span>{" "}
            <Badge variant={environment.bwrap_available ? "default" : "secondary"} className="text-xs">
              {environment.bwrap_available ? "available" : "not found"}
            </Badge>
          </div>
          <div>
            <span className="text-muted-foreground">rootfs:</span>{" "}
            <Badge variant={environment.rootfs_ready ? "default" : "secondary"} className="text-xs">
              {environment.rootfs_ready ? "ready" : "not ready"}
            </Badge>
          </div>
        </div>

        {/* Runtimes */}
        <div>
          <h4 className="text-sm font-medium mb-1">Runtimes</h4>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(environment.capabilities.runtimes).map(([name, info]) => (
              <Badge key={name} variant={info.available ? "default" : "secondary"} className="text-xs">
                {name}{info.version ? ` (${info.version})` : ""}
              </Badge>
            ))}
          </div>
        </div>

        {/* Shell Tools */}
        <div>
          <h4 className="text-sm font-medium mb-1">Shell Tools — Tier 1</h4>
          <div className="flex flex-wrap gap-1">
            {TIER1_TOOLS.map((tool) => {
              const info = environment.capabilities.shell_tools[tool]
              return (
                <Badge key={tool} variant={info?.available ? "default" : "secondary"} className="text-xs">
                  {tool}
                </Badge>
              )
            })}
          </div>
        </div>
        <div>
          <h4 className="text-sm font-medium mb-1">Shell Tools — Tier 2</h4>
          <div className="flex flex-wrap gap-1">
            {TIER2_TOOLS.map((tool) => {
              const info = environment.capabilities.shell_tools[tool]
              return (
                <Badge key={tool} variant={info?.available ? "default" : "secondary"} className="text-xs">
                  {tool}
                </Badge>
              )
            })}
          </div>
        </div>

        {/* Network */}
        <div>
          <h4 className="text-sm font-medium mb-1">Network</h4>
          <div className="flex gap-2">
            <Badge variant={environment.capabilities.network.dns ? "default" : "secondary"} className="text-xs">
              DNS {environment.capabilities.network.dns ? "OK" : "fail"}
            </Badge>
            <Badge variant={environment.capabilities.network.http ? "default" : "secondary"} className="text-xs">
              HTTP {environment.capabilities.network.http ? "OK" : "fail"}
            </Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function PlatformConfigCard({
  config,
  onSave,
  saving,
  pendingRestart,
}: {
  config: PlatformConfigOut
  onSave: (fields: Record<string, unknown>) => void
  saving: boolean
  pendingRestart: string[]
}) {
  const [databaseUrl, setDatabaseUrl] = useState(config.database_url)
  const [redisUrl, setRedisUrl] = useState(config.redis_url)
  const [platformBaseUrl, setPlatformBaseUrl] = useState(config.platform_base_url)
  const [corsAllowAll, setCorsAllowAll] = useState(config.cors_allow_all_origins ?? true)
  const [sandboxMode, setSandboxMode] = useState(config.sandbox_mode)

  useEffect(() => {
    setDatabaseUrl(config.database_url)
    setRedisUrl(config.redis_url)
    setPlatformBaseUrl(config.platform_base_url)
    setCorsAllowAll(config.cors_allow_all_origins ?? true)
    setSandboxMode(config.sandbox_mode)
  }, [config])

  const handleSave = () => {
    onSave({
      database_url: databaseUrl,
      redis_url: redisUrl,
      platform_base_url: platformBaseUrl,
      cors_allow_all_origins: corsAllowAll,
      sandbox_mode: sandboxMode,
    })
  }

  return (
    <Card>
      <CardHeader><CardTitle>Platform Configuration</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {pendingRestart.length > 0 && (
          <Alert variant="warning">
            <AlertTitle>Restart required</AlertTitle>
            <AlertDescription>
              The following settings require a server restart to take effect:{" "}
              <span className="font-medium">{pendingRestart.join(", ")}</span>
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Label>Data Directory</Label>
          <Input value={config.pipelit_dir} disabled />
          <p className="text-xs text-muted-foreground">Read-only. Set via PIPELIT_DIR environment variable.</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="database-url">Database URL</Label>
          <Input id="database-url" value={databaseUrl} onChange={(e) => setDatabaseUrl(e.target.value)} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="redis-url">Redis URL</Label>
          <Input id="redis-url" value={redisUrl} onChange={(e) => setRedisUrl(e.target.value)} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="platform-base-url">Platform Base URL</Label>
          <Input id="platform-base-url" value={platformBaseUrl} onChange={(e) => setPlatformBaseUrl(e.target.value)} />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label htmlFor="cors-all">CORS Allow All Origins</Label>
            <p className="text-xs text-muted-foreground">Allow requests from any origin.</p>
          </div>
          <Switch id="cors-all" checked={corsAllowAll} onCheckedChange={setCorsAllowAll} />
        </div>

        <div className="space-y-2">
          <Label>Sandbox Mode</Label>
          <Select value={sandboxMode} onValueChange={setSandboxMode}>
            <SelectTrigger className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">auto</SelectItem>
              <SelectItem value="bwrap">bwrap</SelectItem>
              <SelectItem value="container">container</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </CardContent>
    </Card>
  )
}

function LoggingCard({
  config,
  onSave,
  saving,
}: {
  config: PlatformConfigOut
  onSave: (fields: Record<string, unknown>) => void
  saving: boolean
}) {
  const [logLevel, setLogLevel] = useState(config.log_level)
  const [logFile, setLogFile] = useState(config.log_file)

  useEffect(() => {
    setLogLevel(config.log_level)
    setLogFile(config.log_file)
  }, [config])

  const handleSave = () => {
    onSave({ log_level: logLevel, log_file: logFile })
  }

  return (
    <Card>
      <CardHeader><CardTitle>Logging</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Log Level</Label>
          <Select value={logLevel} onValueChange={setLogLevel}>
            <SelectTrigger className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((level) => (
                <SelectItem key={level} value={level}>{level}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="log-file">Log File Path</Label>
          <Input
            id="log-file"
            value={logFile}
            onChange={(e) => setLogFile(e.target.value)}
            placeholder="Empty = console only"
          />
        </div>

        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </CardContent>
    </Card>
  )
}

function AdvancedCard({
  config,
  onSave,
  saving,
}: {
  config: PlatformConfigOut
  onSave: (fields: Record<string, unknown>) => void
  saving: boolean
}) {
  const [zombieThreshold, setZombieThreshold] = useState(
    config.zombie_execution_threshold_seconds ?? 900
  )

  useEffect(() => {
    setZombieThreshold(config.zombie_execution_threshold_seconds ?? 900)
  }, [config])

  const handleSave = () => {
    onSave({ zombie_execution_threshold_seconds: zombieThreshold })
  }

  return (
    <Card>
      <CardHeader><CardTitle>Advanced</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="zombie-threshold">Zombie Execution Threshold (seconds)</Label>
          <Input
            id="zombie-threshold"
            type="number"
            min={0}
            value={zombieThreshold}
            onChange={(e) => setZombieThreshold(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Executions running longer than this are considered zombies. Default: 900 (15 min).
          </p>
        </div>

        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const { colorTheme, setColorTheme } = useColorTheme()
  const { editorTheme, setEditorTheme } = useEditorTheme()

  // MFA state
  const [mfaEnabled, setMfaEnabled] = useState(false)
  const [mfaLoading, setMfaLoading] = useState(true)
  const [showEnableDialog, setShowEnableDialog] = useState(false)
  const [showDisableDialog, setShowDisableDialog] = useState(false)
  const [setupData, setSetupData] = useState<MFASetupResult | null>(null)
  const [code, setCode] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // Platform settings state
  const { data: settingsData, isLoading: settingsLoading } = useSettings()
  const updateSettings = useUpdateSettings()
  const [pendingRestart, setPendingRestart] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    mfaStatus()
      .then((res) => setMfaEnabled(res.mfa_enabled))
      .catch(() => {})
      .finally(() => setMfaLoading(false))
  }, [])

  async function handleEnableClick() {
    setError("")
    setCode("")
    setSubmitting(true)
    try {
      const data = await mfaSetup()
      setSetupData(data)
      setShowEnableDialog(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start MFA setup")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleVerifyCode(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      const res = await mfaVerify(code)
      setMfaEnabled(res.mfa_enabled)
      setShowEnableDialog(false)
      setSetupData(null)
      setCode("")
    } catch {
      setError("Invalid code. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDisableMfa(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      const res = await mfaDisable(code)
      setMfaEnabled(res.mfa_enabled)
      setShowDisableDialog(false)
      setCode("")
    } catch {
      setError("Invalid code. Please try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const handleSave = async (fields: Record<string, unknown>) => {
    setSaving(true)
    try {
      const result = await updateSettings.mutateAsync(fields as Record<string, string>)
      if (result.restart_required.length > 0) {
        setPendingRestart((prev) => {
          const combined = new Set([...prev, ...result.restart_required])
          return Array.from(combined)
        })
      }
    } catch {
      // error handled by TanStack Query
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <Card>
        <CardHeader><CardTitle>Appearance</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-2">
            {themes.map((t) => (
              <button
                key={t.value}
                onClick={() => setTheme(t.value)}
                className={`px-4 py-2 rounded-md text-sm border transition-colors ${
                  theme === t.value
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-secondary text-secondary-foreground border-border hover:bg-accent"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>System Theme</CardTitle></CardHeader>
        <CardContent>
          <Select value={colorTheme} onValueChange={(v) => setColorTheme(v as ColorThemeKey)}>
            <SelectTrigger className="w-[240px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {COLOR_THEME_KEYS.map((key) => (
                <SelectItem key={key} value={key}>
                  {COLOR_THEMES[key].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Editor Theme</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Theme</Label>
            <Select value={editorTheme} onValueChange={(v) => setEditorTheme(v as EditorThemeKey)}>
              <SelectTrigger className="w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {themeKeys.map((key) => (
                  <SelectItem key={key} value={key}>
                    {EDITOR_THEMES[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label className="text-muted-foreground text-xs">Preview</Label>
            <CodeMirrorEditor
              value={PREVIEW_SNIPPET}
              language="python"
              readOnly
              className="h-[200px]"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Two-Factor Authentication</CardTitle>
            {!mfaLoading && (
              <Badge variant={mfaEnabled ? "default" : "secondary"}>
                {mfaEnabled ? "Enabled" : "Disabled"}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Add an extra layer of security by requiring a TOTP code from your authenticator app when signing in.
          </p>
          {!mfaLoading && (
            mfaEnabled ? (
              <Button variant="destructive" onClick={() => { setCode(""); setError(""); setShowDisableDialog(true) }}>
                Disable MFA
              </Button>
            ) : (
              <Button onClick={handleEnableClick} disabled={submitting}>
                {submitting ? "Setting up..." : "Enable MFA"}
              </Button>
            )
          )}
          {error && !showEnableDialog && !showDisableDialog && (
            <p className="text-sm text-destructive mt-2">{error}</p>
          )}
        </CardContent>
      </Card>

      {/* Platform Settings Cards */}
      {settingsLoading ? (
        <Card>
          <CardContent className="py-8">
            <p className="text-sm text-muted-foreground text-center">Loading platform settings...</p>
          </CardContent>
        </Card>
      ) : settingsData ? (
        <>
          <EnvironmentCard
            environment={settingsData.environment}
            onRecheck={() => {}}
          />
          <PlatformConfigCard
            config={settingsData.config}
            onSave={handleSave}
            saving={saving}
            pendingRestart={pendingRestart}
          />
          <LoggingCard
            config={settingsData.config}
            onSave={handleSave}
            saving={saving}
          />
          <AdvancedCard
            config={settingsData.config}
            onSave={handleSave}
            saving={saving}
          />
        </>
      ) : null}

      {/* Enable MFA Dialog */}
      <Dialog open={showEnableDialog} onOpenChange={(open) => { setShowEnableDialog(open); if (!open) { setError(""); setCode(""); setSetupData(null); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Set Up Two-Factor Authentication</DialogTitle>
            <DialogDescription>
              Scan the QR code with your authenticator app, then enter the 6-digit code to verify.
            </DialogDescription>
          </DialogHeader>
          {setupData && (
            <form onSubmit={handleVerifyCode} className="space-y-4">
              <div className="flex justify-center">
                <QRCodeSVG value={setupData.provisioning_uri} size={200} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Manual entry key</Label>
                <code className="block text-xs bg-muted p-2 rounded break-all select-all">
                  {setupData.secret}
                </code>
              </div>
              <div className="space-y-2">
                <Label htmlFor="verify-code">Verification code</Label>
                <Input
                  id="verify-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="000000"
                  maxLength={6}
                  pattern="[0-9]{6}"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? "Verifying..." : "Verify & Enable"}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Disable MFA Dialog */}
      <Dialog open={showDisableDialog} onOpenChange={(open) => { setShowDisableDialog(open); if (!open) { setError(""); setCode(""); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Disable Two-Factor Authentication</DialogTitle>
            <DialogDescription>
              Enter your current TOTP code to confirm disabling MFA.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleDisableMfa} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="disable-code">TOTP code</Label>
              <Input
                id="disable-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="000000"
                maxLength={6}
                pattern="[0-9]{6}"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" variant="destructive" className="w-full" disabled={submitting}>
              {submitting ? "Disabling..." : "Disable MFA"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
