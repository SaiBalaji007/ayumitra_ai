import axios from 'axios'

const IGNORED_KEYS = new Set(['code', 'duplicate_of'])

const STATUS_MESSAGES: Record<number, string> = {
  400: 'Some details are invalid. Please check the form and try again.',
  401: 'Your session has expired. Please sign in again.',
  403: "You don't have permission to do that.",
  404: "The server couldn't find this service (HTTP 404). If you're running AyuMitra locally, restart the Django server so it loads the latest code.",
  405: 'This action is not supported.',
  409: 'This already exists.',
  413: 'The file is too large.',
  429: 'Too many attempts. Please wait a minute and try again.',
}

function humanizeField(field: string) {
  const label = field.replace(/_/g, ' ')
  return label.charAt(0).toUpperCase() + label.slice(1)
}

/** First readable message from a DRF error body: {"detail": ...} or {"field": ["msg", ...], ...}. */
function messageFromBody(data: unknown): string | null {
  if (typeof data === 'string') {
    // Django HTML error pages and proxy errors are never shown raw.
    return data.trim().startsWith('<') || data.length > 300 ? null : data.trim() || null
  }
  if (!data || typeof data !== 'object') return null
  const body = data as Record<string, unknown>
  if (typeof body.detail === 'string') return body.detail

  for (const [field, value] of Object.entries(body)) {
    if (IGNORED_KEYS.has(field)) continue
    const first = Array.isArray(value) ? value[0] : value
    if (first && typeof first === 'object') {
      const nested = messageFromBody(first)
      if (nested) return nested
      continue
    }
    if (first == null || first === '') continue
    const msg = String(first)
    return field === 'non_field_errors' ? msg : `${humanizeField(field)}: ${msg}`
  }
  return null
}

/**
 * Turn any request failure into one message a person can act on.
 * Order: the server's own validation message, then a message for the HTTP status, then the fallback.
 */
export function apiErrorMessage(err: unknown, fallback = 'Something went wrong. Please try again.') {
  if (!axios.isAxiosError(err)) {
    console.error(err) // a bug in our code, not a server response: keep details out of the UI
    return fallback
  }
  if (err.code === 'ECONNABORTED') return 'The request timed out. Please try again.'
  if (!err.response) return 'Cannot reach the server. Check your connection and that the backend is running.'

  const { status, data } = err.response
  const fromBody = messageFromBody(data)
  if (fromBody) return fromBody
  if (STATUS_MESSAGES[status]) return STATUS_MESSAGES[status]
  if (status === 502 || status === 503 || status === 504) {
    return 'The server is unavailable right now. Check that the backend is running, then try again.'
  }
  if (status >= 500) return `The server hit an error (HTTP ${status}). Please try again shortly.`
  return fallback
}
