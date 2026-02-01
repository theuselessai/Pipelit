export async function login(username: string, password: string): Promise<string> {
  const res = await fetch("/api/v1/auth/token/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error("Invalid credentials")
  const data = await res.json()
  return data.key
}

export async function checkSetupStatus(): Promise<boolean> {
  const res = await fetch("/api/v1/auth/setup-status/")
  if (!res.ok) throw new Error("Failed to check setup status")
  const data = await res.json()
  return data.needs_setup
}

export async function setupUser(username: string, password: string): Promise<string> {
  const res = await fetch("/api/v1/auth/setup/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error("Setup failed")
  const data = await res.json()
  return data.key
}
