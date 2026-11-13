import { Loader2 } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'

function FullScreenSpinner() {
  return (
    <div className="grid min-h-svh place-items-center">
      <Loader2 className="size-6 animate-spin text-primary" aria-label="Loading" />
    </div>
  )
}

/** Only signed-in users. Remembers where they were headed. */
export function RequireAuth() {
  const { user, initializing } = useAuth()
  const location = useLocation()
  if (initializing) return <FullScreenSpinner />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

/** Login/register pages: send signed-in users straight to the app. */
export function GuestOnly() {
  const { user, initializing } = useAuth()
  if (initializing) return <FullScreenSpinner />
  if (user) return <Navigate to="/app" replace />
  return <Outlet />
}
