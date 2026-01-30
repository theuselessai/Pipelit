import { Outlet, NavLink } from "react-router-dom"
import { useAuth } from "@/features/auth/AuthProvider"
import { Button } from "@/components/ui/button"
import { LayoutDashboard, KeyRound, Activity, Settings, LogOut } from "lucide-react"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Workflows" },
  { to: "/credentials", icon: KeyRound, label: "Credentials" },
  { to: "/executions", icon: Activity, label: "Executions" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

export default function AppLayout() {
  const { logout } = useAuth()

  return (
    <div className="flex h-screen">
      <aside className="w-56 border-r bg-sidebar text-sidebar-foreground flex flex-col">
        <div className="p-4 font-semibold text-lg border-b">Workflow Platform</div>
        <nav className="flex-1 p-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-sidebar-accent/50"
                }`
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t">
          <Button variant="ghost" className="w-full justify-start gap-2" onClick={logout}>
            <LogOut className="h-4 w-4" /> Logout
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
