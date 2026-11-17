import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  AlertTriangle, BookOpenCheck, CalendarClock, CheckCircle2, ExternalLink, FileText, Info, Loader2, Pill,
  RotateCcw, ScanText, ShieldAlert, Trash2, UploadCloud, X,
} from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { MedicineCard } from '@/pages/Prescriptions'
import {
  apiErrorMessage, documentsApi, prescriptionsApi, type MedicineInfo, type PrescriptionInsights,
} from '@/services/api'

const MAX_MB = 20
const ACCEPT = '.jpg,.jpeg,.png,.pdf'

function Section({ icon, title, description, children, className }: { icon: ReactNode; title: string; description?: string; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base"><span className="grid size-8 place-items-center rounded-lg bg-primary/12 text-primary">{icon}</span>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

/** Upload → wait for OCR + extraction → returns the prescription id. */
function UploadCard({ onReady }: { onReady: (rxId: number) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState<'idle' | 'uploading' | 'reading' | 'error'>('idle')
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  function choose(f: File | undefined) {
    if (!f) return
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!['jpg', 'jpeg', 'png', 'pdf'].includes(ext)) return setError('Please choose a JPG, PNG or PDF file.')
    if (f.size > MAX_MB * 1024 * 1024) return setError(`The file is larger than ${MAX_MB} MB.`)
    setError('')
    setStage('idle')
    setFile(f)
    setPreview(f.type.startsWith('image/') ? URL.createObjectURL(f) : null)
  }

  async function analyze() {
    if (!file) return
    setError('')
    try {
      setStage('uploading')
      let doc: { id: string }
      try {
        doc = await documentsApi.upload(file, { document_type: 'prescription', onProgress: setProgress })
      } catch (err) {
        // Same file uploaded before: open its existing analysis instead of failing.
        const dup = isAxiosError(err) ? (err.response?.data as { duplicate_of?: string } | undefined)?.duplicate_of : undefined
        if (!dup) throw err
        doc = { id: dup }
      }
      setStage('reading')
      for (let i = 0; i < 120; i++) { // up to ~6 minutes for multi-page PDFs on CPU
        const st = await documentsApi.status(doc.id)
        if (st.status === 'failed') throw new Error(st.error_message || 'The prescription could not be read.')
        if (st.status === 'completed') break
        await new Promise((r) => setTimeout(r, 3000))
      }
      const list = await prescriptionsApi.list()
      const rx = list.results.find((p) => p.document_id === doc.id)
      if (!rx) throw new Error('No medicines could be found in this file. Is it a prescription?')
      onReady(rx.id)
      setStage('idle')
    } catch (e) {
      setStage('error')
      setError(e instanceof Error && !('isAxiosError' in e) ? e.message : apiErrorMessage(e, 'Upload failed.'))
    }
  }

  const busy = stage === 'uploading' || stage === 'reading'
  return (
    <Section icon={<UploadCloud className="size-4" />} title="Upload prescription"
      description="Handwritten, printed or scanned: a photo (JPG/PNG) or a PDF, up to 20 MB. A sharp, well-lit photo works best.">
      {!file ? (
        <button type="button" onClick={() => input.current?.click()}
          onDragOver={(e: DragEvent) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e: DragEvent) => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files[0]) }}
          className={cn('flex w-full cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-10 text-center transition-colors hover:border-primary/60 hover:bg-primary/5', drag && 'border-primary bg-primary/10')}>
          <span className="grid size-12 place-items-center rounded-full bg-primary/12 text-primary"><UploadCloud className="size-6" /></span>
          <span className="font-medium">Drag your prescription here or click to browse</span>
          <span className="text-xs text-muted-foreground">JPG, JPEG, PNG or PDF · stored privately, visible only to you</span>
        </button>
      ) : (
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="grid h-48 w-full shrink-0 place-items-center overflow-hidden rounded-xl border bg-muted/30 sm:w-56">
            {preview ? <img src={preview} alt="Prescription preview" className="h-full w-full object-contain" />
              : <FileText className="size-12 text-muted-foreground" />}
          </div>
          <div className="flex flex-1 flex-col gap-3">
            <div>
              <p className="font-medium break-all">{file.name}</p>
              <p className="text-xs text-muted-foreground">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
            {busy && (
              <div className="space-y-1.5">
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div className={cn('h-full bg-primary transition-all', stage === 'reading' && 'animate-pulse')} style={{ width: stage === 'reading' ? '100%' : `${progress}%` }} />
                </div>
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" />
                  {stage === 'uploading' ? `Uploading… ${progress}%` : 'Reading the prescription (OCR + medicine extraction)… this can take up to a minute.'}
                </p>
              </div>
            )}
            <div className="mt-auto flex flex-wrap gap-2">
              <Button onClick={analyze} disabled={busy}><ScanText /> Analyze prescription</Button>
              <Button variant="outline" disabled={busy} onClick={() => input.current?.click()}><RotateCcw /> Replace</Button>
              <Button variant="ghost" disabled={busy} onClick={() => { setFile(null); setPreview(null); setError('') }}><X /> Remove</Button>
            </div>
          </div>
        </div>
      )}
      <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => { choose(e.target.files?.[0]); e.target.value = '' }} />
      {error && <Alert variant="destructive" className="mt-3"><AlertTriangle />{error}</Alert>}
    </Section>
  )
}

function InfoCard({ info }: { info: MedicineInfo }) {
  const rows: [string, string | undefined][] = [
    ['Used for', info.uses], ['Common side effects', info.side_effects], ['Important warnings', info.warnings],
    ['Do not use if (contraindications)', info.contraindications], ['Interactions (from the label)', info.interactions_note],
  ]
  return (
    <div className="rounded-xl border p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">{info.generic_name}</p>
        {info.drug_class && <Badge variant="secondary">{info.drug_class}</Badge>}
      </div>
      <dl className="mt-3 space-y-2">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}><dt className="text-xs font-semibold text-primary uppercase">{k}</dt><dd className="text-muted-foreground">{v}</dd></div>
        ))}
      </dl>
      <a href={info.source_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline">
        <BookOpenCheck className="size-3.5" /> {info.source_title} <ExternalLink className="size-3" />
      </a>
      <p className="text-[11px] text-muted-foreground">Retrieved {info.retrieved}. Official U.S. FDA label: wording is technical; ask your pharmacist what applies to you.</p>
    </div>
  )
}

const ADD_FIELDS = [
  { key: 'name_as_written', label: 'Medicine name *', placeholder: 'e.g. Pan 40' },
  { key: 'strength', label: 'Strength', placeholder: 'e.g. 40 mg' },
  { key: 'frequency', label: 'Frequency', placeholder: 'e.g. 1-0-1 or BD' },
  { key: 'timing', label: 'Timing', placeholder: 'e.g. before food' },
  { key: 'duration', label: 'Duration', placeholder: 'e.g. 5 days' },
] as const

/** Lets the user type a medicine the OCR missed, exactly as written on the paper prescription. */
function AddMedicine({ rxId }: { rxId: number }) {
  const qc = useQueryClient()
  const empty = { name_as_written: '', strength: '', frequency: '', timing: '', duration: '' }
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(empty)
  const add = useMutation({
    mutationFn: () => prescriptionsApi.addMedicine(rxId, form),
    onSuccess: () => { setForm(empty); setOpen(false); qc.invalidateQueries({ queryKey: ['prescription', rxId] }) },
  })
  if (!open) {
    return <Button variant="outline" onClick={() => setOpen(true)}><Pill /> Add a medicine the reader missed</Button>
  }
  return (
    <div className="rounded-xl border border-dashed border-primary/50 p-4">
      <p className="mb-3 text-sm font-medium">Type the medicine exactly as written on your prescription</p>
      <div className="grid gap-3 sm:grid-cols-5">
        {ADD_FIELDS.map((f) => (
          <label key={f.key} className="space-y-1 text-xs">
            <span className="text-muted-foreground">{f.label}</span>
            <input value={form[f.key]} placeholder={f.placeholder} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm" />
          </label>
        ))}
      </div>
      {add.isError && <Alert variant="destructive" className="mt-3"><AlertTriangle />{apiErrorMessage(add.error)}</Alert>}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => { setOpen(false); setForm(empty) }}>Cancel</Button>
        <Button size="sm" disabled={add.isPending || form.name_as_written.trim().length < 2} onClick={() => add.mutate()}>
          {add.isPending && <Loader2 className="animate-spin" />} Add medicine
        </Button>
      </div>
    </div>
  )
}

function Results({ rxId }: { rxId: number }) {
  const qc = useQueryClient()
  const rx = useQuery({ queryKey: ['prescription', rxId], queryFn: () => prescriptionsApi.get(rxId) })
  const ins = useQuery({ queryKey: ['rx-insights', rxId, rx.data?.updated_at], queryFn: () => prescriptionsApi.insights(rxId), enabled: Boolean(rx.data) })
  const verify = useMutation({ mutationFn: () => prescriptionsApi.verify(rxId), onSuccess: () => qc.invalidateQueries({ queryKey: ['prescription', rxId] }) })

  if (rx.isPending) return <div className="flex justify-center py-10"><Loader2 className="size-6 animate-spin text-primary" /></div>
  if (rx.isError) return <Alert variant="destructive"><AlertTriangle />{apiErrorMessage(rx.error)}</Alert>
  const p = rx.data
  const data: PrescriptionInsights | undefined = ins.data
  const pending = p.medicines.filter((m) => !m.user_confirmed).length

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
        <Section icon={<ScanText className="size-4" />} title="OCR extracted text" description="Exactly what the text reader saw. Words in the medicines list below are checked against this.">
          {ins.isPending ? <Loader2 className="size-5 animate-spin text-primary" /> : (
            <pre className="max-h-80 overflow-auto rounded-lg bg-muted/40 p-3 text-xs whitespace-pre-wrap">
              {data?.ocr_pages.map((pg) => `${data.ocr_pages.length > 1 ? `— Page ${pg.page} —\n` : ''}${pg.text}`).join('\n\n') || 'No text found.'}
            </pre>
          )}
          {data?.ocr_pages.some((pg) => pg.confidence !== null) && (
            <p className="mt-2 text-xs text-muted-foreground">Reading confidence: {data.ocr_pages.map((pg) => `${Math.round((pg.confidence ?? 0) * 100)}%`).join(', ')}</p>
          )}
        </Section>

        <Section icon={<ShieldAlert className="size-4" />} title="Safety checks" description="What is missing, unclear or needs your pharmacist. Nothing here changes your prescription.">
          {ins.isPending ? <Loader2 className="size-5 animate-spin text-primary" /> : (
            <ul className="space-y-2 text-sm">
              {(data?.safety ?? []).filter((w) => w.level !== 'info').map((w, i) => (
                <li key={i} className={cn('flex gap-2 rounded-lg p-2.5', w.level === 'danger' ? 'bg-destructive/10 text-destructive' : 'bg-warning/15')}>
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {w.message}
                </li>
              ))}
              {data && !data.safety.some((w) => w.level !== 'info') && (
                <li className="flex gap-2 rounded-lg bg-success/10 p-2.5 text-success"><CheckCircle2 className="mt-0.5 size-4" /> No missing or unclear fields found.</li>
              )}
              {pending > 0 && <li className="flex gap-2 p-1 text-xs text-muted-foreground"><Info className="mt-0.5 size-3.5" /> {pending} medicine line{pending > 1 ? 's' : ''} still need your confirmation below.</li>}
            </ul>
          )}
        </Section>
      </div>

      <Section icon={<Pill className="size-4" />} title="Identified medicines"
        description="Check every line against your paper prescription. Fix anything misread, then confirm. Unclear names are never guessed.">
        <div className="space-y-3">
          {p.medicines.length === 0 && <p className="text-sm text-muted-foreground">No medicine lines were found.</p>}
          {p.medicines.map((m) => <MedicineCard key={m.id} rx={p} med={m} />)}
          <AddMedicine rxId={rxId} />
          {p.medicines.some((m) => m.fields_needing_review.includes('name')) && (
            <p className="text-xs text-muted-foreground">
              Handwriting is hard for any text reader. Correct each name from your paper prescription; AyuMitra never guesses a
              medicine name. Remove lines that are not medicines.
            </p>
          )}
        </div>
      </Section>

      <Section icon={<CalendarClock className="size-4" />} title="Dosage schedule" description="Times written on the prescription are used as written. Where only an abbreviation (BD, TDS) is written, its typical timing is shown and marked for confirmation.">
        {ins.isPending ? <Loader2 className="size-5 animate-spin text-primary" /> : (
          <>
            {data && data.schedule.rows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b text-left text-xs text-muted-foreground"><th className="py-2 pr-4">Time</th><th className="py-2 pr-4">Medicine</th><th className="py-2">Instructions</th></tr></thead>
                  <tbody>
                    {data.schedule.rows.map((r, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-2 pr-4 font-medium">{r.time}</td>
                        <td className="py-2 pr-4">
                          {r.medicine}
                          {r.suggested && <Badge variant="warning" className="ml-2">typical timing</Badge>}
                          {!r.confirmed && <Badge variant="outline" className="ml-2">unconfirmed</Badge>}
                        </td>
                        <td className="py-2 text-muted-foreground">{r.instructions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data?.schedule.rows.some((r) => r.suggested) && (
              <p className="mt-3 flex gap-2 rounded-lg bg-warning/15 p-2.5 text-xs">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                Rows marked "typical timing" are the usual meaning of abbreviations like BD (morning and night) or TDS
                (morning, afternoon, night). Your doctor did not write these times: confirm them with your doctor or pharmacist
                before following them.
              </p>
            )}
            {data && data.schedule.unscheduled.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-sm">
                {data.schedule.unscheduled.map((u, i) => (
                  <li key={i} className="flex gap-2"><Info className="mt-0.5 size-4 shrink-0 text-primary" /><span><b>{u.medicine}</b>: {u.note}{u.instructions && ` · ${u.instructions}`}</span></li>
                ))}
              </ul>
            )}
          </>
        )}
      </Section>

      <Section icon={<BookOpenCheck className="size-4" />} title="Medicine information" description="From official FDA drug labels, only for medicines identified exactly or confirmed by you. Dosing is never taken from here.">
        {ins.isPending ? <Loader2 className="size-5 animate-spin text-primary" /> : (
          <div className="space-y-3">
            {data?.medicine_info_error && <Alert variant="destructive"><AlertTriangle />{data.medicine_info_error}</Alert>}
            <div className="grid gap-3 md:grid-cols-2">
              {data?.medicine_info.filter((i) => !i.not_found).map((i) => <InfoCard key={i.query} info={i} />)}
            </div>
            {data?.medicine_info.filter((i) => i.not_found).map((i) => (
              <p key={i.query} className="text-sm text-muted-foreground">"{i.query}": no FDA label found (common for Indian brand names). Ask your pharmacist for the generic name.</p>
            ))}
            {data && data.unidentified.length > 0 && (
              <p className="text-sm text-muted-foreground">Not looked up until identified or confirmed: {data.unidentified.join(', ')}.</p>
            )}
            {data && data.medicine_info.length === 0 && data.unidentified.length === 0 && !data.medicine_info_error && (
              <p className="text-sm text-muted-foreground">No medicines to look up yet.</p>
            )}
          </div>
        )}
      </Section>

      <Section icon={<CheckCircle2 className="size-4" />} title="Confirmed prescription summary" className={cn(p.user_verified && 'border-success/50')}>
        {p.user_verified ? (
          <div className="space-y-2 text-sm">
            <Badge variant="success"><CheckCircle2 className="size-3" /> Confirmed by you{p.verified_at ? ` on ${formatDate(p.verified_at)}` : ''}</Badge>
            <ul className="list-disc space-y-1 pl-5">
              {p.medicines.map((m) => (
                <li key={m.id}><b>{m.generic_name || m.name_as_written}</b> {[m.strength, m.dose, m.frequency, m.timing, m.duration && `for ${m.duration}`].filter(Boolean).join(' · ')}</li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => verify.mutate()} disabled={verify.isPending || pending > 0 || p.medicines.length === 0}>
              <CheckCircle2 /> Finalize prescription
            </Button>
            <span className="text-sm text-muted-foreground">{pending > 0 ? `Confirm all ${pending} remaining line${pending > 1 ? 's' : ''} first.` : 'All lines confirmed.'}</span>
            {verify.isError && <Alert variant="destructive"><AlertTriangle />{apiErrorMessage(verify.error)}</Alert>}
          </div>
        )}
      </Section>

      {data && <p className="flex gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground"><Info className="mt-0.5 size-3.5 shrink-0" /> {data.disclaimer}</p>}
    </div>
  )
}

function History({ active, onOpen }: { active: number | null; onOpen: (id: number | null) => void }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['prescriptions'], queryFn: prescriptionsApi.list })
  const del = useMutation({
    mutationFn: (docId: string) => documentsApi.remove(docId),
    onSuccess: () => { onOpen(null); qc.invalidateQueries({ queryKey: ['prescriptions'] }) },
  })
  if (!list.data?.results.length) return null
  return (
    <Section icon={<FileText className="size-4" />} title="Prescription history" description="Your previous prescriptions. Deleting removes the record and the uploaded file.">
      <ul className="divide-y">
        {list.data.results.map((p) => (
          <li key={p.id} className="flex items-center gap-3 py-2 text-sm">
            <button type="button" onClick={() => onOpen(p.id)} className={cn('flex-1 cursor-pointer text-left hover:text-primary', active === p.id && 'font-medium text-primary')}>
              {p.prescriber_name || 'Prescription'} · {p.medicines.length} medicine{p.medicines.length === 1 ? '' : 's'} · {formatDate(p.created_at)}
            </button>
            {p.user_verified ? <Badge variant="success">confirmed</Badge> : <Badge variant="warning">needs check</Badge>}
            <button type="button" aria-label="Delete prescription" disabled={del.isPending}
              onClick={() => { if (window.confirm('Delete this prescription and its uploaded file?')) del.mutate(p.document_id) }}
              className="cursor-pointer p-1 text-muted-foreground hover:text-destructive"><Trash2 className="size-4" /></button>
          </li>
        ))}
      </ul>
    </Section>
  )
}

export default function PrescriptionAnalyzer() {
  const [active, setActive] = useState<number | null>(null)
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Prescription Analyzer</h2>
        <p className="text-sm text-muted-foreground">Read a prescription, check each medicine, see a schedule built from what is written, and learn about each medicine.</p>
      </div>
      <UploadCard onReady={setActive} />
      {active !== null && <Results key={active} rxId={active} />}
      <History active={active} onOpen={setActive} />
    </div>
  )
}
