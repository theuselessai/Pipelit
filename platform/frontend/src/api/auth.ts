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
