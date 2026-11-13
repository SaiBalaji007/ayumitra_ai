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

/** Turn a DRF error response into one readable message. */
export function apiErrorMessage(err: unknown, fallback = 'Something went wrong. Please try again.') {
  if (!axios.isAxiosError(err)) return fallback
  if (!err.response) return 'Cannot reach the server. Check that the backend is running.'
  const data = err.response.data as Record<string, unknown> | undefined
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') return data.detail
    const first = Object.entries(data)[0]
    if (first) {
      const [field, value] = first
      const msg = Array.isArray(value) ? String(value[0]) : String(value)
      return field === 'non_field_errors' ? msg : `${field.replace(/_/g, ' ')}: ${msg}`
    }
  }
  return fallback
}

// ---------- Endpoints ----------

export type HealthResponse = { status: string; service: string; database: string }
export type User = { id: number; email: string; first_name: string; last_name: string }
export type RegisterPayload = { email: string; password: string; first_name: string; last_name: string }

export const getHealth = () => api.get<HealthResponse>('/health/').then((r) => r.data)

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access: string; refresh: string }>('/auth/token/', { email, password }).then((r) => r.data),
  register: (payload: RegisterPayload) => api.post<User>('/auth/register/', payload).then((r) => r.data),
  me: () => api.get<User>('/auth/me/').then((r) => r.data),
}
