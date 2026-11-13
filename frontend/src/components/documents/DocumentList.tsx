import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ChevronDown, Eye, FileImage, FileText, Info, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatBytes, formatDate, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { apiErrorMessage, DOCUMENT_TYPES, documentsApi, type DocumentType, type MedicalDocument } from '@/services/api'
import { DocumentStatusBadge } from './DocumentStatusBadge'

const ACTIVE = new Set(['queued', 'processing'])

export function DocumentList() {
  const [filter, setFilter] = useState<DocumentType | ''>('')
  const [page, setPage] = useState(1)

  const query = useQuery({
    queryKey: ['documents', { filter, page }],
    queryFn: () => documentsApi.list({ page, document_type: filter || undefined }),
    // Poll only while something is being processed.
    refetchInterval: (q) => (q.state.data?.results.some((d) => ACTIVE.has(d.status)) ? 3000 : false),
    placeholderData: (prev) => prev,
  })

  const data = query.data
  const pages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Your documents</CardTitle>
          <CardDescription>{data ? `${data.count} document${data.count === 1 ? '' : 's'}` : 'Loading…'}</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Filter by type"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value as DocumentType | '')
              setPage(1)
            }}
            className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
          >
            <option value="">All types</option>
            {DOCUMENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <Button variant="outline" size="icon" className="size-9" onClick={() => query.refetch()} aria-label="Refresh">
            <RefreshCw className={cn(query.isFetching && 'animate-spin')} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {query.isError && (
          <Alert variant="destructive">
            <AlertCircle />
            {apiErrorMessage(query.error, 'Could not load your documents.')}
          </Alert>
        )}
        {query.isLoading && (
          <div className="grid place-items-center py-12">
            <Loader2 className="size-5 animate-spin text-primary" aria-label="Loading documents" />
          </div>
        )}
        {data && data.results.length === 0 && (
          <div className="rounded-xl border border-dashed px-6 py-12 text-center">
            <p className="font-medium">{filter ? 'No documents of this type' : 'No documents yet'}</p>
            <p className="mt-1 text-sm text-muted-foreground">Uploaded files will appear here with their processing status.</p>
          </div>
        )}
        {data && data.results.length > 0 && (
          <ul className="divide-y">
            {data.results.map((doc) => (
              <DocumentRow key={doc.id} doc={doc} />
            ))}
          </ul>
        )}
        {pages > 1 && (
          <div className="mt-4 flex items-center justify-end gap-2 text-sm">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="text-muted-foreground">
              Page {page} of {pages}
            </span>
            <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DocumentRow({ doc }: { doc: MedicalDocument }) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [viewError, setViewError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)

  const remove = useMutation({
    mutationFn: () => documentsApi.remove(doc.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })

  async function view() {
    setViewError(null)
    setOpening(true)
    // Open the tab synchronously so pop-up blockers allow it, then point it at the blob.
    const tab = window.open('', '_blank')
    try {
      const url = await documentsApi.fileUrl(doc.id)
      if (tab) tab.location.href = url
      else window.location.assign(url)
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      tab?.close()
      setViewError(apiErrorMessage(err, 'Could not open the file.'))
    } finally {
      setOpening(false)
    }
  }

  const Icon = doc.content_type === 'application/pdf' ? FileText : FileImage

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
        <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={doc.original_filename}>
            {doc.title || doc.original_filename}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {doc.document_type_display} · {formatBytes(doc.file_size)} · {formatDate(doc.created_at)}
          </p>
        </div>
        <DocumentStatusBadge status={doc.status} label={doc.status_display} />
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="size-8" onClick={view} disabled={opening} aria-label={`View ${doc.original_filename}`} title="View file">
            {opening ? <Loader2 className="animate-spin" /> : <Eye />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            aria-label="Processing details"
            title="Processing details"
          >
            <ChevronDown className={cn('transition-transform', expanded && 'rotate-180')} />
          </Button>
          {confirming ? (
            <div className="flex items-center gap-1">
              <Button variant="destructive" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
                {remove.isPending && <Loader2 className="animate-spin" />}
                Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={remove.isPending}>
                Keep
              </Button>
            </div>
          ) : (
            <Button variant="ghost" size="icon" className="size-8 hover:text-destructive" onClick={() => setConfirming(true)} aria-label={`Delete ${doc.original_filename}`} title="Delete">
              <Trash2 />
            </Button>
          )}
        </div>
      </div>
      {confirming && !remove.isError && (
        <p className="mt-2 text-xs text-muted-foreground sm:pl-13">This permanently deletes the file and anything extracted from it.</p>
      )}
      {(remove.isError || viewError) && (
        <p className="mt-2 text-xs text-destructive sm:pl-13">{viewError ?? apiErrorMessage(remove.error, 'Could not delete the document.')}</p>
      )}
      {expanded && <StatusPanel id={doc.id} />}
    </li>
  )
}

function StatusPanel({ id }: { id: string }) {
  const q = useQuery({
    queryKey: ['documents', id, 'status'],
    queryFn: () => documentsApi.status(id),
    refetchInterval: (query) => (query.state.data && ACTIVE.has(query.state.data.status) ? 2000 : false),
  })

  return (
    <div className="mt-3 rounded-lg border bg-muted/30 p-4 text-sm sm:ml-13">
      {q.isLoading && <Loader2 className="size-4 animate-spin text-primary" />}
      {q.isError && <p className="text-destructive">{apiErrorMessage(q.error, 'Could not load status.')}</p>}
      {q.data && (
        <div className="space-y-3">
          {!q.data.processing_enabled && q.data.tasks.length === 0 && (
            <p className="flex gap-2 text-muted-foreground">
              <Info className="mt-0.5 size-4 shrink-0" />
              Stored securely. Text extraction and analysis aren't switched on yet; they arrive with the OCR and medical NLP
              phases. No analysis has been run on this document.
            </p>
          )}
          {q.data.error_message && <p className="text-destructive">{q.data.error_message}</p>}
          {q.data.tasks.length > 0 && (
            <ol className="space-y-2">
              {q.data.tasks.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3">
                  <span>
                    {t.task_type_display}
                    {t.message && <span className="text-muted-foreground"> · {t.message}</span>}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {t.status_display}
                    {t.status === 'running' && ` ${t.progress}%`}
                    {t.finished_at && ` · ${formatDateTime(t.finished_at)}`}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
