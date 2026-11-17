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

// ---------- Reports, prescriptions, assistant, timeline ----------

/** 'matches' / 'differs': a word result ("Negative") compared with a word reference, never interpreted further. */
export type RangeStatus = 'below' | 'within' | 'above' | 'matches' | 'differs' | 'unknown'

export type LabParameter = {
  id: number
  name_as_printed: string
  normalized_name: string
  value_text: string
  value_numeric: string | null
  unit: string
  reference_range_text: string
  reference_low: string | null
  reference_high: string | null
  lab_flag: string
  lab_flag_display: string
  range_status: RangeStatus
  /** 'lab' = compared with the lab's printed range; 'typical' = with a cited typical range (none printed). */
  range_source: 'lab' | 'typical' | ''
  typical_range: TypicalRange | null
  confidence: number | null
  user_verified: boolean
}

export type TypicalRangeOption = {
  sex: 'any' | 'male' | 'female'
  display: string
  publisher: string
  source_title: string
  url: string
  quote: string
  comparable: boolean
  unit: string
}

/** A typical adult range quoted from a public-domain source, used only when the report printed no range. */
export type TypicalRange = { selected: TypicalRangeOption | null; options: TypicalRangeOption[] }

export type Citation = {
  id: string
  title: string
  url: string | null
  section: string
  page?: number | null
  published_date?: string | null
  quote: string
  publisher?: string | null
  /** fetched live from an external trusted source (MedlinePlus, FDA label) rather than the local library */
  external?: boolean
}

export type RagAnswer = {
  question: string
  status: 'answered' | 'insufficient_evidence' | 'refused'
  answer: string
  citations: Citation[]
  safety: { flags: string[]; urgent: boolean; urgent_message: string | null; notices: string[]; disclaimer: string }
}

export type Explanation = {
  parameter: string
  value: string
  unit: string
  reference_range: string
  lab_flag: string
  range_status: RangeStatus
  answer: RagAnswer
}

export type ExtractedReport = {
  id: number
  document_id: string
  document_title: string
  lab_name: string
  report_date: string | null
  parameters: LabParameter[]
  explanations: Explanation[]
  education: { items: Explanation[]; messages: string[]; created_at: string } | null
  abnormal_count: number
  created_at: string
}

export type PrescriptionMedicine = {
  id: number
  line_number: number
  name_as_written: string
  generic_name: string
  rxnorm_cui: string
  strength: string
  dosage_form: string
  dose: string
  frequency: string
  timing: string
  duration: string
  route: string
  food_instructions: string
  field_confidence: {
    suggestions?: { name: string; rxcui: string; kind: string; similarity: number }[]
    match_status?: string
    frequency_reading?: string
    [k: string]: unknown
  }
  overall_confidence: number | null
  fields_needing_review: string[]
  user_confirmed: boolean
}

export type Prescription = {
  id: number
  document_id: string
  prescriber_name: string
  prescribed_date: string | null
  user_verified: boolean
  verified_at: string | null
  medicines: PrescriptionMedicine[]
  created_at: string
  updated_at: string
}

export type ChatMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  status: string
  citations: Citation[]
  safety: Partial<RagAnswer['safety']>
  created_at: string
}

export type Conversation = { id: string; title: string; report_id: number | null; created_at: string; updated_at: string }

export type TimelinePoint = {
  date: string
  report_id: number
  value_text: string
  value: number | null
  unit: string
  reference_range_text: string
  reference_low: number | null
  reference_high: number | null
  lab_flag: string
  range_status: RangeStatus
}

export const reportsApi = {
  list: () => api.get<Paginated<ExtractedReport>>('/reports/').then((r) => r.data),
  get: (id: number) => api.get<ExtractedReport>(`/reports/${id}/`).then((r) => r.data),
  // LLM on CPU can take minutes for several explanations.
  explain: (id: number) =>
    api.post<{ explanations: Explanation[]; messages: string[] }>(`/reports/${id}/explain/`, {}, { timeout: 0 }).then((r) => r.data),
  education: (id: number) =>
    api.post<{ items: Explanation[]; messages: string[] }>(`/reports/${id}/education/`, {}, { timeout: 0 }).then((r) => r.data),
  /** Download the PDF summary (auth header required, so fetch as a blob). */
  exportPdf: async (id: number) => {
    const res = await api.get<Blob>(`/reports/${id}/export/`, { responseType: 'blob', timeout: 120_000 })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `ayumitra-report-${id}.pdf`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  },
  updateParameter: (reportId: number, paramId: number, data: Partial<LabParameter>) =>
    api.patch<LabParameter>(`/reports/${reportId}/parameters/${paramId}/`, data).then((r) => r.data),
}

export const prescriptionsApi = {
  list: () => api.get<Paginated<Prescription>>('/prescriptions/').then((r) => r.data),
  get: (id: number) => api.get<Prescription>(`/prescriptions/${id}/`).then((r) => r.data),
  updateMedicine: (rxId: number, medId: number, data: Partial<PrescriptionMedicine> & { choose_suggestion?: string }) =>
    api.patch<PrescriptionMedicine>(`/prescriptions/${rxId}/medicines/${medId}/`, data).then((r) => r.data),
  verify: (rxId: number) => api.post<Prescription>(`/prescriptions/${rxId}/verify/`).then((r) => r.data),
  addMedicine: (rxId: number, data: Partial<PrescriptionMedicine>) =>
    api.post<PrescriptionMedicine>(`/prescriptions/${rxId}/medicines/`, data).then((r) => r.data),
  removeMedicine: (rxId: number, medId: number) => api.delete(`/prescriptions/${rxId}/medicines/${medId}/`),
  insights: (rxId: number) => api.get<PrescriptionInsights>(`/prescriptions/${rxId}/insights/`, { timeout: 120_000 }).then((r) => r.data),
}

export type MedicineInfo = {
  query: string
  not_found?: boolean
  generic_name?: string
  brand_names?: string[]
  drug_class?: string
  uses?: string
  side_effects?: string
  warnings?: string
  contraindications?: string
  interactions_note?: string
  source_title?: string
  source_url?: string
  retrieved?: string
}
export type PrescriptionInsights = {
  prescription_id: number
  document_id: string
  ocr_pages: { page: number; text: string; confidence: number | null }[]
  schedule: {
    rows: { time: string; medicine: string; instructions: string; line: number; confirmed: boolean; suggested: boolean }[]
    unscheduled: { medicine: string; note: string; instructions: string; line: number }[]
  }
  safety: { level: 'danger' | 'warning' | 'info'; line: number; message: string }[]
  medicine_info: MedicineInfo[]
  medicine_info_error: string
  unidentified: string[]
  disclaimer: string
}

export const assistantApi = {
  ask: (question: string, opts: { conversation_id?: string; report_id?: number } = {}) =>
    api
      .post<{ conversation_id: string; message: ChatMessage; intent?: string }>('/assistant/ask/', { question, ...opts }, { timeout: 0 })
      .then((r) => r.data),
  conversations: () => api.get<Paginated<Conversation>>('/assistant/conversations/').then((r) => r.data),
  conversation: (id: string) =>
    api.get<Conversation & { messages: ChatMessage[] }>(`/assistant/conversations/${id}/`).then((r) => r.data),
  remove: (id: string) => api.delete(`/assistant/conversations/${id}/`),
}

export const timelineApi = {
  parameters: () => api.get<{ parameter: string; label: string; count: number }[]>('/timeline/').then((r) => r.data),
  series: (parameter: string) =>
    api
      .get<{ parameter: string; units: string[]; mixed_units: boolean; points: TimelinePoint[] }>('/timeline/', { params: { parameter } })
      .then((r) => r.data),
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access: string; refresh: string }>('/auth/token/', { email, password }).then((r) => r.data),
  register: (payload: RegisterPayload) => api.post<User>('/auth/register/', payload).then((r) => r.data),
  me: () => api.get<User>('/auth/me/').then((r) => r.data),
  updateMe: (payload: Pick<User, 'first_name' | 'last_name'>) => api.patch<User>('/auth/me/', payload).then((r) => r.data),
  changePassword: (current_password: string, new_password: string) =>
    api.post<{ detail: string }>('/auth/password/', { current_password, new_password }).then((r) => r.data),
  /** Permanently deletes the account and every document, report and conversation it owns. */
  deleteAccount: (password: string) => api.delete('/auth/me/', { data: { password } }),
}

export type PatientProfile = {
  date_of_birth: string | null
  sex: 'female' | 'male' | 'intersex' | 'undisclosed'
  blood_group: string
  height_cm: string | null
  weight_kg: string | null
  allergies: string
  chronic_conditions: string
  current_medications_note: string
  dietary_preference: string
}

export const profileApi = {
  get: () => api.get<PatientProfile>('/patients/me/profile/').then((r) => r.data),
  update: (payload: Partial<PatientProfile>) => api.patch<PatientProfile>('/patients/me/profile/', payload).then((r) => r.data),
}

// ---------- Diet & lifestyle recommendations (curated education; computed from the user's own results) ----------
export type RecSource = { title: string; url: string }
export type RecFood = { name: string; note: string }
export type RecFinding = {
  parameter: string
  label: string
  value_text: string
  unit: string
  reference_range_text: string
  direction: 'high' | 'low'
  critical: boolean
  report_id: number
  report_date: string
  user_verified: boolean
}
export type DietItem = {
  id: string
  title: string
  why: string
  summary: string
  include: RecFood[]
  limit: string[]
  tips: string[]
  removed_for_you: string[]
  needs_doctor: boolean
  doctor_note: string
  sources: RecSource[]
  based_on: string[]
}
export type LifestyleItem = Omit<DietItem, 'include' | 'limit' | 'removed_for_you'>
export type Recommendations = {
  generated_from: {
    reports_used: number
    latest_report_date: string | null
    results_outside_range: number
    dietary_preference: string | null
    allergies_considered: boolean
    allergy_groups_excluded: string[]
    missing_profile_fields: string[]
    unverified_results: string[]
  }
  findings: RecFinding[]
  alerts: string[]
  diet: { items: DietItem[]; meal_plan: { available: boolean; message: string; slots: Record<string, RecFood[]> } }
  lifestyle: { items: LifestyleItem[] }
  disclaimer: string
}

export const recommendationsApi = {
  get: () => api.get<Recommendations>('/recommendations/').then((r) => r.data),
}

// ---------- Nearby care (OpenStreetMap via the backend) ----------
export type CareCategory = 'all' | 'hospital' | 'clinic' | 'pharmacy' | 'doctor'
export type Facility = {
  id: string
  name: string
  category: Exclude<CareCategory, 'all'>
  address: string
  lat: number
  lon: number
  distance_km: number
  phone: string
  website: string
  opening_hours: string
  emergency: boolean
}
export type NearbyResult = {
  place: { name: string; lat: number; lon: number }
  radius_km: number
  category: CareCategory
  count: number
  facilities: Facility[]
  attribution: string
  cached: boolean
}

export const careApi = {
  nearby: (p: { city: string; locality?: string; category: CareCategory; radius: number }) =>
    api.get<NearbyResult>('/care/nearby/', { params: p, timeout: 120_000 }).then((r) => r.data),
}
