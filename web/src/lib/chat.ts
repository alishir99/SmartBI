/**
 * Chat state (Zustand). A turn holds the streamed progress chips, the streaming
 * narrative, and finally the AnswerCard — the same card type the dashboard renders.
 */

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
    history.push({ role: 'assistant', content: turn.card.narrative })
  }
  return history.slice(-8)
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
      error: null,
    }

    const history = toHistory(get().turns)
    set((state) => ({ turns: [...state.turns, turn], pending: true }))

    const patch = (update: (current: ChatTurn) => ChatTurn) =>
      set((state) => ({
        turns: state.turns.map((candidate) => (candidate.id === id ? update(candidate) : candidate)),
      }))

    controller = new AbortController()

    try {
      await streamChat(trimmed, history, (event: ChatEvent) => handle(event, patch), controller.signal)
      patch((current) =>
        current.card
          ? { ...current, status: 'done', statusMessage: null }
          : {
              ...current,
              status: 'error',
              statusMessage: null,
              error: 'Svaret avbröts innan något kort hade skapats.',
            },
      )
    } catch (error) {
      if (controller?.signal.aborted) {
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
      controller = null
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
            chips[i] = { ...chips[i], done: true, rowCount: event.row_count }
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

    case 'card':
      patch((current) => ({ ...current, card: event.card, statusMessage: null }))
      break

    case 'error':
      patch((current) => ({ ...current, status: 'error', statusMessage: null, error: event.message }))
      break
  }
}
