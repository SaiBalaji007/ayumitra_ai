import { Lock } from 'lucide-react'
import { DocumentList } from '@/components/documents/DocumentList'
import { UploadPanel } from '@/components/documents/UploadPanel'

export default function Documents() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Document workspace</h2>
          <p className="mt-1 text-muted-foreground">Upload lab reports and prescriptions and track their processing.</p>
        </div>
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Lock className="size-3.5" /> Private to your account
        </p>
      </div>
      <UploadPanel />
      <DocumentList />
    </div>
  )
}
