import { useQuery } from '@tanstack/react-query'
import { Ban, CheckCircle2, Coffee, Lightbulb, Moon, Sandwich, Sun, UtensilsCrossed } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  BasisPanel,
  Disclaimer,
  DoctorBadge,
  DoctorNote,
  ErrorState,
  LoadingState,
  PageHeader,
  Section,
  Sources,
} from '@/components/recommendations/shared'
import { recommendationsApi, type DietItem, type Recommendations } from '@/services/api'

const SLOTS = [
  { key: 'breakfast', label: 'Breakfast', Icon: Sun },
  { key: 'lunch', label: 'Lunch', Icon: UtensilsCrossed },
  { key: 'snacks', label: 'Snacks', Icon: Coffee },
  { key: 'dinner', label: 'Dinner', Icon: Moon },
] as const

function DietCard({ item }: { item: DietItem }) {
  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{item.title}</CardTitle>
          {item.needs_doctor && <DoctorBadge />}
        </div>
        <p className="text-sm text-muted-foreground">{item.summary}</p>
        {item.why && <p className="text-xs font-medium text-primary">{item.why}</p>}
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {(item.include.length > 0 || item.limit.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            {item.include.length > 0 && (
              <div>
                <p className="mb-2 flex items-center gap-1.5 font-medium text-success">
                  <CheckCircle2 className="size-4" /> Foods to include
                </p>
                <ul className="space-y-2">
                  {item.include.map((f) => (
                    <li key={f.name}>
                      <p>{f.name}</p>
                      <p className="text-xs text-muted-foreground">{f.note}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {item.limit.length > 0 && (
              <div>
                <p className="mb-2 flex items-center gap-1.5 font-medium text-destructive">
                  <Ban className="size-4" /> Foods to limit
                </p>
                <ul className="list-disc space-y-1.5 pl-5">
                  {item.limit.map((l) => <li key={l}>{l}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
        {item.tips.length > 0 && (
          <ul className="space-y-1">
            {item.tips.map((t) => (
              <li key={t} className="flex gap-2"><Lightbulb className="mt-0.5 size-3.5 shrink-0 text-primary" /> {t}</li>
            ))}
          </ul>
        )}
        {item.removed_for_you.length > 0 && (
          <p className="text-xs text-muted-foreground">Left out for your allergies or diet: {item.removed_for_you.join('; ')}.</p>
        )}
        <DoctorNote text={item.doctor_note} strong={item.needs_doctor} />
        <Sources sources={item.sources} />
      </CardContent>
    </Card>
  )
}

function MealPlan({ plan }: { plan: Recommendations['diet']['meal_plan'] }) {
  if (!plan.available) {
    return <p className="rounded-lg bg-warning/15 p-3 text-sm">{plan.message}</p>
  }
  return (
    <>
      <p className="text-sm text-muted-foreground">{plan.message}</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {SLOTS.map(({ key, label, Icon }) => (
          <Card key={key}>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base"><Icon className="size-4 text-primary" /> {label}</CardTitle>
            </CardHeader>
            <CardContent>
              {(plan.slots[key] ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No option fits your allergies and diet; a dietitian can suggest alternatives.</p>
              ) : (
                <ul className="space-y-3 text-sm">
                  {plan.slots[key].map((f, i) => (
                    <li key={f.name}>
                      <p>{i > 0 && <span className="text-xs text-muted-foreground">or </span>}{f.name}</p>
                      <p className="text-xs text-muted-foreground">{f.note}</p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}

export default function Diet() {
  const q = useQuery({ queryKey: ['recommendations'], queryFn: recommendationsApi.get })
  const personal = q.data?.diet.items.filter((i) => i.based_on.length > 0) ?? []
  const general = q.data?.diet.items.filter((i) => i.based_on.length === 0) ?? []

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title="Diet recommendations" description="Educational food guidance based on your latest lab results and health profile." />
      {q.isPending ? (
        <LoadingState label="Preparing your recommendations…" />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : (
        <>
          <BasisPanel data={q.data} />
          {personal.length > 0 && (
            <Section title="Based on your results">
              {personal.map((i) => <DietCard key={i.id} item={i} />)}
            </Section>
          )}
          <Section title="Everyday healthy eating">
            {general.map((i) => <DietCard key={i.id} item={i} />)}
          </Section>
          <Section title="Sample meal ideas">
            <div className="flex items-center gap-2 text-xs text-muted-foreground"><Sandwich className="size-3.5" /> Built from foods suited to your profile.</div>
            <MealPlan plan={q.data.diet.meal_plan} />
          </Section>
          <Disclaimer text={q.data.disclaimer} />
        </>
      )}
    </div>
  )
}
