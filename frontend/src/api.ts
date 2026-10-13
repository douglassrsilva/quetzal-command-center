export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, payload.detail || `Error ${response.status}`)
  return payload as T
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const newIdempotencyKey = (prefix = 'quetzal') => {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${id}`
}

export const postIdempotent = <T>(path: string, body: unknown, key = newIdempotencyKey('create')) =>
  api<T>(path, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) })

export const patchIdempotent = <T>(path: string, body: unknown, key = newIdempotencyKey('transition')) =>
  api<T>(path, { method: 'PATCH', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) })

export const money = (value: unknown, compact = true) => {
  const n = Number(value || 0)
  return new Intl.NumberFormat('es-419', {
    style: 'currency', currency: 'USD', maximumFractionDigits: compact ? 1 : 0,
    notation: compact ? 'compact' : 'standard',
  }).format(n)
}

export const number = (value: unknown, compact = false) => new Intl.NumberFormat('es-419', {
  maximumFractionDigits: 1, notation: compact ? 'compact' : 'standard',
}).format(Number(value || 0))

export const dateTime = (value: unknown) => value
  ? new Intl.DateTimeFormat('es-419', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(String(value)))
  : '—'
