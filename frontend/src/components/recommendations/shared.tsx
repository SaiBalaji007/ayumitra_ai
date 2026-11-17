import { AlertTriangle, BookOpenCheck, ExternalLink, FileText, Info, Loader2, ShieldAlert, Stethoscope, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { formatDate } from '@/lib/format'
import { apiErrorMessage, type RecSource, type Recommendations } from '@/services/api'

const PROFILE_LABELS: Record<string, string> = {
  date_of_birth: 'date of birth',
  height_cm: 'height',
  weight_kg: 'weight',
  dietary_preference: 'dietary preference',
}

export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
      <Loader2 className="size-5 animate-spin text-primary" /> {label}
    </div>
  )
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle />
      {apiErrorMessage(error, 'Could not load your recommendations. Please try again.')}
    </Alert>
  )
}

export function DoctorBadge() {
  return (
    <Badge variant="warning">
      <Stethoscope className="size-3" /> Ask your doctor first
    </Badge>
  )
}

export function Sources({ sources }: { sources: RecSource[] }) {
  if (!sources.length) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <BookOpenCheck className="size-3.5" />
      {sources.map((s) => (
        <a key={s.url} href={s.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-primary hover:underline">
          {s.title} <ExternalLink className="size-3" />
        </a>
      ))}
    </div>
  )
}

export function DoctorNote({ text, strong }: { text: string; strong: boolean }) {
  if (!text) return null
  return (
    <p className={strong ? 'mt-3 flex gap-2 rounded-lg bg-warning/15 p-2.5 text-xs' : 'mt-3 flex gap-2 text-xs text-muted-foreground'}>
      <Stethoscope className="mt-0.5 size-3.5 shrink-0" /> {text}
    </p>
  )
}

/** What the recommendations were based on, what is missing, and any urgent alerts. */
export function BasisPanel({ data }: { data: Recommendations }) {
  const g = data.generated_from
  const missing = g.missing_profile_fields.map((f) => PROFILE_LABELS[f] ?? f)
  return (
    <div className="space-y-3">
      {data.alerts.map((a) => (
        <div key={a} role="alert" className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/8 p-3 text-sm font-medium text-destructive">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" /> {a}
        </div>
      ))}
      <Card>
        <CardContent className="grid gap-4 p-4 text-sm sm:grid-cols-2">
          <div className="flex gap-3">
            <FileText className="mt-0.5 size-4 shrink-0 text-primary" />
            <div>
              {g.reports_used === 0 ? (
                <>
                  <p className="font-medium">No lab results yet</p>
                  <p className="text-muted-foreground">
                    Showing general guidance only. <Link to="/app/documents" className="text-primary hover:underline">Upload a lab report</Link> to
                    get suggestions linked to your own results.
                  </p>
                </>
              ) : (
                <>
                  <p className="font-medium">
                    Based on {g.reports_used} report{g.reports_used === 1 ? '' : 's'}
                    {g.latest_report_date ? `, latest ${formatDate(g.latest_report_date)}` : ''}
                  </p>
                  <p className="text-muted-foreground">
                    {g.results_outside_range === 0
                      ? 'All your latest results are within the ranges printed by your laboratory.'
                      : `${g.results_outside_range} latest result${g.results_outside_range === 1 ? ' is' : 's are'} outside the lab's range: `}
                    {data.findings.map((f, i) => (
                      <span key={f.parameter}>
                        {i > 0 && ', '}
                        <Link to={`/app/reports/${f.report_id}`} className="text-primary hover:underline">
                          {f.label} {f.value_text} {f.unit} ({f.direction})
                        </Link>
                      </span>
                    ))}
                  </p>
                  {g.unverified_results.length > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Not yet checked by you: {g.unverified_results.join(', ')}. Confirm the values on the report page so suggestions use
                      the correct numbers.
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
          <div className="flex gap-3">
            <UserRound className="mt-0.5 size-4 shrink-0 text-primary" />
            <div>
              <p className="font-medium">Your profile</p>
              <p className="text-muted-foreground">
                {g.dietary_preference ? `Diet: ${g.dietary_preference}. ` : ''}
                {g.allergies_considered
                  ? g.allergy_groups_excluded.length
                    ? `Foods containing ${g.allergy_groups_excluded.join(', ')} are left out for your allergies. `
                    : 'Your allergy notes were checked against common allergens. '
                  : 'No allergies recorded. '}
                {missing.length > 0 && `Add your ${missing.join(', ')} in `}
                {missing.length > 0 && <Link to="/app/settings" className="text-primary hover:underline">Settings</Link>}
                {missing.length > 0 && ' for more relevant guidance.'}
              </p>
              {g.allergies_considered && (
                <p className="mt-1 text-xs text-muted-foreground">AyuMitra recognises common allergens only. Always check foods against your full allergy list.</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export function Disclaimer({ text }: { text: string }) {
  return (
    <p className="flex gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
      <Info className="mt-0.5 size-3.5 shrink-0" /> {text}
    </p>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">{title}</h3>
      {children}
    </section>
  )
}
