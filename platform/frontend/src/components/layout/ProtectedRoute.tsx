import { useEffect, useState } from "react"
import { Navigate, Outlet } from "react-router-dom"
import { useAuth } from "@/features/auth/AuthProvider"
import { checkSetupStatus } from "@/api/auth"

export default function ProtectedRoute() {
  const { isAuthenticated } = useAuth()
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)

  useEffect(() => {
    if (!isAuthenticated) {
      checkSetupStatus()
        .then((result) => setNeedsSetup(result.needs_setup))
        .catch(() => setNeedsSetup(false))
    }
  }, [isAuthenticated])

  if (isAuthenticated) return <Outlet />
  if (needsSetup === null) return null
  if (needsSetup) return <Navigate to="/setup" replace />
  return <Navigate to="/login" replace />
}
