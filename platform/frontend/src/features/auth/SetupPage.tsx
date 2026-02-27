import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "./AuthProvider"
import {
  checkSetupStatus,
  setupUser,
  recheckEnvironment,
  checkRootfsStatus,
} from "@/api/auth"
import type { EnvironmentInfo } from "@/types/models"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  ChevronRight,
  ChevronLeft,
} from "lucide-react"

// ── Step Indicator ──────────────────────────────────────────────────────────

function StepIndicator({ current }: { current: number }) {
  const steps = ["Environment", "Account", "Done"]
  return (
    <div className="flex items-center justify-center gap-2 mb-6">
      {steps.map((label, i) => {
        const step = i + 1
        const completed = step < current
        const active = step === current
        return (
          <div key={label} className="flex items-center gap-2">
            {i > 0 && (
              <div
                className={`h-px w-8 ${
                  completed ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              />
            )}
            <div className="flex flex-col items-center gap-1">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-medium transition-colors ${
                  completed
                    ? "bg-primary text-primary-foreground"
                    : active
                      ? "border-2 border-primary text-primary"
                      : "border border-muted-foreground/30 text-muted-foreground"
                }`}
              >
                {completed ? <CheckCircle2 className="h-4 w-4" /> : step}
              </div>
              <span
                className={`text-xs ${
                  active ? "text-foreground font-medium" : "text-muted-foreground"
                }`}
              >
                {label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Status icon helper ──────────────────────────────────────────────────────

function StatusIcon({ status }: { status: "ok" | "warn" | "error" | "loading" }) {
  switch (status) {
    case "ok":
      return <CheckCircle2 className="h-4 w-4 text-emerald-500" />
    case "warn":
      return <AlertTriangle className="h-4 w-4 text-amber-500" />
    case "error":
      return <XCircle className="h-4 w-4 text-destructive" />
    case "loading":
      return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
  }
}

// ── Main Component ──────────────────────────────────────────────────────────

interface SetupConfig {
  database_url: string
  redis_url: string
  log_level: string
  platform_base_url: string
}

export default function SetupPage() {
  const { setToken } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState(1)
  const [checking, setChecking] = useState(true)
  const [environment, setEnvironment] = useState<EnvironmentInfo | null>(null)
  const [rechecking, setRechecking] = useState(false)

  // Step 2 state
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  // Advanced config
  const [config, setConfig] = useState<SetupConfig>({
    database_url: "",
    redis_url: "",
    log_level: "",
    platform_base_url: "",
  })

  // Rootfs polling
  const [rootfsPolling, setRootfsPolling] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Initial setup status check
  useEffect(() => {
    checkSetupStatus()
      .then((result) => {
        if (!result.needs_setup) {
          navigate("/login", { replace: true })
        } else {
          setEnvironment(result.environment)
          setChecking(false)
        }
      })
      .catch(() => setChecking(false))
  }, [navigate])

  // Start rootfs polling when in bwrap mode and rootfs not ready
  useEffect(() => {
    if (
      environment &&
      environment.sandbox_mode === "bwrap" &&
      !environment.rootfs_ready &&
      !rootfsPolling
    ) {
      setRootfsPolling(true)
      pollingRef.current = setInterval(async () => {
        try {
          const status = await checkRootfsStatus()
          if (status.ready) {
            setEnvironment((prev) =>
              prev ? { ...prev, rootfs_ready: true } : prev
            )
            setRootfsPolling(false)
            if (pollingRef.current) clearInterval(pollingRef.current)
          }
        } catch {
          // ignore
        }
      }, 3000)
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [environment, rootfsPolling])

  async function handleRecheck() {
    setRechecking(true)
    try {
      const env = await recheckEnvironment()
      setEnvironment(env)
    } catch {
      // ignore
    } finally {
      setRechecking(false)
    }
  }

  async function handleSetup(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    if (password !== confirmPassword) {
      setError("Passwords do not match")
      return
    }
    if (password.length < 4) {
      setError("Password must be at least 4 characters")
      return
    }
    setLoading(true)
    try {
      const key = await setupUser({
        username,
        password,
        sandbox_mode: environment?.sandbox_mode,
        database_url: config.database_url || undefined,
        redis_url: config.redis_url || undefined,
        log_level: config.log_level || undefined,
        platform_base_url: config.platform_base_url || undefined,
      })
      setToken(key)
      setStep(3)
    } catch {
      setError("Setup failed")
    } finally {
      setLoading(false)
    }
  }

  if (checking) return null

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Platform Setup</CardTitle>
        </CardHeader>
        <CardContent>
          <StepIndicator current={step} />

          {step === 1 && (
            <StepEnvironment
              environment={environment}
              rechecking={rechecking}
              onRecheck={handleRecheck}
              config={config}
              setConfig={setConfig}
              onNext={() => setStep(2)}
            />
          )}

          {step === 2 && (
            <StepAccount
              username={username}
              setUsername={setUsername}
              password={password}
              setPassword={setPassword}
              confirmPassword={confirmPassword}
              setConfirmPassword={setConfirmPassword}
              error={error}
              loading={loading}
              onBack={() => setStep(1)}
              onSubmit={handleSetup}
            />
          )}

          {step === 3 && <StepDone onNavigate={() => navigate("/")} />}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Step 1: Environment Check ───────────────────────────────────────────────

function StepEnvironment({
  environment,
  rechecking,
  onRecheck,
  config,
  setConfig,
  onNext,
}: {
  environment: EnvironmentInfo | null
  rechecking: boolean
  onRecheck: () => void
  config: SetupConfig
  setConfig: (c: SetupConfig) => void
  onNext: () => void
}) {
  if (!environment) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin" />
        <span className="ml-2">Detecting environment...</span>
      </div>
    )
  }

  const gatePassed = environment.gate.passed

  const items: { label: string; value: string; status: "ok" | "warn" | "error" | "loading" }[] = [
    {
      label: "Operating System",
      value: `${environment.os} (${environment.arch})`,
      status: "ok",
    },
    {
      label: "Sandbox Mode",
      value: environment.sandbox_mode,
      status: environment.sandbox_mode === "none" ? "warn" : "ok",
    },
    {
      label: "Bubblewrap (bwrap)",
      value: environment.bwrap_available ? "Available" : "Not found",
      status: environment.bwrap_available ? "ok" : environment.sandbox_mode === "bwrap" ? "error" : "warn",
    },
    {
      label: "Container",
      value: environment.container || "None",
      status: environment.container ? "ok" : "ok",
    },
    {
      label: "Rootfs",
      value: environment.rootfs_ready
        ? "Ready"
        : environment.sandbox_mode === "bwrap"
          ? "Not provisioned (will be created)"
          : "N/A",
      status: environment.rootfs_ready
        ? "ok"
        : environment.sandbox_mode === "bwrap"
          ? "loading"
          : "ok",
    },
    {
      label: "Tier 1 Tools",
      value: environment.tier1_met ? "All present" : "Missing",
      status: environment.tier1_met ? "ok" : "error",
    },
  ]

  // Add key runtimes
  const py = environment.capabilities.runtimes.python3
  if (py) {
    items.push({
      label: "Python",
      value: py.available ? (py.version || "Available") : "Not found",
      status: py.available ? "ok" : "error",
    })
  }
  const node = environment.capabilities.runtimes.node
  if (node) {
    items.push({
      label: "Node.js",
      value: node.available ? (node.version || "Available") : "Not found",
      status: node.available ? "ok" : "warn",
    })
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <tbody>
            {items.map((item) => (
              <tr key={item.label} className="border-b last:border-0">
                <td className="px-3 py-2 font-medium">{item.label}</td>
                <td className="px-3 py-2 text-right flex items-center justify-end gap-2">
                  <span className="text-muted-foreground">{item.value}</span>
                  <StatusIcon status={item.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!gatePassed && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Environment Not Supported</AlertTitle>
          <AlertDescription>{environment.gate.blocked_reason}</AlertDescription>
        </Alert>
      )}

      {gatePassed && environment.tier2_warnings.length > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Optional Tools Missing</AlertTitle>
          <AlertDescription>
            The following optional tools are not available:{" "}
            {environment.tier2_warnings.join(", ")}
          </AlertDescription>
        </Alert>
      )}

      <details className="group">
        <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
          Advanced Configuration
        </summary>
        <div className="mt-3 space-y-3">
          <Separator />
          <div className="space-y-2">
            <Label htmlFor="database_url">Database URL</Label>
            <Input
              id="database_url"
              placeholder="sqlite:///db.sqlite3"
              value={config.database_url}
              onChange={(e) => setConfig({ ...config, database_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="redis_url">Redis URL</Label>
            <Input
              id="redis_url"
              placeholder="redis://localhost:6379/0"
              value={config.redis_url}
              onChange={(e) => setConfig({ ...config, redis_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="log_level">Log Level</Label>
            <Select
              value={config.log_level}
              onValueChange={(v) => setConfig({ ...config, log_level: v })}
            >
              <SelectTrigger id="log_level">
                <SelectValue placeholder="Default (INFO)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="DEBUG">DEBUG</SelectItem>
                <SelectItem value="INFO">INFO</SelectItem>
                <SelectItem value="WARNING">WARNING</SelectItem>
                <SelectItem value="ERROR">ERROR</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="platform_base_url">Platform Base URL</Label>
            <Input
              id="platform_base_url"
              placeholder="http://localhost:8000"
              value={config.platform_base_url}
              onChange={(e) => setConfig({ ...config, platform_base_url: e.target.value })}
            />
          </div>
        </div>
      </details>

      <div className="flex justify-between pt-2">
        <Button variant="outline" onClick={onRecheck} disabled={rechecking}>
          {rechecking ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Checking...
            </>
          ) : (
            "Re-check"
          )}
        </Button>
        <Button onClick={onNext} disabled={!gatePassed}>
          Next
          <ChevronRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

// ── Step 2: Create Admin Account ────────────────────────────────────────────

function StepAccount({
  username,
  setUsername,
  password,
  setPassword,
  confirmPassword,
  setConfirmPassword,
  error,
  loading,
  onBack,
  onSubmit,
}: {
  username: string
  setUsername: (v: string) => void
  password: string
  setPassword: (v: string) => void
  confirmPassword: string
  setConfirmPassword: (v: string) => void
  error: string
  loading: boolean
  onBack: () => void
  onSubmit: (e: React.FormEvent) => void
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          autoFocus
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="confirmPassword">Confirm Password</Label>
        <Input
          id="confirmPassword"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex justify-between pt-2">
        <Button type="button" variant="outline" onClick={onBack}>
          <ChevronLeft className="mr-1 h-4 w-4" />
          Back
        </Button>
        <Button type="submit" disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Creating...
            </>
          ) : (
            "Create Account"
          )}
        </Button>
      </div>
    </form>
  )
}

// ── Step 3: Done ────────────────────────────────────────────────────────────

function StepDone({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div className="space-y-4 text-center">
      <div className="flex justify-center">
        <CheckCircle2 className="h-12 w-12 text-emerald-500" />
      </div>
      <h3 className="text-lg font-medium">Setup Complete</h3>
      <p className="text-sm text-muted-foreground">
        Your admin account has been created and the platform is configured.
      </p>
      <Button className="w-full" onClick={onNavigate}>
        Go to Dashboard
        <ChevronRight className="ml-1 h-4 w-4" />
      </Button>
    </div>
  )
}
