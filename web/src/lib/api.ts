/**
 * The single place that talks to the backend. Every call attaches the bearer
 * token from the auth store. When VITE_USE_MOCKS=true the same functions serve
 * fixtures instead — the real fetch path is the default.
 */

import type {
  AnswerCard,
  ChatEvent,
  ChatHistoryEntry,
  DashboardResponse,
  LoginResponse,
  ResultResponse,
  SaveCardRequest,
  ShareResponse,
  User,
} from '../types'
import { apiUrl, USE_MOCKS } from './env'
import { getToken } from './auth'
import * as mocks from './mocks'
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
  if (USE_MOCKS) {
    await tick()
    return mocks.mockLogin(email, password)
  }
  return request<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
}

export async function fetchMe(): Promise<User> {
  if (USE_MOCKS) {
    await tick()
    return mocks.mockMe(getToken() ?? '')
  }
  return request<User>('/api/auth/me')
}

// --- dashboard, results -----------------------------------------------------

export async function fetchDashboard(period = DEFAULT_PERIOD): Promise<DashboardResponse> {
  if (USE_MOCKS) {
    await tick(280)
    return mocks.mockDashboard()
  }
  return request<DashboardResponse>(`/api/dashboard?period=${encodeURIComponent(period)}`)
}

export async function fetchResult(queryId: string): Promise<ResultResponse> {
  if (USE_MOCKS) {
    await tick(180)
    return mocks.mockResult(queryId)
  }
  return request<ResultResponse>(`/api/result/${encodeURIComponent(queryId)}?offset=0&limit=1000`)
}

// --- saved views ------------------------------------------------------------

export async function fetchCards(): Promise<AnswerCard[]> {
  if (USE_MOCKS) {
    await tick(200)
    return mocks.mockListCards()
  }
  return request<AnswerCard[]>('/api/cards')
}

/**
 * Saving persists the spec plus the tool arguments, not a screenshot, so the card
 * re-runs live against fresh data. `source` is only used by the mock layer to
 * echo back a complete card.
 */
export async function saveCard(body: SaveCardRequest, source?: AnswerCard): Promise<AnswerCard> {
  if (USE_MOCKS) {
    await tick(260)
    return mocks.mockSaveCard(body, source)
  }
  return request<AnswerCard>('/api/cards', { method: 'POST', body })
}

export async function deleteCard(cardId: string): Promise<void> {
  if (USE_MOCKS) {
    await tick(160)
    mocks.mockDeleteCard(cardId)
    return
  }
  await request<void>(`/api/cards/${encodeURIComponent(cardId)}`, { method: 'DELETE' })
}

export async function shareCard(
  cardId: string,
  mode: 'snapshot' | 'live',
): Promise<ShareResponse> {
  if (USE_MOCKS) {
    await tick(240)
    return mocks.mockShare(cardId, mode)
  }
  return request<ShareResponse>('/api/share', { method: 'POST', body: { card_id: cardId, mode } })
}

// --- export -----------------------------------------------------------------

/**
 * CSV download. The backend owns the sv-SE dialect (semicolon separated, comma
 * decimal); under mocks we build the same dialect client-side.
 */
export async function downloadCsv(queryId: string, filename: string): Promise<void> {
  let blob: Blob
  if (USE_MOCKS) {
    const result = mocks.mockResult(queryId)
    const header = result.columns.map((column) => column.label).join(';')
    const lines = result.rows.map((row) =>
      result.columns
        .map((column) => {
          const value = row[column.key]
          if (value === null || value === undefined) return ''
          if (typeof value === 'number') return String(value).replace('.', ',')
          return /[;"\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
        })
        .join(';'),
    )
    blob = new Blob([`﻿${[header, ...lines].join('\r\n')}\r\n`], {
      type: 'text/csv;charset=utf-8',
    })
  } else {
    const token = getToken()
    const response = await fetch(apiUrl(`/api/export/${encodeURIComponent(queryId)}.csv`), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
    blob = await response.blob()
  }

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
  if (USE_MOCKS) {
    return mocks.mockChatStream(question, onEvent, signal)
  }
  return streamSse<ChatEvent>(apiUrl('/api/chat'), {
    token: getToken(),
    body: { question, history },
    signal,
    onEvent,
  })
}

const tick = (ms = 120) => new Promise<void>((resolve) => setTimeout(resolve, ms))
