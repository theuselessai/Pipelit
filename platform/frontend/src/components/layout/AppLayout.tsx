import { useState, useEffect } from "react"
import { Outlet, NavLink, useNavigate } from "react-router-dom"
import { useAuth } from "@/features/auth/AuthProvider"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/hooks/useTheme"
import { useColorTheme } from "@/hooks/useColorTheme"
import { useWebSocket } from "@/hooks/useWebSocket"
import {
  LayoutDashboard,
  KeyRound,
  FolderOpen,
  Activity,
  Brain,
  Bot,
  ListTodo,
  LogOut,
  Workflow,
  ChevronLeft,
  ChevronRight,
  User,
  Settings,
} from "lucide-react"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Workflows" },
  { to: "/credentials", icon: KeyRound, label: "Credentials" },
  { to: "/workspaces", icon: FolderOpen, label: "Workspaces" },
  { to: "/executions", icon: Activity, label: "Executions" },
  { to: "/epics", icon: ListTodo, label: "Epics" },
  { to: "/memories", icon: Brain, label: "Memories" },
  { to: "/agent-users", icon: Bot, label: "Agent Users" },
]

export default function AppLayout() {
  const { logout, username } = useAuth()
  const navigate = useNavigate()
  useTheme() // keep theme in sync
  useColorTheme() // keep color theme in sync
  useWebSocket() // global authenticated WebSocket
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar_collapsed") === "true")

  useEffect(() => {
    localStorage.setItem("sidebar_collapsed", String(collapsed))
  }, [collapsed])

  return (
    <div className="flex h-screen">
      <aside
        className={`${
          collapsed ? "w-14" : "w-56"
        } border-r bg-sidebar text-sidebar-foreground flex flex-col transition-[width] duration-200`}
      >
        <div className="p-4 font-semibold text-lg border-b flex items-center justify-between min-h-[57px]">
          <div className={`flex items-center gap-2 overflow-hidden text-sidebar-primary ${collapsed ? "hidden" : ""}`}>
            <Workflow className="h-5 w-5 shrink-0" />
            <span>Pipelit</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              title={item.label}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-sidebar-accent/50"
                }`
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t space-y-1">
          <Button
            variant="ghost"
            className={`w-full ${collapsed ? "justify-center px-0" : "justify-start gap-2"}`}
            title="Settings"
            onClick={() => navigate("/settings")}
          >
            <Settings className="h-4 w-4 shrink-0" />
            {!collapsed && "Settings"}
          </Button>
          <Button
            variant="ghost"
            className={`w-full ${collapsed ? "justify-center px-0" : "justify-start gap-2"}`}
            title="Logout"
            onClick={logout}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {!collapsed && "Logout"}
          </Button>
        </div>
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
        <div className="border-t px-4 py-1.5 text-sm text-muted-foreground flex items-center gap-2">
          <User className="h-3.5 w-3.5" />
          <span>{username ?? "User"}</span>
        </div>
      </main>
    </div>
  )
}
