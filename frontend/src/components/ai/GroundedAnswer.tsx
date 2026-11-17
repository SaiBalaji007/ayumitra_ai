import { AlertTriangle, BookOpenCheck, ExternalLink, Info, ShieldAlert } from 'lucide-react'
import { Fragment } from 'react'
import { cn } from '@/lib/utils'
import type { Citation, RagAnswer } from '@/services/api'

/** One sentence with clickable [n] citation markers that jump to the source list. */
function Cited({ text, idPrefix }: { text: string; idPrefix: string }) {
  const parts = text.split(/(\[\d+\])/g)
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/)
        if (!m) return <Fragment key={i}>{part}</Fragment>
        return (
          <a
            key={i}
            href={`#${idPrefix}-cite-${m[1]}`}
            className="mx-0.5 inline-grid min-w-5 place-items-center rounded bg-primary/12 px-1 align-super text-[10px] font-semibold text-primary no-underline hover:bg-primary/20"
            aria-label={`Source ${m[1]}`}
          >
            {m[1]}
          </a>
        )
      })}
    </>
  )
}

/**
 * Answer text from the AI service: "### Heading" lines start a section, "- " lines are bullets, other
 * lines are paragraphs. Older single-paragraph answers render as one paragraph.
 */
function AnswerText({ text, idPrefix }: { text: string; idPrefix: string }) {
  const blocks: { heading?: string; lines: string[] }[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('### ')) blocks.push({ heading: line.slice(4), lines: [] })
    else (blocks.at(-1) ?? blocks[blocks.push({ lines: [] }) - 1]).lines.push(line)
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => {
        const bullets = b.lines.filter((l) => l.startsWith('- '))
        const paras = b.lines.filter((l) => !l.startsWith('- '))
        return (
          <section key={i}>
            {b.heading && <h4 className="mb-1 text-xs font-semibold tracking-wide text-primary uppercase">{b.heading}</h4>}
            {paras.map((p, j) => (
              <p key={j} className="leading-relaxed"><Cited text={p} idPrefix={idPrefix} /></p>
            ))}
            {bullets.length > 0 && (
              <ul className="list-disc space-y-1 pl-5 leading-relaxed">
                {bullets.map((l, j) => <li key={j}><Cited text={l.slice(2)} idPrefix={idPrefix} /></li>)}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )
}

export function CitationList({ citations, idPrefix }: { citations: Citation[]; idPrefix: string }) {
  if (!citations.length) return null
  return (
    <div className="mt-4 space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <BookOpenCheck className="size-3.5" /> Sources (each claim was checked against these passages)
      </p>
      <ol className="space-y-2">
        {citations.map((c) => (
          <li key={c.id} id={`${idPrefix}-cite-${c.id}`} className="scroll-mt-24 rounded-lg border bg-muted/30 p-3 text-xs">
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium">
                [{c.id}] {c.title}
                {c.section && c.section !== c.title && <span className="font-normal text-muted-foreground"> · {c.section}</span>}
                {c.publisher && <span className="block font-normal text-muted-foreground">{c.publisher}</span>}
                {c.external && (
                  <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                    Fetched from an external trusted source
                  </span>
                )}
              </span>
              {c.url && (
                <a href={c.url} target="_blank" rel="noreferrer noopener" className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline">
                  Open source <ExternalLink className="size-3.5" />
                </a>
              )}
            </div>
            <blockquote className="mt-1.5 border-l-2 border-primary/40 pl-2 text-muted-foreground italic">“{c.quote}”</blockquote>
            {c.published_date && <p className="mt-1 text-[11px] text-muted-foreground">Source updated: {c.published_date}</p>}
          </li>
        ))}
      </ol>
    </div>
  )
}

export function GroundedAnswer({ answer, idPrefix = 'a', compact = false }: { answer: RagAnswer; idPrefix?: string; compact?: boolean }) {
  const { safety } = answer
  return (
    <div className={cn('text-sm', compact && 'text-[13px]')}>
      {safety?.urgent && safety.urgent_message && (
        <div role="alert" className="mb-3 flex gap-2 rounded-lg border border-destructive/40 bg-destructive/8 p-3 font-medium text-destructive">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" /> {safety.urgent_message}
        </div>
      )}
      {answer.status === 'answered' ? (
        <AnswerText text={answer.answer} idPrefix={idPrefix} />
      ) : (
        <p className="flex gap-2 text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0" /> {answer.answer}
        </p>
      )}
      {safety?.notices?.map((n) => (
        <p key={n} className="mt-3 flex gap-2 rounded-lg bg-warning/15 p-2.5 text-xs">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {n}
        </p>
      ))}
      <CitationList citations={answer.citations ?? []} idPrefix={idPrefix} />
      {!compact && safety?.disclaimer && <p className="mt-3 text-[11px] text-muted-foreground">{safety.disclaimer}</p>}
    </div>
  )
}
