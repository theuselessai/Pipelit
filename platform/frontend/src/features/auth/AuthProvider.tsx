/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react"
import { login as apiLogin, loginVerifyMFA as apiLoginVerifyMFA, fetchMe } from "@/api/auth"

interface LoginResult {
  authenticated: boolean
  requiresMfa: boolean
}

interface AuthContextType {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<LoginResult>
  loginWithMfa: (username: string, code: string) => Promise<void>
  logout: () => void
  setToken: (key: string) => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("auth_token"))
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem("auth_username"))

  useEffect(() => {
    if (token && !username) {
      fetchMe()
        .then((data) => {
          localStorage.setItem("auth_username", data.username)
          setUsername(data.username)
        })
        .catch(() => {
          // token invalid
        })
    }
  }, [token, username])

  const login = useCallback(async (user: string, password: string): Promise<LoginResult> => {
    const result = await apiLogin(user, password)

    if (result.requires_mfa) {
      return { authenticated: false, requiresMfa: true }
    }

    localStorage.setItem("auth_token", result.key)
    setToken(result.key)
    localStorage.setItem("auth_username", user)
    setUsername(user)
    return { authenticated: true, requiresMfa: false }
  }, [])

  const loginWithMfa = useCallback(async (user: string, code: string) => {
    const result = await apiLoginVerifyMFA(user, code)
    localStorage.setItem("auth_token", result.key)
    setToken(result.key)
    localStorage.setItem("auth_username", user)
    setUsername(user)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token")
    localStorage.removeItem("auth_username")
    setToken(null)
    setUsername(null)
  }, [])

  const setTokenAndStore = useCallback((key: string) => {
    localStorage.setItem("auth_token", key)
    setToken(key)
  }, [])

  return (
    <AuthContext.Provider value={{ token, username, isAuthenticated: !!token, login, loginWithMfa, logout, setToken: setTokenAndStore }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
