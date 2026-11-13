import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { buttonVariants } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '#features', label: 'Features' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#safety', label: 'Safety' },
]

export default function MarketingLayout() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)

  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/75 backdrop-blur-lg">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav className="hidden items-center gap-8 text-sm text-muted-foreground md:flex">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} className="transition-colors hover:text-foreground">
                {n.label}
              </a>
            ))}
          </nav>
          <div className="hidden items-center gap-3 md:flex">
            <ThemeToggle />
            {user ? (
              <Link to="/app" className={buttonVariants()}>
                Open dashboard
              </Link>
            ) : (
              <>
                <Link to="/login" className={buttonVariants({ variant: 'ghost' })}>
                  Sign in
                </Link>
                <Link to="/register" className={buttonVariants()}>
                  Get started
                </Link>
              </>
            )}
          </div>
          <button
            type="button"
            className="grid size-10 place-items-center rounded-lg md:hidden"
            aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
        {open && (
          <div className="border-t px-4 py-4 md:hidden">
            <nav className="flex flex-col gap-1">
              {NAV.map((n) => (
                <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="rounded-md px-2 py-2 hover:bg-accent">
                  {n.label}
                </a>
              ))}
            </nav>
            <div className="mt-4 flex items-center gap-2">
              <ThemeToggle />
              <Link to={user ? '/app' : '/login'} className={cn(buttonVariants({ variant: 'outline' }), 'flex-1')}>
                {user ? 'Dashboard' : 'Sign in'}
              </Link>
              {!user && (
                <Link to="/register" className={cn(buttonVariants(), 'flex-1')}>
                  Get started
                </Link>
              )}
            </div>
          </div>
        )}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 sm:px-6 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm space-y-3">
            <Logo />
            <p className="text-sm text-muted-foreground">
              AI-Powered Medical Intelligence and Personalized Healthcare Platform.
            </p>
          </div>
          <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
            AyuMitra AI is an educational tool. It does not diagnose conditions, prescribe medicines or replace
            advice from a qualified doctor or pharmacist. In an emergency, contact local emergency services.
          </p>
        </div>
      </footer>
    </div>
  )
}
