/** The single place that talks to the backend. */

import type {
  AnswerCard,
  ChatEvent,
  ChatHistoryEntry,
  DashboardResponse,
  LoginResponse,
  MoversResponse,
  ResultResponse,
  SaveCardRequest,
  ShareResponse,
  User,
} from '../types'
import { apiUrl } from './env'
import { getToken } from './auth'
import { streamSse } from './sse'
import { DEFAULT_PERIOD } from './periods'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(apiUrl(path), {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (response.status === 204) return undefined as T
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  return (await response.json()) as T
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const parsed = (await response.json()) as { detail?: string }
    if (parsed?.detail) return parsed.detail
  } catch {
    /* non-JSON body */
  }
  if (response.status === 401) return 'Sessionen har gått ut. Logga in igen.'
  if (response.status === 403) return 'Du har inte åtkomst till den här datan.'
  if (response.status === 404) return 'Kunde inte hitta datan.'
  return `Något gick fel (HTTP ${response.status}).`
}

// --- auth -------------------------------------------------------------------

export async function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
}

export async function fetchMe(): Promise<User> {
  return request<User>('/api/auth/me')
}

// --- dashboard, results -----------------------------------------------------

export async function fetchDashboard(period = DEFAULT_PERIOD): Promise<DashboardResponse> {
  return request<DashboardResponse>(`/api/dashboard?${new URLSearchParams({ period })}`)
}

export async function fetchMovers(period = DEFAULT_PERIOD): Promise<MoversResponse> {
  return request<MoversResponse>(`/api/movers?${new URLSearchParams({ period })}`)
}

export async function fetchResult(queryId: string): Promise<ResultResponse> {
  return request<ResultResponse>(`/api/result/${encodeURIComponent(queryId)}?offset=0&limit=1000`)
}

// --- saved views ------------------------------------------------------------

export async function fetchCards(): Promise<AnswerCard[]> {
  return request<AnswerCard[]>('/api/cards')
}

/**
 * Saving persists the spec plus the tool arguments, not a screenshot, so the card re-runs live
 * against fresh data.
 */
export async function saveCard(body: SaveCardRequest): Promise<AnswerCard> {
  return request<AnswerCard>('/api/cards', { method: 'POST', body })
}

export async function deleteCard(cardId: string): Promise<void> {
  await request<void>(`/api/cards/${encodeURIComponent(cardId)}`, { method: 'DELETE' })
}

export async function shareCard(
  cardId: string,
  mode: 'snapshot' | 'live',
): Promise<ShareResponse> {
  return request<ShareResponse>('/api/share', { method: 'POST', body: { card_id: cardId, mode } })
}

// --- export -----------------------------------------------------------------

/** CSV download. */
export async function downloadCsv(queryId: string, filename: string): Promise<void> {
  const token = getToken()
  const response = await fetch(apiUrl(`/api/export/${encodeURIComponent(queryId)}.csv`), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  const blob = await response.blob()

  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

// --- chat (SSE) -------------------------------------------------------------

export async function streamChat(
  question: string,
  history: ChatHistoryEntry[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse<ChatEvent>(apiUrl('/api/chat'), {
    token: getToken(),
    body: { question, history },
    signal,
    onEvent,
  })
}
