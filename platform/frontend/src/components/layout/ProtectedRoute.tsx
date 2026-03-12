import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/features/auth/AuthProvider"

export default function ProtectedRoute() {
  const { isAuthenticated } = useAuth()

  if (isAuthenticated) return <Outlet />
  return <Navigate to="/login" replace />
}
