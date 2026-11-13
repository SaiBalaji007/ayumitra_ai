import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, FileUp, Loader2, RotateCcw, UploadCloud, X, XCircle } from 'lucide-react'
import { useCallback, useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { apiErrorMessage, DOCUMENT_TYPES, documentsApi, UPLOAD_LIMITS, type DocumentType } from '@/services/api'

type Item = {
  key: string
  file: File
  type: DocumentType
  state: 'uploading' | 'success' | 'error' | 'cancelled'
  progress: number
  error?: string
  controller?: AbortController
}

/** Client-side pre-check for instant feedback. The server is the real gatekeeper. */
function precheck(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!UPLOAD_LIMITS.extensions.includes(ext)) return `Unsupported file type. Use PDF, PNG or JPG.`
  if (file.size === 0) return 'The file is empty.'
  if (file.size > UPLOAD_LIMITS.maxBytes) return `File is larger than ${formatBytes(UPLOAD_LIMITS.maxBytes)}.`
  return null
}

export function UploadPanel() {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [docType, setDocType] = useState<DocumentType>('lab_report')
  const [dragging, setDragging] = useState(false)
  const [items, setItems] = useState<Item[]>([])

  const patch = (key: string, p: Partial<Item>) => setItems((list) => list.map((i) => (i.key === key ? { ...i, ...p } : i)))

  const start = useCallback(
    (file: File, type: DocumentType, key: string = crypto.randomUUID()) => {
      const problem = precheck(file)
      const controller = new AbortController()
      const item: Item = problem
        ? { key, file, type, state: 'error', progress: 0, error: problem }
        : { key, file, type, state: 'uploading', progress: 0, controller }
      setItems((list) => [item, ...list.filter((i) => i.key !== key)])
      if (problem) return

      documentsApi
        .upload(file, { document_type: type, signal: controller.signal, onProgress: (progress) => patch(key, { progress }) })
        .then(() => {
          patch(key, { state: 'success', progress: 100, controller: undefined })
          queryClient.invalidateQueries({ queryKey: ['documents'] })
        })
        .catch((err) => {
          if (controller.signal.aborted) patch(key, { state: 'cancelled', controller: undefined })
          else patch(key, { state: 'error', error: apiErrorMessage(err, 'Upload failed.'), controller: undefined })
        })
    },
    [queryClient],
  )

  const addFiles = (files: FileList | null) => {
    if (!files) return
    Array.from(files).forEach((f) => start(f, docType))
    if (inputRef.current) inputRef.current.value = ''
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }

  const finished = items.filter((i) => i.state !== 'uploading')

  return (
    <Card>
      <CardContent className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-semibold">Upload documents</h2>
            <p className="text-sm text-muted-foreground">PDF, PNG or JPG, up to {formatBytes(UPLOAD_LIMITS.maxBytes)} each.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="doc-type" className="text-xs text-muted-foreground">
              Document type
            </Label>
            <select
              id="doc-type"
              value={docType}
              onChange={(e) => setDocType(e.target.value as DocumentType)}
              className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
            dragging ? 'border-primary bg-accent' : 'border-border hover:border-primary/50 hover:bg-muted/40',
          )}
        >
          <motion.div
            animate={dragging ? { scale: 1.1, y: -4 } : { scale: 1, y: 0 }}
            className="grid size-12 place-items-center rounded-full bg-primary/12 text-primary"
          >
            <UploadCloud className="size-6" />
          </motion.div>
          <div>
            <p className="font-medium">{dragging ? 'Drop to upload' : 'Drag files here or click to browse'}</p>
            <p className="mt-1 text-xs text-muted-foreground">Files are stored privately and only visible to you.</p>
          </div>
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={UPLOAD_LIMITS.accept}
          className="sr-only"
          onChange={(e) => addFiles(e.target.files)}
          aria-label="Choose files to upload"
        />

        {items.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Uploads</span>
              {finished.length > 0 && (
                <button
                  type="button"
                  className="cursor-pointer hover:text-foreground"
                  onClick={() => setItems((l) => l.filter((i) => i.state === 'uploading'))}
                >
                  Clear finished
                </button>
              )}
            </div>
            <ul className="space-y-2" aria-live="polite">
              <AnimatePresence initial={false}>
                {items.map((item) => (
                  <motion.li
                    key={item.key}
                    layout
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, height: 0 }}
                    className="rounded-lg border bg-background p-3"
                  >
                    <div className="flex items-center gap-3">
                      <ItemIcon state={item.state} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{item.file.name}</p>
                        <p
                          className={cn(
                            'text-xs',
                            item.state === 'error' ? 'text-destructive' : 'text-muted-foreground',
                          )}
                        >
                          {item.state === 'uploading' && `${formatBytes(item.file.size)} · ${item.progress}%`}
                          {item.state === 'success' && 'Uploaded securely'}
                          {item.state === 'cancelled' && 'Cancelled'}
                          {item.state === 'error' && item.error}
                        </p>
                      </div>
                      {item.state === 'uploading' && (
                        <Button variant="ghost" size="sm" onClick={() => item.controller?.abort()} aria-label={`Cancel ${item.file.name}`}>
                          <X />
                        </Button>
                      )}
                      {(item.state === 'error' || item.state === 'cancelled') && !precheck(item.file) && (
                        <Button variant="ghost" size="sm" onClick={() => start(item.file, item.type, item.key)} aria-label="Retry">
                          <RotateCcw />
                        </Button>
                      )}
                    </div>
                    {item.state === 'uploading' && (
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={item.progress} aria-valuemin={0} aria-valuemax={100}>
                        <motion.div className="h-full rounded-full bg-primary" animate={{ width: `${item.progress}%` }} transition={{ ease: 'easeOut' }} />
                      </div>
                    )}
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ItemIcon({ state }: { state: Item['state'] }) {
  if (state === 'uploading') return <Loader2 className="size-5 shrink-0 animate-spin text-primary" />
  if (state === 'success') return <CheckCircle2 className="size-5 shrink-0 text-success" />
  if (state === 'error') return <XCircle className="size-5 shrink-0 text-destructive" />
  return <FileUp className="size-5 shrink-0 text-muted-foreground" />
}
