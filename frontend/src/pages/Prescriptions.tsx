import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader2, Pill } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { apiErrorMessage, prescriptionsApi, type Prescription, type PrescriptionMedicine } from '@/services/api'

const FIELDS: { key: keyof PrescriptionMedicine; label: string; review?: string }[] = [
  { key: 'name_as_written', label: 'Medicine (as written)', review: 'name' },
  { key: 'strength', label: 'Strength', review: 'strength' },
  { key: 'frequency', label: 'Frequency', review: 'frequency' },
  { key: 'timing', label: 'Timing' },
  { key: 'duration', label: 'Duration', review: 'duration' },
]

// oxlint-disable-next-line react/only-export-components -- reused by the Prescription Analyzer page
export function MedicineCard({ rx, med }: { rx: Prescription; med: PrescriptionMedicine }) {
  const qc = useQueryClient()
  const [form, setForm] = useState(() => Object.fromEntries(FIELDS.map((f) => [f.key, String(med[f.key] ?? '')])))
  const [suggestion, setSuggestion] = useState('')
  const save = useMutation({
    mutationFn: (confirm: boolean) =>
      prescriptionsApi.updateMedicine(rx.id, med.id, { ...form, ...(suggestion ? { choose_suggestion: suggestion } : {}), user_confirmed: confirm }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['prescription', rx.id] }),
  })
  const remove = useMutation({
    mutationFn: () => prescriptionsApi.removeMedicine(rx.id, med.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['prescription', rx.id] }),
  })
  const suggestions = med.field_confidence?.suggestions ?? []
  const status = med.field_confidence?.match_status

  return (
    <div className={cn('rounded-xl border p-4', med.user_confirmed && 'border-success/50 bg-success/5')}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          Line {med.line_number}
          {med.generic_name && <span className="ml-2 text-sm font-normal text-muted-foreground">Generic (RxNorm): {med.generic_name}</span>}
        </p>
        {med.user_confirmed ? <Badge variant="success"><CheckCircle2 className="size-3" /> Confirmed</Badge>
          : med.fields_needing_review.length ? <Badge variant="warning"><AlertTriangle className="size-3" /> Needs your check</Badge>
          : <Badge variant="outline">Not yet confirmed</Badge>}
      </div>
      {status === 'suggestion' && !med.generic_name && (
        <div className="mb-3 rounded-lg bg-warning/15 p-3 text-xs">
          AyuMitra couldn't read this medicine name with certainty and will not guess. If one of these RxNorm names matches your
          prescription, select it; otherwise type the name exactly as written.
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button key={s.rxcui} type="button" onClick={() => setSuggestion(s.name === suggestion ? '' : s.name)}
                className={cn('cursor-pointer rounded-full border px-2.5 py-1', suggestion === s.name && 'border-primary bg-primary/10 font-medium')}>
                {s.name}
              </button>
            ))}
          </div>
        </div>
      )}
      {status === 'unrecognized' && (
        <p className="mb-3 rounded-lg bg-warning/15 p-3 text-xs">This name isn't in RxNorm (many Indian brand names aren't). Please check it against your prescription.</p>
      )}
      <div className="grid gap-3 sm:grid-cols-5">
        {FIELDS.map((f) => {
          const flagged = f.review && med.fields_needing_review.includes(f.review)
          return (
            <div key={f.key} className="space-y-1">
              <Label htmlFor={`${med.id}-${f.key}`} className={cn('text-xs', flagged && 'text-warning')}>
                {f.label}{flagged ? ' *' : ''}
              </Label>
              <Input id={`${med.id}-${f.key}`} className={cn('h-9', flagged && 'border-warning')} value={form[f.key]}
                placeholder={flagged ? 'Not read: check' : ''} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
            </div>
          )
        })}
      </div>
      {med.field_confidence?.frequency_reading && (
        <p className="mt-2 text-xs text-muted-foreground">"{med.frequency}" usually means: {med.field_confidence.frequency_reading}</p>
      )}
      <div className="mt-3 flex justify-end gap-2">
        {save.isError && <p className="mr-auto text-xs text-destructive">{apiErrorMessage(save.error)}</p>}
        <Button variant="ghost" size="sm" className="mr-auto text-muted-foreground hover:text-destructive" disabled={remove.isPending}
          onClick={() => { if (window.confirm('Remove this line? Use this only if it is not a medicine (e.g. clinic name).')) remove.mutate() }}>
          Remove line
        </Button>
        <Button variant="outline" size="sm" onClick={() => save.mutate(false)} disabled={save.isPending}>Save</Button>
        <Button size="sm" onClick={() => save.mutate(true)} disabled={save.isPending}>
          {save.isPending && <Loader2 className="animate-spin" />} Matches my prescription
        </Button>
      </div>
    </div>
  )
}

function PrescriptionDetail({ id }: { id: number }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['prescription', id], queryFn: () => prescriptionsApi.get(id) })
  const verify = useMutation({ mutationFn: () => prescriptionsApi.verify(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['prescription', id] }) })
  if (q.isLoading) return <Loader2 className="size-5 animate-spin text-primary" />
  if (q.isError || !q.data) return <Alert variant="destructive">{apiErrorMessage(q.error)}</Alert>
  const rx = q.data
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <Link to="/app/prescriptions" className="text-sm text-primary hover:underline">← All prescriptions</Link>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Review prescription</h2>
        <p className="text-sm text-muted-foreground">
          Check each line against your paper prescription. Fields marked * couldn't be read confidently. AyuMitra never fills in a missing dose,
          frequency or duration.
        </p>
      </div>
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2"><Pill className="size-4 text-primary" /> Medicines</CardTitle>
            <CardDescription>{rx.user_verified ? `Verified on ${formatDate(rx.verified_at!)}` : 'Not verified yet'}</CardDescription>
          </div>
          <Button onClick={() => verify.mutate()} disabled={rx.user_verified || verify.isPending || rx.medicines.some((m) => !m.user_confirmed)}>
            {rx.user_verified ? 'Verified' : 'Mark prescription as verified'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {verify.isError && <Alert variant="destructive">{apiErrorMessage(verify.error)}</Alert>}
          {rx.medicines.map((m) => <MedicineCard key={`${m.id}-${m.user_confirmed}`} rx={rx} med={m} />)}
          {rx.medicines.length === 0 && <p className="text-sm text-muted-foreground">No medicine lines were found on this document.</p>}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">Always follow your doctor's instructions. Ask your pharmacist if anything on the prescription is unclear.</p>
    </div>
  )
}

function PrescriptionList() {
  const q = useQuery({ queryKey: ['prescriptions'], queryFn: prescriptionsApi.list })
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Prescriptions</h2>
        <p className="mt-1 text-muted-foreground">Medicines read from your uploaded prescriptions, waiting for your confirmation.</p>
      </div>
      {q.isError && <Alert variant="destructive">{apiErrorMessage(q.error)}</Alert>}
      {q.data?.results.length === 0 && (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          No prescriptions yet. <Link to="/app/documents" className="text-primary hover:underline">Upload one</Link> as type "Prescription".
        </CardContent></Card>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {q.data?.results.map((rx) => (
          <Link key={rx.id} to={`/app/prescriptions/${rx.id}`} className="rounded-xl border bg-card p-5 hover:shadow-md">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{rx.medicines.length} medicine{rx.medicines.length === 1 ? '' : 's'}</p>
              {rx.user_verified ? <Badge variant="success">Verified</Badge> : <Badge variant="warning">Needs review</Badge>}
            </div>
            <p className="mt-1 truncate text-sm text-muted-foreground">{rx.medicines.map((m) => m.name_as_written).join(', ')}</p>
            <p className="mt-1 text-xs text-muted-foreground">{formatDate(rx.created_at)}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}

export default function Prescriptions() {
  const { id } = useParams()
  return id ? <PrescriptionDetail id={Number(id)} /> : <PrescriptionList />
}
