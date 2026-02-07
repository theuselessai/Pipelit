/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react"
import { login as apiLogin, fetchMe } from "@/api/auth"

interface AuthContextType {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
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

  const login = useCallback(async (user: string, password: string) => {
    const key = await apiLogin(user, password)
    localStorage.setItem("auth_token", key)
    setToken(key)
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
    <AuthContext.Provider value={{ token, username, isAuthenticated: !!token, login, logout, setToken: setTokenAndStore }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
