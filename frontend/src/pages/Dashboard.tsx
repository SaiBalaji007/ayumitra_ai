import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Circle,
  FileText,
  FileUp,
  MessageSquareText,
  Pill,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'
import { DocumentStatusBadge } from '@/components/documents/DocumentStatusBadge'
import { formatBytes, formatDate } from '@/lib/format'
import { api, documentsApi, getHealth, type Paginated } from '@/services/api'
import { cn } from '@/lib/utils'

const QUICK_ACTIONS = [
  { to: '/app/documents', Icon: FileUp, title: 'Upload a report', body: 'PDF or photo of a lab report' },
  { to: '/app/prescriptions', Icon: Pill, title: 'Add a prescription', body: 'Printed or handwritten' },
  { to: '/app/assistant', Icon: MessageSquareText, title: 'Ask the assistant', body: 'Evidence-backed answers' },
]

/** All counts come from the API. "Reports analyzed" stays 0 until extraction (Phase 4–5) produces reports. */
function useDashboardData() {
  const recent = useQuery({ queryKey: ['documents', 'recent'], queryFn: () => documentsApi.list({ page: 1 }) })
  const labs = useQuery({ queryKey: ['documents', 'count', 'lab_report'], queryFn: () => documentsApi.list({ document_type: 'lab_report' }) })
  const rx = useQuery({ queryKey: ['documents', 'count', 'prescription'], queryFn: () => documentsApi.list({ document_type: 'prescription' }) })
  const analyzed = useQuery({
    queryKey: ['reports', 'count'],
    queryFn: () => api.get<Paginated<unknown>>('/reports/').then((r) => r.data),
  })
  return { recent, labs, rx, analyzed }
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

function EmptyState({ Icon, title, body, action }: { Icon: typeof FileText; title: string; body: string; action?: { to: string; label: string } }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-12 text-center">
      <div className="mb-4 grid size-12 place-items-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-5" />
      </div>
      <p className="font-medium">{title}</p>
      <p className="mt-1 max-w-xs text-sm text-muted-foreground">{body}</p>
      {action && (
        <Link to={action.to} className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'mt-5')}>
          {action.label}
        </Link>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 60_000 })
  const { recent, labs, rx, analyzed } = useDashboardData()
  const docCount = recent.data?.count

  const STATS = [
    { label: 'Documents', value: docCount, Icon: FileText },
    { label: 'Lab reports', value: labs.data?.count, Icon: Activity },
    { label: 'Prescriptions', value: rx.data?.count, Icon: Pill },
    { label: 'Reports analyzed', value: analyzed.data?.count, Icon: Sparkles },
  ]

  const steps = [
    { done: true, label: 'Create your account' },
    { done: (docCount ?? 0) > 0, label: 'Upload your first lab report' },
    { done: false, label: 'Review the extracted parameters' },
    { done: false, label: 'Ask a question about your results' },
  ]
  const doneCount = steps.filter((s) => s.done).length

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {greeting()}, {user?.first_name}
          </h2>
          <p className="mt-1 text-muted-foreground">Here's an overview of your medical documents.</p>
        </div>
        <Link to="/app/documents" className={buttonVariants()}>
          <FileUp /> Upload document
        </Link>
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {STATS.map(({ label, value, Icon }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="text-xs font-medium sm:text-sm">{label}</span>
                  <Icon className="size-4" />
                </div>
                <p className="mt-3 text-3xl font-semibold tabular-nums">{value ?? '–'}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="grid gap-4 md:grid-cols-3">
        {QUICK_ACTIONS.map(({ to, Icon, title, body }) => (
          <Link
            key={to}
            to={to}
            className="group flex items-center gap-4 rounded-xl border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-md hover:shadow-primary/5"
          >
            <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/12 text-primary">
              <Icon className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{title}</p>
              <p className="text-sm text-muted-foreground">{body}</p>
            </div>
            <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-primary" />
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent documents</CardTitle>
            <CardDescription>Reports and prescriptions you've uploaded.</CardDescription>
          </CardHeader>
          <CardContent>
            {recent.data && recent.data.results.length > 0 ? (
              <ul className="divide-y">
                {recent.data.results.slice(0, 5).map((d) => (
                  <li key={d.id} className="flex items-center gap-3 py-3">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{d.title || d.original_filename}</p>
                      <p className="text-xs text-muted-foreground">
                        {d.document_type_display} · {formatBytes(d.file_size)} · {formatDate(d.created_at)}
                      </p>
                    </div>
                    <DocumentStatusBadge status={d.status} label={d.status_display} />
                  </li>
                ))}
                <li className="pt-3">
                  <Link to="/app/documents" className="text-sm font-medium text-primary hover:underline">
                    View all documents
                  </Link>
                </li>
              </ul>
            ) : (
              <EmptyState
                Icon={FileText}
                title={recent.isLoading ? 'Loading…' : 'No documents yet'}
                body="Upload a lab report or prescription and its processing status will appear here."
                action={{ to: '/app/documents', label: 'Upload a document' }}
              />
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Getting started</CardTitle>
                <Badge variant="secondary">
                  {doneCount}/{steps.length}
                </Badge>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
              </div>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3 text-sm">
                {steps.map((s) => (
                  <li key={s.label} className={cn('flex items-center gap-3', s.done && 'text-muted-foreground line-through')}>
                    {s.done ? <CheckCircle2 className="size-4 text-success" /> : <Circle className="size-4 text-muted-foreground" />}
                    {s.label}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="size-4 text-primary" /> System status
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <StatusRow label="API" ok={health.isSuccess} pending={health.isLoading} />
              <StatusRow label="Database" ok={health.data?.database !== undefined && health.data.database !== 'unavailable'} pending={health.isLoading} />
              <StatusRow label="AI engine" ok={false} pending={false} note="Coming in Phase 8" />
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Parameter trends</CardTitle>
          <CardDescription>Track lab values like glucose or hemoglobin across reports over time.</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState Icon={Activity} title="Trends need at least two reports" body="Once you upload reports from different dates, matching parameters are charted here." />
        </CardContent>
      </Card>
    </div>
  )
}

function StatusRow({ label, ok, pending, note }: { label: string; ok: boolean; pending: boolean; note?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2">
        {note ?? (pending ? 'Checking…' : ok ? 'Operational' : 'Unavailable')}
        <span
          className={cn(
            'size-2 rounded-full',
            pending ? 'animate-pulse bg-muted-foreground' : ok ? 'bg-success' : note ? 'bg-muted-foreground/40' : 'bg-destructive',
          )}
        />
      </span>
    </div>
  )
}
