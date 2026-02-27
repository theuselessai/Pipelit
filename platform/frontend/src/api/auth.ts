import { apiFetch } from "./client"
import type { EnvironmentInfo, RootfsStatus } from "@/types/models"

export interface LoginResult {
  key: string
  requires_mfa: boolean
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch("/api/v1/auth/token/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error("Invalid credentials")
  return res.json()
}

export async function loginVerifyMFA(username: string, code: string): Promise<LoginResult> {
  const res = await fetch("/api/v1/auth/mfa/login-verify/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, code }),
  })
  if (!res.ok) throw new Error("Invalid TOTP code")
  return res.json()
}

export async function fetchMe(): Promise<{ username: string; mfa_enabled: boolean }> {
  return apiFetch("/auth/me/")
}

export interface SetupStatusResult {
  needs_setup: boolean
  environment: EnvironmentInfo | null
}

export async function checkSetupStatus(): Promise<SetupStatusResult> {
  const res = await fetch("/api/v1/auth/setup-status/")
  if (!res.ok) throw new Error("Failed to check setup status")
  return res.json()
}

export interface SetupConfig {
  username: string
  password: string
  sandbox_mode?: string
  database_url?: string
  redis_url?: string
  log_level?: string
  platform_base_url?: string
}

export async function setupUser(config: SetupConfig): Promise<string> {
  const res = await fetch("/api/v1/auth/setup/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error("Setup failed")
  const data = await res.json()
  return data.key
}

export async function recheckEnvironment(): Promise<EnvironmentInfo> {
  const res = await fetch("/api/v1/auth/setup/recheck/", { method: "POST" })
  if (!res.ok) throw new Error("Recheck failed")
  const data = await res.json()
  return data.environment
}

export async function checkRootfsStatus(): Promise<RootfsStatus> {
  const res = await fetch("/api/v1/auth/setup/rootfs-status/")
  if (!res.ok) throw new Error("Failed to check rootfs status")
  return res.json()
}

// ── MFA management (authenticated) ─────────────────────────────────────────

export interface MFASetupResult {
  secret: string
  provisioning_uri: string
}

export async function mfaSetup(): Promise<MFASetupResult> {
  return apiFetch("/auth/mfa/setup/", { method: "POST" })
}

export async function mfaVerify(code: string): Promise<{ mfa_enabled: boolean }> {
  return apiFetch("/auth/mfa/verify/", {
    method: "POST",
    body: JSON.stringify({ code }),
  })
}

export async function mfaDisable(code: string): Promise<{ mfa_enabled: boolean }> {
  return apiFetch("/auth/mfa/disable/", {
    method: "POST",
    body: JSON.stringify({ code }),
  })
}

export async function mfaStatus(): Promise<{ mfa_enabled: boolean }> {
  return apiFetch("/auth/mfa/status/")
}
