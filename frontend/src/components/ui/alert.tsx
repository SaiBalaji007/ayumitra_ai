import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Alert({
  className,
  variant = 'default',
  ...props
}: HTMLAttributes<HTMLDivElement> & { variant?: 'default' | 'destructive' }) {
  return (
    <div
      role="alert"
      className={cn(
        'flex gap-3 rounded-lg border p-3 text-sm [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0',
        variant === 'destructive' && 'border-destructive/40 bg-destructive/8 text-destructive',
        className,
      )}
      {...props}
    />
  )
}
