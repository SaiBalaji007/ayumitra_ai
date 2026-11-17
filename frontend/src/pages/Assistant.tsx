import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MessageSquarePlus, Send, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { isAxiosError } from 'axios'
import { useSearchParams } from 'react-router-dom'
import { GroundedAnswer } from '@/components/ai/GroundedAnswer'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { apiErrorMessage, assistantApi, type ChatMessage, type RagAnswer } from '@/services/api'

const SUGGESTIONS = [
  'What does an HbA1c test show?',
  'What does low hemoglobin mean?',
  'Do I have to fast before a cholesterol test?',
  'What does high creatinine indicate?',
]

function toAnswer(m: ChatMessage): RagAnswer {
  return {
    question: '',
    status: (m.status === 'answered' ? 'answered' : 'insufficient_evidence') as RagAnswer['status'],
    answer: m.content,
    citations: m.citations ?? [],
    safety: { flags: [], urgent: false, urgent_message: null, notices: [], disclaimer: '', ...(m.safety ?? {}) },
  }
}

export default function Assistant() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const conversationId = params.get('c') ?? undefined
  const reportId = params.get('report') ? Number(params.get('report')) : undefined
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const conversations = useQuery({ queryKey: ['conversations'], queryFn: assistantApi.conversations })
  const conversation = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => assistantApi.conversation(conversationId!),
    enabled: Boolean(conversationId),
  })

  const ask = useMutation({
    mutationFn: (q: string) => assistantApi.ask(q, { conversation_id: conversationId, report_id: conversationId ? undefined : reportId }),
    onMutate: (q) => setPending(q),
    onSettled: () => setPending(null),
    onSuccess: (data) => {
      setParams({ c: data.conversation_id })
      qc.invalidateQueries({ queryKey: ['conversation', data.conversation_id] })
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (error) => {
      // When the AI service is down the backend still saves the question (and the error reply) in a
      // conversation; open it so the user's question isn't lost.
      const id = isAxiosError(error) ? (error.response?.data as { conversation_id?: string } | undefined)?.conversation_id : undefined
      if (id) {
        setParams({ c: id })
        qc.invalidateQueries({ queryKey: ['conversation', id] })
      }
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => assistantApi.remove(id),
    onSuccess: (_d, id) => {
      if (id === conversationId) setParams({})
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })

  // Braces matter: Chromium's scrollIntoView now returns a Promise, and React would treat a returned
  // value as the effect's cleanup function ("destroy is not a function"), crashing the page.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [conversation.data, pending])

  function submit(e?: FormEvent, text = question) {
    e?.preventDefault()
    const q = text.trim()
    if (q.length < 3 || ask.isPending) return
    setQuestion('')
    ask.mutate(q)
  }

  const messages = conversationId ? (conversation.data?.messages ?? []) : []

  return (
    <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[260px_1fr]">
      <aside className="space-y-2">
        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => setParams({})}>
            <MessageSquarePlus /> New conversation
          </Button>
        </div>
        {/* Small screens: a compact picker instead of the full list. */}
        {conversations.data && conversations.data.results.length > 0 && (
          <select
            aria-label="Previous conversations"
            className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm lg:hidden"
            value={conversationId ?? ''}
            onChange={(e) => setParams(e.target.value ? { c: e.target.value } : {})}
          >
            <option value="">Previous conversations…</option>
            {conversations.data.results.map((c) => <option key={c.id} value={c.id}>{c.title || 'Conversation'}</option>)}
          </select>
        )}
        <div className="hidden lg:block">
          <p className="px-2 pt-2 pb-1 text-xs font-medium text-muted-foreground">History</p>
          {conversations.isPending ? (
            <div className="flex items-center gap-2 px-2 py-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading conversations…
            </div>
          ) : conversations.isError ? (
            <Alert variant="destructive" className="text-xs">{apiErrorMessage(conversations.error, 'Could not load your conversations.')}</Alert>
          ) : conversations.data.results.length === 0 ? (
            <p className="px-2 py-3 text-sm text-muted-foreground">No conversations yet. Your questions and answers will be saved here, visible only to you.</p>
          ) : (
            <ul className="space-y-1">
              {conversations.data.results.map((c) => (
                <li key={c.id} className="group flex items-center">
                  <button
                    type="button"
                    onClick={() => setParams({ c: c.id })}
                    className={cn('flex-1 cursor-pointer truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent', c.id === conversationId && 'bg-accent font-medium')}
                    title={`${c.title || 'Conversation'} · ${formatDateTime(c.updated_at)}`}
                  >
                    {c.title || 'Conversation'}
                  </button>
                  <button type="button" aria-label="Delete conversation" onClick={() => remove.mutate(c.id)} className="cursor-pointer p-1 text-muted-foreground opacity-0 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100">
                    <Trash2 className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <Card className="flex min-h-[70svh] flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-6" aria-live="polite">
          {!conversationId && !pending && (
            <div className="py-10 text-center">
              <h2 className="text-xl font-semibold">Ask about a test or a health topic</h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                Answers come only from trusted medical sources, with every sentence linked to the passage it came from.
                {reportId ? ' This conversation will use the results from your selected report.' : ''}
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => submit(undefined, s)} className="cursor-pointer rounded-full border px-3 py-1.5 text-xs hover:border-primary/50 hover:bg-accent">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {conversationId && conversation.isPending && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin text-primary" /> Loading conversation…
            </div>
          )}
          {conversationId && conversation.isError && (
            <Alert variant="destructive">
              {apiErrorMessage(conversation.error, 'Could not load this conversation.')}{' '}
              <button type="button" className="cursor-pointer underline" onClick={() => setParams({})}>Start a new one</button>
            </Alert>
          )}
          {messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                {m.content}
              </div>
            ) : (
              <div key={m.id} className="max-w-[95%] rounded-2xl rounded-bl-sm border bg-background p-4">
                {m.status === 'error' ? <p className="text-sm text-destructive">{m.content}</p> : <GroundedAnswer answer={toAnswer(m)} idPrefix={`m${m.id}`} />}
                <p className="mt-2 text-[11px] text-muted-foreground">{formatDateTime(m.created_at)}</p>
              </div>
            ),
          )}
          {pending && (
            <>
              <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">{pending}</div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin text-primary" /> Searching trusted sources and checking every claim… this can take a minute.
              </div>
            </>
          )}
          {/* If the backend saved the failed exchange, its error reply is already shown in the thread. */}
          {ask.isError && !(isAxiosError(ask.error) && (ask.error.response?.data as { conversation_id?: string } | undefined)?.conversation_id) && (
            <Alert variant="destructive">{apiErrorMessage(ask.error, 'The assistant could not answer right now.')}</Alert>
          )}
          <div ref={endRef} />
        </div>
        <form onSubmit={submit} className="flex gap-2 border-t p-3">
          <label htmlFor="q" className="sr-only">Your question</label>
          <input
            id="q"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={1000}
            placeholder="Ask a question about a test, a result or a condition…"
            className="h-11 flex-1 rounded-lg border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:outline-none"
          />
          <Button type="submit" size="icon" className="size-11" disabled={ask.isPending || question.trim().length < 3} aria-label="Send">
            {ask.isPending ? <Loader2 className="animate-spin" /> : <Send />}
          </Button>
        </form>
      </Card>
    </div>
  )
}
