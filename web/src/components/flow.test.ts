
import { describe, expect, it } from 'vitest'
import type { ChatTurn, ToolChip } from '../lib/chat'
import { flowStage } from './ChatPanel'

const turn = (overrides: Partial<ChatTurn> = {}): ChatTurn => ({
  id: 't1',
  question: 'Hur går det för lurar?',
  status: 'streaming',
  statusMessage: 'Tänker…',
  chips: [],
  streamedText: '',
  card: null,
  cardIsPreview: false,
  error: null,
  ...overrides,
})

const chip = (done: boolean): ToolChip => ({
  id: 'c1',
  tool: 'query_sales',
  args: {},
  rowCount: done ? 12 : null,
  done,
})

describe('flowStage', () => {
  it('starts on the model, before any tool has been called', () => {
    expect(flowStage(turn())).toBe(0)
  })

  it('is on the database while a call is in flight', () => {
    expect(flowStage(turn({ chips: [chip(false)] }))).toBe(2)
  })

  it('moves to the return hop once every call has come back', () => {
    expect(flowStage(turn({ chips: [chip(true)] }))).toBe(3)
  })

  it('stays on the database while any one call is still out', () => {
    expect(flowStage(turn({ chips: [chip(true), chip(false)] }))).toBe(2)
  })

  it('reaches the model again as soon as prose starts arriving', () => {
    expect(flowStage(turn({ chips: [chip(true)], streamedText: 'Lurar växer' }))).toBe(4)
  })

  it('completes the whole chain once the turn is no longer streaming', () => {
    // Errors too: the chain stops animating rather than pulsing on a step that will never end.
    expect(flowStage(turn({ status: 'done' }))).toBe(5)
    expect(flowStage(turn({ status: 'error', chips: [chip(false)] }))).toBe(5)
  })
})
