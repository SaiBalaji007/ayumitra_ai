import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Check, Download, FileText, Loader2, MessageSquareText, Pencil, Salad, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { GroundedAnswer } from '@/components/ai/GroundedAnswer'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { formatDate } from '@/lib/format'
import { apiErrorMessage, reportsApi, type ExtractedReport, type LabParameter, type RangeStatus } from '@/services/api'

function RangeBadge({ status }: { status: RangeStatus }) {
  if (status === 'above') return <Badge variant="warning"><ArrowUp className="size-3" /> Above range</Badge>
  if (status === 'below') return <Badge variant="warning"><ArrowDown className="size-3" /> Below range</Badge>
  if (status === 'within') return <Badge variant="success">Within range</Badge>
  return <Badge variant="outline">No range printed</Badge>
}

function ReportList() {
  const q = useQuery({ queryKey: ['reports'], queryFn: reportsApi.list })
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Lab reports</h2>
        <p className="mt-1 text-muted-foreground">Results extracted from your uploaded lab reports.</p>
      </div>
      {q.isLoading && <Loader2 className="size-5 animate-spin text-primary" />}
      {q.isError && <Alert variant="destructive">{apiErrorMessage(q.error)}</Alert>}
      {q.data && q.data.results.length === 0 && (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          No reports yet. <Link to="/app/documents" className="text-primary hover:underline">Upload a lab report</Link>; its results appear here after processing.
        </CardContent></Card>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {q.data?.results.map((r) => (
          <Link key={r.id} to={`/app/reports/${r.id}`} className="rounded-xl border bg-card p-5 transition-shadow hover:shadow-md">
            <div className="flex items-start gap-3">
              <FileText className="mt-0.5 size-5 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{r.document_title}</p>
                <p className="text-xs text-muted-foreground">{r.parameters.length} results · {formatDate(r.report_date ?? r.created_at)}</p>
              </div>
              {r.abnormal_count > 0 ? <Badge variant="warning">{r.abnormal_count} outside range</Badge> : <Badge variant="success">All within range</Badge>}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

function ParameterRow({ report, p }: { report: ExtractedReport; p: LabParameter }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({ value_text: p.value_text, unit: p.unit, reference_range_text: p.reference_range_text })
  const save = useMutation({
    mutationFn: (data: Partial<LabParameter>) => reportsApi.updateParameter(report.id, p.id, data),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ['report', report.id] }) },
  })
  const lowConfidence = p.confidence !== null && p.confidence < 0.8 && !p.user_verified

  return (
    <tr className="border-b last:border-0 align-top">
      <td className="py-3 pr-3 font-medium">
        {p.name_as_printed}
        {lowConfidence && <span className="mt-0.5 block text-[11px] font-normal text-warning">Low reading confidence: please check</span>}
      </td>
      <td className="py-3 pr-3 tabular-nums">
        {editing ? (
          <div className="flex gap-1">
            <Input aria-label="Value" className="h-8 w-20" value={form.value_text} onChange={(e) => setForm({ ...form, value_text: e.target.value })} />
            <Input aria-label="Unit" className="h-8 w-20" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
          </div>
        ) : (
          <>{p.value_text} <span className="text-xs text-muted-foreground">{p.unit}</span></>
        )}
      </td>
      <td className="py-3 pr-3 text-muted-foreground tabular-nums">
        {editing ? (
          <Input aria-label="Reference range" className="h-8 w-28" value={form.reference_range_text} onChange={(e) => setForm({ ...form, reference_range_text: e.target.value })} />
        ) : (p.reference_range_text || '-')}
      </td>
      <td className="py-3 pr-3">{p.lab_flag ? <Badge variant="outline">{p.lab_flag_display}</Badge> : <span className="text-xs text-muted-foreground">none</span>}</td>
      <td className="py-3 pr-3"><RangeBadge status={p.range_status} /></td>
      <td className="py-3 text-right whitespace-nowrap">
        {editing ? (
          <>
            <Button size="icon" variant="ghost" className="size-8" aria-label="Save" disabled={save.isPending} onClick={() => save.mutate(form)}><Check /></Button>
            <Button size="icon" variant="ghost" className="size-8" aria-label="Cancel" onClick={() => setEditing(false)}><X /></Button>
          </>
        ) : (
          <>
            {!p.user_verified && (
              <Button size="sm" variant="ghost" onClick={() => save.mutate({ user_verified: true })} disabled={save.isPending}>Confirm</Button>
            )}
            {p.user_verified && <Badge variant="success" className="mr-1">Checked</Badge>}
            <Button size="icon" variant="ghost" className="size-8" aria-label="Correct this value" onClick={() => setEditing(true)}><Pencil /></Button>
          </>
        )}
        {save.isError && <p className="text-[11px] text-destructive">{apiErrorMessage(save.error)}</p>}
      </td>
    </tr>
  )
}

function ReportDetail({ id }: { id: number }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['report', id], queryFn: () => reportsApi.get(id) })
  const explain = useMutation({
    mutationFn: () => reportsApi.explain(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['report', id] }),
  })
  const education = useMutation({
    mutationFn: () => reportsApi.education(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['report', id] }),
  })
  const exportPdf = useMutation({ mutationFn: () => reportsApi.exportPdf(id) })
  if (q.isLoading) return <Loader2 className="size-5 animate-spin text-primary" />
  if (q.isError || !q.data) return <Alert variant="destructive">{apiErrorMessage(q.error, 'Could not load this report.')}</Alert>
  const r = q.data

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/app/reports" className="text-sm text-primary hover:underline">← All reports</Link>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{r.document_title}</h2>
          <p className="text-sm text-muted-foreground">{r.parameters.length} results{r.lab_name ? ` · ${r.lab_name}` : ''}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => exportPdf.mutate()} disabled={exportPdf.isPending}>
            {exportPdf.isPending ? <Loader2 className="animate-spin" /> : <Download />} Export PDF
          </Button>
          <Link to={`/app/assistant?report=${r.id}`} className={buttonVariants({ variant: 'outline' })}>
            <MessageSquareText /> Ask about this report
          </Link>
        </div>
        {exportPdf.isError && <Alert variant="destructive" className="w-full">{apiErrorMessage(exportPdf.error, 'Export failed.')}</Alert>}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Results</CardTitle>
          <CardDescription>
            Values, units and reference ranges exactly as printed. "Lab flag" is what your laboratory marked; "Compared with lab range" is
            AyuMitra's comparison against that printed range. Correct anything that was read wrongly.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="pb-2 font-medium">Test</th><th className="pb-2 font-medium">Result</th>
                <th className="pb-2 font-medium">Lab reference range</th><th className="pb-2 font-medium">Lab flag</th>
                <th className="pb-2 font-medium">Compared with lab range</th><th />
              </tr>
            </thead>
            <tbody>{r.parameters.map((p) => <ParameterRow key={p.id} report={r} p={p} />)}</tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" /> What do the results outside the range mean?</CardTitle>
            <CardDescription>General, evidence-backed explanations from trusted sources. They are not a diagnosis.</CardDescription>
          </div>
          <Button onClick={() => explain.mutate()} disabled={explain.isPending || r.abnormal_count === 0}>
            {explain.isPending && <Loader2 className="animate-spin" />}
            {r.explanations.length ? 'Refresh explanations' : 'Explain results'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {r.abnormal_count === 0 && <p className="text-sm text-muted-foreground">All results are within the ranges printed by your laboratory.</p>}
          {explain.isPending && <p className="text-sm text-muted-foreground">Retrieving evidence and checking each claim. On a CPU this can take a few minutes.</p>}
          {explain.isError && <Alert variant="destructive">{apiErrorMessage(explain.error)}</Alert>}
          {r.explanations.map((e, i) => (
            <div key={i} className="rounded-xl border p-4">
              <p className="mb-2 text-sm font-medium">
                {e.parameter}: {e.value} {e.unit} <span className="font-normal text-muted-foreground">(lab range {e.reference_range || 'not printed'})</span>
              </p>
              <GroundedAnswer answer={e.answer} idPrefix={`e${i}`} compact />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2"><Salad className="size-4 text-primary" /> Diet and lifestyle education</CardTitle>
            <CardDescription>General information from trusted nutrition and lifestyle sources related to these results. Not a personal plan.</CardDescription>
          </div>
          <Button variant="outline" onClick={() => education.mutate()} disabled={education.isPending || r.abnormal_count === 0}>
            {education.isPending && <Loader2 className="animate-spin" />}
            {r.education ? 'Refresh' : 'Show education'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {education.isError && <Alert variant="destructive">{apiErrorMessage(education.error)}</Alert>}
          {r.education?.messages.map((m) => <p key={m} className="text-xs text-muted-foreground">{m}</p>)}
          {r.education?.items.map((e, i) => (
            <div key={i} className="rounded-xl border p-4">
              <p className="mb-2 text-sm font-medium">{e.parameter}</p>
              <GroundedAnswer answer={e.answer} idPrefix={`ed${i}`} compact />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

export default function Reports() {
  const { id } = useParams()
  return id ? <ReportDetail id={Number(id)} /> : <ReportList />
}
