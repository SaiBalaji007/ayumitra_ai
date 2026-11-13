import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

const ACCESS_KEY = 'ayumitra.access'
const REFRESH_KEY = 'ayumitra.refresh'

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

/** Shared Axios client. In dev, Vite proxies /api to Django on :8000. */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api',
  timeout: 30_000,
})

api.interceptors.request.use((config) => {
  const token = tokens.access
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On a 401, try one silent refresh and replay the request. Concurrent 401s share one refresh.
let refreshing: Promise<string> | null = null

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined
    const isAuthCall = original?.url?.startsWith('/auth/token')
    if (error.response?.status !== 401 || !original || original._retry || isAuthCall || !tokens.refresh) {
      return Promise.reject(error)
    }
    original._retry = true
    try {
      refreshing ??= axios
        .post<{ access: string }>(`${api.defaults.baseURL}/auth/token/refresh/`, { refresh: tokens.refresh })
        .then((r) => r.data.access)
        .finally(() => {
          refreshing = null
        })
      const access = await refreshing
      tokens.set(access)
      original.headers.Authorization = `Bearer ${access}`
      return api(original)
    } catch (refreshError) {
      tokens.clear()
      window.dispatchEvent(new Event('ayumitra:logout'))
      return Promise.reject(refreshError)
    }
  },
)

export { apiErrorMessage } from '@/lib/apiError'

// ---------- Endpoints ----------

export type HealthResponse = { status: string; service: string; database: string }
export type User = { id: number; email: string; first_name: string; last_name: string }
export type RegisterPayload = { email: string; password: string; first_name: string; last_name: string }

export const getHealth = () => api.get<HealthResponse>('/health/').then((r) => r.data)

// ---------- Documents ----------

export type DocumentType = 'lab_report' | 'prescription' | 'discharge_summary' | 'imaging_report' | 'other' | 'unknown'
export type DocumentStatus = 'uploaded' | 'queued' | 'processing' | 'completed' | 'failed'

export type MedicalDocument = {
  id: string
  original_filename: string
  title: string
  content_type: string
  file_size: number
  document_type: DocumentType
  document_type_display: string
  status: DocumentStatus
  status_display: string
  page_count: number | null
  document_date: string | null
  error_message: string
  file_url: string
  created_at: string
  updated_at: string
}

export type ProcessingTask = {
  id: string
  task_type: string
  task_type_display: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  status_display: string
  progress: number
  message: string
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export type DocumentStatusResponse = {
  id: string
  status: DocumentStatus
  status_display: string
  error_message: string
  page_count: number | null
  processing_enabled: boolean
  tasks: ProcessingTask[]
  updated_at: string
}

export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] }

export const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: 'lab_report', label: 'Lab report' },
  { value: 'prescription', label: 'Prescription' },
  { value: 'discharge_summary', label: 'Discharge summary' },
  { value: 'imaging_report', label: 'Imaging report' },
  { value: 'other', label: 'Other' },
]

/** Mirrors the backend limits (documents/validators.py, DOCUMENT_MAX_UPLOAD_MB). The server re-validates. */
export const UPLOAD_LIMITS = {
  maxBytes: 20 * 1024 * 1024,
  extensions: ['.pdf', '.png', '.jpg', '.jpeg'],
  accept: 'application/pdf,image/png,image/jpeg,.pdf,.png,.jpg,.jpeg',
}

export const documentsApi = {
  list: (params: { page?: number; document_type?: DocumentType } = {}) =>
    api.get<Paginated<MedicalDocument>>('/documents/', { params }).then((r) => r.data),
  get: (id: string) => api.get<MedicalDocument>(`/documents/${id}/`).then((r) => r.data),
  status: (id: string) => api.get<DocumentStatusResponse>(`/documents/${id}/status/`).then((r) => r.data),
  remove: (id: string) => api.delete(`/documents/${id}/`),
  upload: (
    file: File,
    opts: { document_type?: DocumentType; title?: string; onProgress?: (pct: number) => void; signal?: AbortSignal },
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (opts.document_type) form.append('document_type', opts.document_type)
    if (opts.title) form.append('title', opts.title)
    return api
      .post<MedicalDocument>('/documents/upload/', form, {
        timeout: 0, // large scans on slow connections; the user can cancel instead
        signal: opts.signal,
        onUploadProgress: (e) => {
          if (e.total) opts.onProgress?.(Math.round((e.loaded / e.total) * 100))
        },
      })
      .then((r) => r.data)
  },
  /** Fetch the private file with the auth header and return a temporary object URL. */
  fileUrl: async (id: string) => {
    const res = await api.get<Blob>(`/documents/${id}/file/`, { responseType: 'blob', timeout: 0 })
    return URL.createObjectURL(res.data)
  },
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access: string; refresh: string }>('/auth/token/', { email, password }).then((r) => r.data),
  register: (payload: RegisterPayload) => api.post<User>('/auth/register/', payload).then((r) => r.data),
  me: () => api.get<User>('/auth/me/').then((r) => r.data),
}
