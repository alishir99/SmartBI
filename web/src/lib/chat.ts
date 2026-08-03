/** Chat state (Zustand). */

import { create } from 'zustand'
import type { AnswerCard, ChatEvent, ChatHistoryEntry } from '../types'
import { streamChat } from './api'

export type ToolChip = {
  id: string
  tool: string
  args: Record<string, unknown>
  rowCount: number | null
  done: boolean
}

export type ChatTurn = {
  id: string
  question: string
  status: 'streaming' | 'done' | 'error'
  statusMessage: string | null
  chips: ToolChip[]
  /** Narrative streamed token by token; the card's own narrative wins once it lands. */
  streamedText: string
  card: AnswerCard | null
  /** True while `card` is the chart-only preview and the prose is still being written. */
  cardIsPreview: boolean
  error: string | null
}

type ChatState = {
  turns: ChatTurn[]
  pending: boolean
  ask: (question: string) => Promise<void>
  cancel: () => void
  reset: () => void
}

let controller: AbortController | null = null
let seq = 0
const nextId = () => `t${++seq}`

/** Only `ok` narratives are worth feeding back as history. */
function toHistory(turns: ChatTurn[]): ChatHistoryEntry[] {
  const history: ChatHistoryEntry[] = []
  for (const turn of turns) {
    if (turn.status !== 'done' || !turn.card) continue
    history.push({ role: 'user', content: turn.question })
    history.push({ role: 'assistant', content: turn.card.narrative + describeCard(turn.card) })
  }
  return history.slice(-8)
}

/**
 * What the card actually put on screen, appended to the answer the model wrote.
 *
 * Without this a follow-up like "vad betyder den streckade linjen?" is unanswerable: the
 * model never sees the chart, because the server picks it after the prose is written. It
 * would then say it cannot see the chart, which reads as a system that does not know what it
 * just showed you.
 */
function describeCard(card: AnswerCard): string {
  if (!card.chart) return ''
  const parts = [`typ: ${card.chart.type}`]
  if (card.chart.x) parts.push(`x-axel: ${card.chart.x}`)
  if (card.chart.y.length) parts.push(`serier: ${card.chart.y.join(', ')}`)
  if (card.chart.markers.length && card.chart.marker_label) {
    parts.push(`markeringar: ${card.chart.marker_label}`)
  }
  return `\n[Diagrammet på kortet - ${parts.join('; ')}]`
}

export const useChatStore = create<ChatState>((set, get) => ({
  turns: [],
  pending: false,

  ask: async (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || get().pending) return

    const id = nextId()
    const turn: ChatTurn = {
      id,
      question: trimmed,
      status: 'streaming',
      statusMessage: 'Tänker…',
      chips: [],
      streamedText: '',
      card: null,
      cardIsPreview: false,
      error: null,
    }

    const history = toHistory(get().turns)
    set((state) => ({ turns: [...state.turns, turn], pending: true }))

    const patch = (update: (current: ChatTurn) => ChatTurn) =>
      set((state) => ({
        turns: state.turns.map((candidate) => (candidate.id === id ? update(candidate) : candidate)),
      }))

    // Held locally as well as on the module, because `cancel()` nulls the module-level
    // reference synchronously while the fetch rejects a tick later.
    const abort = new AbortController()
    controller = abort

    try {
      await streamChat(trimmed, history, (event: ChatEvent) => handle(event, patch), abort.signal)
      patch((current) =>
        // A preview is not an answer: a stream that ends on one ended early.
        current.card && !current.cardIsPreview
          ? { ...current, status: 'done', statusMessage: null }
          : {
              ...current,
              status: 'error',
              statusMessage: null,
              error: 'Svaret avbröts innan något kort hade skapats.',
            },
      )
    } catch (error) {
      if (abort.signal.aborted) {
        patch((current) => ({ ...current, status: 'done', statusMessage: null }))
      } else {
        patch((current) => ({
          ...current,
          status: 'error',
          statusMessage: null,
          error: error instanceof Error ? error.message : 'Ett oväntat fel inträffade.',
        }))
      }
    } finally {
      // Only clear it if this turn still owns it; a newer turn may already have replaced it.
      if (controller === abort) controller = null
      set({ pending: false })
    }
  },

  cancel: () => {
    controller?.abort()
    controller = null
    set({ pending: false })
  },

  reset: () => {
    controller?.abort()
    controller = null
    set({ turns: [], pending: false })
  },
}))

function handle(event: ChatEvent, patch: (update: (current: ChatTurn) => ChatTurn) => void): void {
  switch (event.type) {
    case 'status':
      patch((current) => ({ ...current, statusMessage: event.message }))
      break

    case 'tool_call':
      patch((current) => ({
        ...current,
        chips: [
          ...current.chips,
          { id: `${current.id}-${current.chips.length}`, tool: event.tool, args: event.args, rowCount: null, done: false },
        ],
      }))
      break

    case 'tool_result':
      patch((current) => {
        const chips = [...current.chips]
        for (let i = chips.length - 1; i >= 0; i -= 1) {
          if (chips[i].tool === event.tool && !chips[i].done) {
            chips[i] = { ...chips[i], done: true, rowCount: event.row_count ?? null }
            break
          }
        }
        return { ...current, chips }
      })
      break

    case 'token':
      patch((current) => ({
        ...current,
        statusMessage: null,
        streamedText: current.streamedText + event.text,
      }))
      break

    // The status line stays: the turn is still working, and the prose is still coming.
    case 'preview':
      patch((current) => ({ ...current, card: event.card, cardIsPreview: true }))
      break

    case 'card':
      patch((current) => ({
        ...current,
        card: event.card,
        cardIsPreview: false,
        statusMessage: null,
      }))
      break

    case 'error':
      patch((current) => ({ ...current, status: 'error', statusMessage: null, error: event.message }))
      break
  }
}
