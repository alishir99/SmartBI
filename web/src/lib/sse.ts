/**
 * SSE over `fetch` + `ReadableStream`. Deliberately NOT `EventSource`: EventSource cannot set
 * request headers, so it cannot send `Authorization: Bearer <token>`, and it cannot POST a body.
 */

import { t } from './i18n'

export type SseOptions<TEvent> = {
  token: string | null
  body: unknown
  signal?: AbortSignal
  onEvent: (event: TEvent) => void
}

export class SseHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'SseHttpError'
  }
}

export async function streamSse<TEvent>(url: string, options: SseOptions<TEvent>): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (options.token) headers.Authorization = `Bearer ${options.token}`

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(options.body),
    signal: options.signal,
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const parsed = (await response.json()) as { detail?: string }
      if (parsed?.detail) detail = parsed.detail
    } catch {
      /* non-JSON error body */
    }
    throw new SseHttpError(response.status, detail)
  }
  if (!response.body) throw new SseHttpError(response.status, t('chat.no_stream'))

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = drain(buffer, options.onEvent)
    }
    // A final frame may arrive without its trailing blank line.
    buffer += decoder.decode()
    drain(buffer.endsWith('\n\n') ? buffer : `${buffer}\n\n`, options.onEvent)
  } finally {
    reader.releaseLock()
  }
}

/** Consume every complete frame in the buffer; return the unconsumed remainder. */
function drain<TEvent>(buffer: string, onEvent: (event: TEvent) => void): string {
  let rest = buffer
  for (;;) {
    const boundary = findBoundary(rest)
    if (boundary === null) return rest
    const frame = rest.slice(0, boundary.index)
    rest = rest.slice(boundary.index + boundary.length)
    const parsed = parseFrame<TEvent>(frame)
    if (parsed !== undefined) onEvent(parsed)
  }
}

function findBoundary(buffer: string): { index: number; length: number } | null {
  const lf = buffer.indexOf('\n\n')
  const crlf = buffer.indexOf('\r\n\r\n')
  if (lf === -1 && crlf === -1) return null
  if (crlf !== -1 && (lf === -1 || crlf < lf)) return { index: crlf, length: 4 }
  return { index: lf, length: 2 }
}

function parseFrame<TEvent>(frame: string): TEvent | undefined {
  const data: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    const line = rawLine.trimEnd()
    if (!line || line.startsWith(':')) continue // comment / keep-alive
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (data.length === 0) return undefined
  const payload = data.join('\n')
  if (payload === '[DONE]') return undefined
  try {
    return JSON.parse(payload) as TEvent
  } catch {
    return undefined
  }
}
