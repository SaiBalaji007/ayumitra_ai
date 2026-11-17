import { useQuery } from '@tanstack/react-query'
import { Brain, Droplets, Footprints, Lightbulb, Moon, Sparkles, type LucideIcon } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  BasisPanel,
  Disclaimer,
  DoctorBadge,
  DoctorNote,
  ErrorState,
  LoadingState,
  PageHeader,
  Sources,
} from '@/components/recommendations/shared'
import { recommendationsApi, type LifestyleItem } from '@/services/api'

const ICONS: Record<string, LucideIcon> = {
  activity: Footprints,
  sleep: Moon,
  hydration: Droplets,
  stress: Brain,
  habits: Sparkles,
}

function LifestyleCard({ item }: { item: LifestyleItem }) {
  const Icon = ICONS[item.id] ?? Sparkles
  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <span className="grid size-8 place-items-center rounded-lg bg-primary/12 text-primary"><Icon className="size-4" /></span>
            {item.title}
          </CardTitle>
          {item.needs_doctor && <DoctorBadge />}
        </div>
        <p className="text-sm">{item.summary}</p>
        {item.why && <p className="text-xs font-medium text-primary">{item.why}</p>}
      </CardHeader>
      <CardContent className="text-sm">
        <ul className="space-y-1.5">
          {item.tips.map((t) => (
            <li key={t} className="flex gap-2"><Lightbulb className="mt-0.5 size-3.5 shrink-0 text-primary" /> {t}</li>
          ))}
        </ul>
        <DoctorNote text={item.doctor_note} strong={item.needs_doctor} />
        <Sources sources={item.sources} />
      </CardContent>
    </Card>
  )
}

export default function Lifestyle() {
  const q = useQuery({ queryKey: ['recommendations'], queryFn: recommendationsApi.get })
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title="Lifestyle recommendations" description="Activity, sleep, hydration, stress and daily habits, adjusted to your results and profile." />
      {q.isPending ? (
        <LoadingState label="Preparing your recommendations…" />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : (
        <>
          <BasisPanel data={q.data} />
          <div className="grid gap-4 lg:grid-cols-2">
            {q.data.lifestyle.items.map((i) => <LifestyleCard key={i.id} item={i} />)}
          </div>
          <Disclaimer text={q.data.disclaimer} />
        </>
      )}
    </div>
  )
}
