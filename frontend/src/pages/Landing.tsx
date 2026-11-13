import { motion, type Variants } from 'framer-motion'
import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  CircleAlert,
  FileSearch,
  Layers,
  Lock,
  MessageSquareText,
  Pill,
  Quote,
  Salad,
  ScanText,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' } },
}
const stagger: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.08 } } }

function Section({ id, className, children }: { id?: string; className?: string; children: ReactNode }) {
  return (
    <section id={id} className={cn('scroll-mt-20 px-4 py-20 sm:px-6 sm:py-28', className)}>
      <div className="mx-auto max-w-6xl">{children}</div>
    </section>
  )
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-80px' }}
      className="mx-auto mb-14 max-w-2xl text-center"
    >
      <p className="mb-3 text-sm font-medium text-primary">{eyebrow}</p>
      <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h2>
      <p className="mt-4 text-pretty text-muted-foreground">{body}</p>
    </motion.div>
  )
}

/* ---------------- Hero product preview (illustrative data only) ---------------- */

const SAMPLE_ROWS = [
  { name: 'Fasting glucose', value: '112', unit: 'mg/dL', range: '70 – 100', flag: 'High' },
  { name: 'Hemoglobin', value: '13.8', unit: 'g/dL', range: '12.0 – 15.5', flag: null },
  { name: 'LDL cholesterol', value: '138', unit: 'mg/dL', range: '< 100', flag: 'High' },
  { name: 'TSH', value: '2.1', unit: 'mIU/L', range: '0.4 – 4.0', flag: null },
]

function ProductPreview() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40, rotateX: 8 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      transition={{ duration: 0.8, delay: 0.25, ease: 'easeOut' }}
      style={{ transformPerspective: 1200 }}
      className="relative mx-auto mt-16 max-w-5xl"
    >
      <div className="absolute -inset-x-10 -top-10 -bottom-10 -z-10 rounded-[3rem] bg-gradient-to-b from-primary/20 via-primary/5 to-transparent blur-3xl" />
      <div className="overflow-hidden rounded-2xl border bg-card shadow-2xl shadow-primary/10">
        <div className="flex items-center gap-2 border-b bg-muted/40 px-4 py-3">
          <span className="size-3 rounded-full bg-destructive/60" />
          <span className="size-3 rounded-full bg-warning/70" />
          <span className="size-3 rounded-full bg-success/60" />
          <span className="ml-3 truncate text-xs text-muted-foreground">Report analysis · lipid_and_glucose_panel.pdf</span>
          <Badge variant="outline" className="ml-auto shrink-0">
            Illustrative sample
          </Badge>
        </div>

        <div className="grid gap-0 md:grid-cols-[1.35fr_1fr]">
          <div className="p-5 sm:p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold">Extracted parameters</h3>
              <span className="text-xs text-muted-foreground">4 of 18 shown</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="pb-2 font-medium">Test</th>
                    <th className="pb-2 font-medium">Result</th>
                    <th className="hidden pb-2 font-medium sm:table-cell">Lab range</th>
                    <th className="pb-2 font-medium">Lab flag</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {SAMPLE_ROWS.map((r, i) => (
                    <motion.tr
                      key={r.name}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.7 + i * 0.12 }}
                    >
                      <td className="py-2.5 pr-3 font-medium">{r.name}</td>
                      <td className="py-2.5 pr-3 tabular-nums">
                        {r.value} <span className="text-xs text-muted-foreground">{r.unit}</span>
                      </td>
                      <td className="hidden py-2.5 pr-3 text-muted-foreground tabular-nums sm:table-cell">{r.range}</td>
                      <td className="py-2.5">
                        {r.flag ? <Badge variant="warning">{r.flag}</Badge> : <Badge variant="success">In range</Badge>}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border-t bg-muted/25 p-5 sm:p-6 md:border-t-0 md:border-l">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" /> Grounded explanation
            </div>
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 1.3 }}
              className="text-sm leading-relaxed text-muted-foreground"
            >
              Your fasting glucose is above the laboratory's reference range. A single reading like this is
              commonly followed up with repeat testing such as HbA1c
              <sup className="ml-0.5 font-semibold text-primary">[1]</sup>. Discuss this result with your doctor.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.6 }}
              className="mt-4 rounded-lg border bg-card p-3 text-xs"
            >
              <div className="mb-1 flex items-center gap-1.5 font-medium">
                <Quote className="size-3 text-primary" /> [1] Evidence
              </div>
              <p className="text-muted-foreground">Laboratory test reference · Blood glucose testing</p>
            </motion.div>
            <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="size-3.5 text-success" /> Citation check passed · Safety check passed
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

/* ---------------- Content ---------------- */

const ENGINES = [
  {
    Icon: FileSearch,
    title: 'Medical report intelligence',
    body: 'Reads lab reports from PDFs and scans, extracts every parameter with its unit and the lab’s own reference interval, and explains results with cited evidence.',
    points: ['PyMuPDF + OCR for scanned pages', 'Lab flag kept separate from AI interpretation', 'Report-specific questions'],
  },
  {
    Icon: Pill,
    title: 'Prescription intelligence',
    body: 'Turns printed or handwritten prescriptions into structured medication instructions, normalized to verified generic names.',
    points: ['Field-level confidence scores', 'Unclear handwriting is flagged, never guessed', 'You confirm before anything is saved'],
  },
  {
    Icon: BookOpenCheck,
    title: 'Evidence-based assistant',
    body: 'Answers health questions from a curated medical knowledge base, with every claim checked against its source.',
    points: ['Hybrid dense + keyword retrieval', 'Cross-encoder reranking', 'Inline citations you can open'],
  },
]

const SUPPORTING = [
  { Icon: Activity, title: 'Health timeline', body: 'Compare parameters across reports and see how they change over time.' },
  { Icon: Salad, title: 'Diet & lifestyle education', body: 'General food, activity and lifestyle information linked to your results.' },
  { Icon: Layers, title: 'Medical knowledge graph', body: 'Connected conditions, tests and medicines retrieved when they add context.' },
  { Icon: MessageSquareText, title: 'Conversation history', body: 'Every answer stays attached to the documents and sources it used.' },
]

const PIPELINE = [
  { title: 'Understand', body: 'Classify intent and rewrite the question into focused search queries.' },
  { title: 'Retrieve', body: 'Run dense vector and BM25 search in parallel, then fuse the rankings.' },
  { title: 'Refine', body: 'Filter by topic and source, rerank with a cross-encoder, and compress context.' },
  { title: 'Generate', body: 'Qwen writes a structured answer from the assembled evidence only.' },
  { title: 'Validate', body: 'Each claim is checked against its citation and passed through safety rules.' },
]

const SAFETY = [
  { Icon: Quote, title: 'Every claim is cited', body: 'Answers that can’t be supported by retrieved evidence are withheld or marked as uncertain.' },
  { Icon: CircleAlert, title: 'No guessing on medicines', body: 'Missing doses are never invented, and “no interaction found” is never shown as “safe”.' },
  { Icon: Lock, title: 'Your records stay yours', body: 'Personal documents are isolated per user and never used to answer anyone else.' },
  { Icon: ShieldCheck, title: 'Education, not diagnosis', body: 'AyuMitra explains and informs. Decisions stay with you and your doctor.' },
]

export default function Landing() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden px-4 pt-16 pb-20 sm:px-6 sm:pt-24">
        <div className="bg-grid absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" />
        <motion.div variants={stagger} initial="hidden" animate="show" className="mx-auto max-w-3xl text-center">
          <motion.div variants={fadeUp}>
            <Badge className="mb-6 px-3 py-1">
              <ScanText className="size-3.5" /> AI-powered medical intelligence
            </Badge>
          </motion.div>
          <motion.h1
            variants={fadeUp}
            className="text-4xl font-semibold tracking-tight text-balance sm:text-6xl sm:leading-[1.05]"
          >
            Your health documents.{' '}
            <span className="bg-gradient-to-r from-teal via-primary to-violet bg-clip-text text-transparent">
              Understood intelligently.
            </span>
          </motion.h1>
          <motion.p variants={fadeUp} className="mx-auto mt-6 max-w-2xl text-lg text-pretty text-muted-foreground">
            AyuMitra AI reads your lab reports and prescriptions, retrieves trusted medical knowledge, and explains
            what your results mean, with every claim linked to its source.
          </motion.p>
          <motion.div variants={fadeUp} className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
            <Link to="/register" className={buttonVariants({ size: 'lg' })}>
              Analyze a report <ArrowRight />
            </Link>
            <a href="#how-it-works" className={buttonVariants({ size: 'lg', variant: 'outline' })}>
              See how it works
            </a>
          </motion.div>
        </motion.div>
        <ProductPreview />
      </section>

      {/* Engines */}
      <Section id="features" className="bg-muted/30">
        <SectionHeading
          eyebrow="Three intelligence engines"
          title="Built to read medical documents, not just chat"
          body="Each engine has its own extraction, retrieval and validation pipeline, tuned for the documents it handles."
        />
        <motion.div
          variants={stagger}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: '-80px' }}
          className="grid gap-5 md:grid-cols-3"
        >
          {ENGINES.map(({ Icon, title, body, points }) => (
            <motion.div
              key={title}
              variants={fadeUp}
              className="group rounded-2xl border bg-card p-6 transition-shadow hover:shadow-lg hover:shadow-primary/5"
            >
              <div className="mb-5 grid size-11 place-items-center rounded-xl bg-primary/12 text-primary transition-transform group-hover:scale-110">
                <Icon className="size-5" />
              </div>
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
              <ul className="mt-5 space-y-2 border-t pt-5 text-sm">
                {points.map((p) => (
                  <li key={p} className="flex gap-2">
                    <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
                    {p}
                  </li>
                ))}
              </ul>
            </motion.div>
          ))}
        </motion.div>

        <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {SUPPORTING.map(({ Icon, title, body }) => (
            <div key={title} className="rounded-2xl border bg-card/60 p-5">
              <Icon className="mb-3 size-5 text-primary" />
              <h3 className="font-medium">{title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Pipeline */}
      <Section id="how-it-works">
        <SectionHeading
          eyebrow="How it works"
          title="A retrieval pipeline you can inspect"
          body="Every answer passes through five stages. Nothing reaches the language model without retrieved evidence behind it."
        />
        <ol className="relative grid gap-4 md:grid-cols-5">
          <div className="absolute top-6 right-[10%] left-[10%] hidden h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent md:block" />
          {PIPELINE.map((step, i) => (
            <motion.li
              key={step.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
              className="relative flex gap-4 md:flex-col md:items-center md:text-center"
            >
              <span className="z-10 grid size-12 shrink-0 place-items-center rounded-full border-2 border-primary/30 bg-background text-sm font-semibold text-primary">
                {i + 1}
              </span>
              <div>
                <h3 className="font-semibold">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
              </div>
            </motion.li>
          ))}
        </ol>
      </Section>

      {/* Safety */}
      <Section id="safety" className="bg-muted/30">
        <SectionHeading
          eyebrow="Safety and privacy"
          title="Designed around what a medical AI should not do"
          body="Safety rules are enforced in the pipeline itself, not added as a disclaimer at the end."
        />
        <div className="grid gap-5 sm:grid-cols-2">
          {SAFETY.map(({ Icon, title, body }) => (
            <div key={title} className="flex gap-4 rounded-2xl border bg-card p-6">
              <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-success/12 text-success">
                <Icon className="size-5" />
              </div>
              <div>
                <h3 className="font-semibold">{title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* CTA */}
      <Section>
        <div className="relative overflow-hidden rounded-3xl bg-navy px-6 py-16 text-center text-white sm:px-12">
          <div className="bg-grid-light absolute inset-0 opacity-30" />
          <div className="absolute -top-24 -left-16 size-72 rounded-full bg-teal/40 blur-3xl" />
          <div className="absolute -right-16 -bottom-24 size-72 rounded-full bg-violet/35 blur-3xl" />
          <div className="relative">
            <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
              Start with your most recent report
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-white/75">
              Create an account, upload a PDF or photo, and get a structured, cited explanation.
            </p>
            <Link
              to="/register"
              className={cn(buttonVariants({ size: 'lg', variant: 'secondary' }), 'mt-8 bg-mint text-navy hover:bg-mint/90')}
            >
              Create free account <ArrowRight />
            </Link>
          </div>
        </div>
      </Section>
    </>
  )
}
