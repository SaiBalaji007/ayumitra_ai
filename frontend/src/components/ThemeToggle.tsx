import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type Theme } from '@/contexts/ThemeContext'
import { cn } from '@/lib/utils'

const OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: 'light', label: 'Light theme', Icon: Sun },
  { value: 'dark', label: 'Dark theme', Icon: Moon },
  { value: 'system', label: 'System theme', Icon: Monitor },
]

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme()
  return (
    <div role="radiogroup" aria-label="Theme" className={cn('inline-flex rounded-lg border bg-muted/50 p-0.5', className)}>
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          aria-label={label}
          title={label}
          onClick={() => setTheme(value)}
          className={cn(
            'grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:text-foreground',
            theme === value && 'bg-background text-foreground shadow-sm',
          )}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  )
}
