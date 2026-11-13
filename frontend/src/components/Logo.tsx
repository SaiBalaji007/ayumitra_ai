import { useId } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

/** AyuMitra mark: a navy tile with a teal-to-mint care cross and a violet "insight" dot. */
export function LogoMark({ className }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn('size-8', className)}>
      <defs>
        <linearGradient id={`${id}-cross`} x1="8" y1="8" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--mint)" />
          <stop offset="1" stopColor="var(--teal)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="var(--navy)" />
      <path d="M16 9v14M9 16h14" stroke={`url(#${id}-cross)`} strokeWidth="3.6" strokeLinecap="round" />
      <circle cx="24.5" cy="7.5" r="3" fill="var(--violet)" />
    </svg>
  )
}

export function Logo({ to = '/', className }: { to?: string; className?: string }) {
  return (
    <Link to={to} className={cn('flex items-center gap-2 font-semibold tracking-tight', className)} aria-label="AyuMitra AI home">
      <LogoMark />
      <span className="text-lg">
        AyuMitra <span className="text-primary">AI</span>
      </span>
    </Link>
  )
}
