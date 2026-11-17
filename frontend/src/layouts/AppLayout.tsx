import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareText,
  Pill,
  Settings,
  FlaskConical,
  Salad,
  HeartPulse,
  Hospital,
  ScanText,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

const APP_NAV = [
  { to: '/app', label: 'Dashboard', Icon: LayoutDashboard, end: true },
  { to: '/app/documents', label: 'Documents', Icon: FileText },
  { to: '/app/reports', label: 'Medical reports', Icon: FlaskConical },
  { to: '/app/prescription-analyzer', label: 'Prescription Analyzer', Icon: ScanText },
  { to: '/app/nearby', label: 'Find Hospitals & Medical Shops', Icon: Hospital },
  { to: '/app/prescriptions', label: 'Prescriptions', Icon: Pill },
  { to: '/app/assistant', label: 'AI Assistant', Icon: MessageSquareText },
  { to: '/app/diet', label: 'Diet recommendations', Icon: Salad },
  { to: '/app/lifestyle', label: 'Lifestyle recommendations', Icon: HeartPulse },
  { to: '/app/timeline', label: 'Health timeline', Icon: Activity },
] as const

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth()
  const initials = `${user?.first_name?.[0] ?? ''}${user?.last_name?.[0] ?? ''}`.toUpperCase() || '?'

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
      isActive && 'bg-accent font-medium text-accent-foreground',
    )

  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <Logo to="/app" className="px-2 pt-1" />
      <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
        {APP_NAV.map(({ to, label, Icon, ...rest }) => (
          <NavLink key={to} to={to} end={'end' in rest} className={linkClass} onClick={onNavigate}>
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-3 border-t pt-4">
        <NavLink to="/app/settings" className={linkClass} onClick={onNavigate}>
          <Settings className="size-4" />
          Settings
        </NavLink>
        <div className="flex items-center gap-3 px-2">
          <div className="grid size-9 place-items-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {user?.first_name} {user?.last_name}
            </p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
          </div>
          <button
            type="button"
            onClick={logout}
            aria-label="Sign out"
            title="Sign out"
            className="grid size-8 cursor-pointer place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const current = [...APP_NAV].reverse().find((n) => location.pathname.startsWith(n.to))
  const title = location.pathname.startsWith('/app/settings') ? 'Settings' : (current?.label ?? 'Dashboard')

  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMobileOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileOpen])

  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[260px_1fr]">
      <aside className="sticky top-0 hidden h-svh border-r bg-sidebar lg:block">
        <SidebarContent />
      </aside>

      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <motion.div
              className="absolute inset-0 bg-black/40"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
            />
            <motion.aside
              className="absolute inset-y-0 left-0 w-72 border-r bg-sidebar shadow-xl"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            >
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setMobileOpen(false)}
                className="absolute top-4 right-3 grid size-9 place-items-center rounded-md hover:bg-accent"
              >
                <X className="size-4" />
              </button>
              <SidebarContent onNavigate={() => setMobileOpen(false)} />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-lg sm:px-6">
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMobileOpen(true)}
            className="grid size-9 place-items-center rounded-md hover:bg-accent lg:hidden"
          >
            <Menu className="size-5" />
          </button>
          <h1 className="flex-1 truncate text-base font-semibold">{title}</h1>
          <ThemeToggle />
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
