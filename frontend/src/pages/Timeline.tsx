import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowDown, ArrowUp, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis, type DotProps } from 'recharts'
import { Alert } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate } from '@/lib/format'
import { apiErrorMessage, timelineApi, type TimelinePoint } from '@/services/api'

type Datum = TimelinePoint & { t: number }

/** Out-of-range points: warning color AND a triangle shape (identity never by color alone). */
function PointMarker(props: DotProps & { payload?: Datum }) {
  const { cx, cy, payload } = props
  if (cx == null || cy == null || !payload) return null
  const out = payload.range_status === 'above' || payload.range_status === 'below'
  if (!out) return <circle cx={cx} cy={cy} r={4} fill="var(--primary)" stroke="var(--card)" strokeWidth={2} />
  const up = payload.range_status === 'above'
  const d = up ? `M${cx},${cy - 6} L${cx + 6},${cy + 4} L${cx - 6},${cy + 4} Z` : `M${cx},${cy + 6} L${cx + 6},${cy - 4} L${cx - 6},${cy - 4} Z`
  return <path d={d} fill="var(--warning)" stroke="var(--card)" strokeWidth={2} />
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Datum }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium">{formatDate(p.date)}</p>
      <p className="mt-0.5 tabular-nums">{p.value_text} {p.unit}</p>
      <p className="text-muted-foreground">Lab range: {p.reference_range_text || 'not printed'}</p>
      {(p.range_status === 'above' || p.range_status === 'below') && (
        <p className="mt-0.5 flex items-center gap-1 font-medium">
          {p.range_status === 'above' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
          {p.range_status === 'above' ? 'Above' : 'Below'} the lab's range
        </p>
      )}
    </div>
  )
}

export default function Timeline() {
  const params = useQuery({ queryKey: ['timeline'], queryFn: timelineApi.parameters })
  const [selected, setSelected] = useState<string>('')
  const parameter = selected || params.data?.[0]?.parameter || ''
  const series = useQuery({ queryKey: ['timeline', parameter], queryFn: () => timelineApi.series(parameter), enabled: Boolean(parameter) })
  const [unit, setUnit] = useState<string>('')

  const activeUnit = unit && series.data?.units.includes(unit) ? unit : series.data?.units[0] ?? ''
  const data: Datum[] = useMemo(
    () => (series.data?.points ?? []).filter((p) => p.unit === activeUnit && p.value !== null).map((p) => ({ ...p, t: new Date(p.date).getTime() })),
    [series.data, activeUnit],
  )
  // The band is drawn only when every point shares the same printed range; otherwise it would mislead.
  const band = useMemo(() => {
    const keys = new Set(data.map((d) => `${d.reference_low}|${d.reference_high}`))
    if (keys.size !== 1 || !data.length) return null
    return { low: data[0].reference_low, high: data[0].reference_high }
  }, [data])
  const label = params.data?.find((p) => p.parameter === parameter)?.label ?? parameter

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Health timeline</h2>
        <p className="mt-1 text-muted-foreground">How a test result changes across your reports, using the values exactly as printed.</p>
      </div>
      {params.isLoading && <Loader2 className="size-5 animate-spin text-primary" />}
      {params.isError && <Alert variant="destructive">{apiErrorMessage(params.error)}</Alert>}
      {params.data?.length === 0 && (
        <Card><CardContent className="flex flex-col items-center p-10 text-center">
          <Activity className="mb-3 size-6 text-muted-foreground" />
          <p className="font-medium">No results to chart yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Upload lab reports; matching tests from different dates are charted here.</p>
        </CardContent></Card>
      )}

      {Boolean(params.data?.length) && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-muted-foreground" htmlFor="param">Test</label>
            <select id="param" value={parameter} onChange={(e) => { setSelected(e.target.value); setUnit('') }}
              className="h-9 rounded-lg border border-input bg-background px-3 text-sm">
              {params.data!.map((p) => <option key={p.parameter} value={p.parameter}>{p.label} ({p.count})</option>)}
            </select>
            {series.data && series.data.units.length > 1 && (
              <>
                <label className="text-sm text-muted-foreground" htmlFor="unit">Unit</label>
                <select id="unit" value={activeUnit} onChange={(e) => setUnit(e.target.value)} className="h-9 rounded-lg border border-input bg-background px-3 text-sm">
                  {series.data.units.map((u) => <option key={u} value={u}>{u || '(no unit)'}</option>)}
                </select>
              </>
            )}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{label}{activeUnit ? ` (${activeUnit})` : ''}</CardTitle>
              <CardDescription>
                {series.data?.mixed_units ? 'Your reports use different units for this test. They are shown separately, never converted. ' : ''}
                {band ? "Shaded band: your laboratory's printed reference range." : 'No shared reference range to shade.'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {data.length < 2 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">At least two results with this unit are needed to draw a trend.</p>
              ) : (
                <div className="h-72" role="img" aria-label={`${label} over time`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
                      <CartesianGrid stroke="var(--border)" strokeDasharray="0" vertical={false} />
                      {band && (
                        <ReferenceArea y1={band.low ?? undefined} y2={band.high ?? undefined} fill="var(--success)" fillOpacity={0.1} stroke="none" ifOverflow="extendDomain" />
                      )}
                      <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={(t) => formatDate(new Date(t).toISOString())}
                        stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} tickLine={false} axisLine={{ stroke: 'var(--border)' }} padding={{ left: 16, right: 16 }} />
                      <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={48} domain={['auto', 'auto']} />
                      <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--muted-foreground)', strokeDasharray: '3 3' }} />
                      <Line type="monotone" dataKey="value" stroke="var(--primary)" strokeWidth={2} dot={<PointMarker />}
                        activeDot={{ r: 6, fill: 'var(--primary)', stroke: 'var(--card)', strokeWidth: 2 }} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {data.length > 0 && (
                <details className="mt-4 text-sm" open={data.length < 2}>
                  <summary className="cursor-pointer text-xs text-muted-foreground">Table view</summary>
                  <table className="mt-2 w-full text-left">
                    <thead className="text-xs text-muted-foreground"><tr><th className="py-1 font-medium">Date</th><th className="font-medium">Result</th><th className="font-medium">Lab range</th><th className="font-medium">Compared with range</th></tr></thead>
                    <tbody>
                      {data.map((d) => (
                        <tr key={`${d.report_id}-${d.date}`} className="border-t">
                          <td className="py-1.5">{formatDate(d.date)}</td>
                          <td className="tabular-nums">{d.value_text} {d.unit}</td>
                          <td className="text-muted-foreground">{d.reference_range_text || '-'}</td>
                          <td>{d.range_status === 'within' ? 'Within' : d.range_status === 'above' ? 'Above ▲' : d.range_status === 'below' ? 'Below ▼' : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
