import { useEffect, useState } from "react"
import { QRCodeSVG } from "qrcode.react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
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
