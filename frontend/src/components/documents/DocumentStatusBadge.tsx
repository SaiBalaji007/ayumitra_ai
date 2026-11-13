import { CheckCircle2, CircleDashed, Clock, Loader2, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { DocumentStatus } from '@/services/api'

const MAP: Record<DocumentStatus, { variant: 'secondary' | 'default' | 'success' | 'destructive' | 'outline'; Icon: typeof Clock; spin?: boolean }> = {
  uploaded: { variant: 'secondary', Icon: CircleDashed },
  queued: { variant: 'outline', Icon: Clock },
  processing: { variant: 'default', Icon: Loader2, spin: true },
  completed: { variant: 'success', Icon: CheckCircle2 },
  failed: { variant: 'destructive', Icon: XCircle },
}

export function DocumentStatusBadge({ status, label }: { status: DocumentStatus; label: string }) {
  const { variant, Icon, spin } = MAP[status]
  return (
    <Badge variant={variant}>
      <Icon className={spin ? 'size-3 animate-spin' : 'size-3'} />
      {label}
    </Badge>
  )
}
