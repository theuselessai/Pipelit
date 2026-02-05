import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AuthProvider } from "@/features/auth/AuthProvider"
import { Toaster } from "@/components/ui/sonner"
import ProtectedRoute from "@/components/layout/ProtectedRoute"
import AppLayout from "@/components/layout/AppLayout"
import LoginPage from "@/features/auth/LoginPage"
import SetupPage from "@/features/auth/SetupPage"
import DashboardPage from "@/features/workflows/DashboardPage"
import WorkflowEditorPage from "@/features/workflows/WorkflowEditorPage"
import CredentialsPage from "@/features/credentials/CredentialsPage"
import ExecutionsPage from "@/features/executions/ExecutionsPage"
import ExecutionDetailPage from "@/features/executions/ExecutionDetailPage"
import SettingsPage from "@/features/settings/SettingsPage"
import MemoriesPage from "@/features/memories/MemoriesPage"
import AgentUsersPage from "@/features/users/AgentUsersPage"

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/setup" element={<SetupPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/workflows/:slug" element={<WorkflowEditorPage />} />
                <Route path="/credentials" element={<CredentialsPage />} />
                <Route path="/executions" element={<ExecutionsPage />} />
                <Route path="/executions/:id" element={<ExecutionDetailPage />} />
                <Route path="/memories" element={<MemoriesPage />} />
                <Route path="/agent-users" element={<AgentUsersPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster />
      </AuthProvider>
    </QueryClientProvider>
  )
}
