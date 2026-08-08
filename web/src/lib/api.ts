
import type {
  AnswerCard,
  ChatEvent,
  ChatHistoryEntry,
  DashboardResponse,
  LoginResponse,
  MoversResponse,
  ResultResponse,
  SaveCardRequest,
  SharedView,
  ShareResponse,
  User,
} from '../types'
import type { RegionPoint } from './geo'
import { apiUrl } from './env'
import { getToken } from './auth'
import { streamSse } from './sse'
import { DEFAULT_PERIOD } from './periods'
import { currentLanguage, t } from './i18n'

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
  // Sent on every request, not only ones with a `lang` param: several routes return
  // server-written text (card titles, caveats, a 502's detail) and the middleware reads this.
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Accept-Language': currentLanguage(),
  }
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
  if (response.status === 401) return t('error.expired')
  if (response.status === 403) return t('error.forbidden')
  return t('error.generic')
}


export async function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
}

export async function fetchMe(): Promise<User> {
  return request<User>('/api/auth/me')
}

/** Change your own password. 403 when the current one is wrong. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await request<void>('/api/auth/password', {
    method: 'POST',
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

/** Always resolves, whatever the address was: the server answers identically for a known and
 * an unknown account, so a client that branched on the answer would give that away. */
export async function forgotPassword(email: string): Promise<string> {
  const body = await request<{ detail: string }>('/api/auth/password/forgot', {
    method: 'POST',
    body: { email },
  })
  return body.detail
}

/** Redeem a reset link. 400 when it is expired, already used or forged. */
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await request<void>('/api/auth/password/reset', {
    method: 'POST',
    body: { token, new_password: newPassword },
  })
}


export async function fetchDashboard(period = DEFAULT_PERIOD): Promise<DashboardResponse> {
  const query = new URLSearchParams({ period, lang: currentLanguage() })
  return request<DashboardResponse>(`/api/dashboard?${query}`)
}

export async function fetchMovers(period = DEFAULT_PERIOD): Promise<MoversResponse> {
  const query = new URLSearchParams({ period, lang: currentLanguage() })
  return request<MoversResponse>(`/api/movers?${query}`)
}

/** Every region with a centroid, for the map. Empty is a real answer: an ungeocoded warehouse
 * has no map to draw, and the client hides the tab rather than guessing. */
export async function fetchRegions(): Promise<RegionPoint[]> {
  const rows = await request<{ name: string; lat: number; lon: number }[]>('/api/regions')
  return rows.map((row) => ({ region: row.name, lat: row.lat, lon: row.lon }))
}

export async function fetchResult(queryId: string): Promise<ResultResponse> {
  return request<ResultResponse>(`/api/result/${encodeURIComponent(queryId)}?offset=0&limit=1000`)
}


export async function fetchCards(): Promise<AnswerCard[]> {
  return request<AnswerCard[]>('/api/cards')
}

/** Saving persists the spec plus the tool arguments, not a screenshot, so the card re-runs
 * live against fresh data. */
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

/** No Authorization header sent or wanted: the token carries which card and whose scope, both
 * signed, and the reader is a person with no account here. */
export async function fetchShared(token: string): Promise<SharedView> {
  return request<SharedView>(`/api/shared/${encodeURIComponent(token)}`)
}


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


export async function streamChat(
  question: string,
  history: ChatHistoryEntry[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse<ChatEvent>(apiUrl('/api/chat'), {
    token: getToken(),
    // In the body, not only the header: the answer is written inside a streaming generator,
    // a different task from the one that handled the request.
    body: { question, history, lang: currentLanguage() },
    signal,
    onEvent,
  })
}
