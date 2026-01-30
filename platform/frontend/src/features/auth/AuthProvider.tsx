import { createContext, useContext, useState, useCallback, type ReactNode } from "react"
import { login as apiLogin } from "@/api/auth"

interface AuthContextType {
  token: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("auth_token"))

  const login = useCallback(async (username: string, password: string) => {
    const key = await apiLogin(username, password)
    localStorage.setItem("auth_token", key)
    setToken(key)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token")
    setToken(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, isAuthenticated: !!token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
