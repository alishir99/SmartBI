/**
 * One render per card status.
 *
 * These exist because the review found four defects a single render test each would have
 * caught - a deleted source chip that four documents still promised, a `validation_failed`
 * sentence painted twice, a preview card indistinguishable from a final one, and a chip
 * reading "0 rader" next to a green tick. The whole frontend suite was pure functions, so
 * every one of them passed CI.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnswerCard, Provenance } from '../types'
import { AnswerCardView } from './AnswerCard'

// The chart's rows come from /api/result. Nothing here is about the chart, and a real fetch
// in a unit test is a flake waiting to happen.
vi.mock('../lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/queries')>()),
  useResult: () => ({ data: undefined, isPending: false, isError: false, error: null }),
}))

const PROVENANCE: Provenance = {
  tool: 'query_sales',
  source: 'mv_sales_daily (rollup)',
  scope: 'supplier:abcd',
  currency: 'SEK',
  vat: 'exkl. moms',
  time_range: { from: '2025-07-01', to: '2026-06-30' },
  compare_range: null,
  coverage: { from: '2024-07-01', to: '2026-06-30' },
  filters_applied: {},
  row_count: 12,
  truncated: false,
  executed_at: '2026-08-01T10:00:00Z',
  tool_args: { measures: ['net_sales_sek'] },
}

const CARD: AnswerCard = {
  card_id: null,
  status: 'ok',
  narrative: 'Försäljningen landade på 49 360 103 kronor.',
  insights: [],
  caveats: [],
  chart: {
    type: 'bar', x: 'month', y: ['net_sales_sek'], series: null, sort: null, limit: null,
    title: 'Försäljning per månad', subtitle: null, markers: [], marker_label: null,
  },
  query_id: 'q_1',
  columns: [],
  provenance: PROVENANCE,
  suggestions: [],
}

// Not automatic without `globals: true`, and without it every query sees the previous render
// as well as its own.
afterEach(cleanup)

function show(card: Partial<AnswerCard>, props: Record<string, unknown> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AnswerCardView card={{ ...CARD, ...card }} {...props} />
    </QueryClientProvider>,
  )
}

describe('the answer card', () => {
  it('shows the prose and the source chip on a chat answer', () => {
    show({}, { showSource: true })
    expect(screen.getByText(/49 360 103 kronor/)).toBeDefined()
    // G1: the chip was deleted while four documents still promised it, and nothing failed.
    expect(screen.getByText('Källa')).toBeDefined()
  })

  it('leaves the source off a dashboard tile', () => {
    // The page header already states the period, the supplier and the unit, once, for every
    // tile on it. A source line under each one is the same sentence four times.
    show({})
    expect(screen.queryByText('Källa')).toBeNull()
  })

  it('says where the numbers came from without naming a table', () => {
    // The chip led with `query_sales`, `mv_sales_daily (rollup)` and `supplier:8f2a`. To the
    // person this product is for, that reads as an app handing out database internals.
    const { container } = show({}, { showSource: true })
    for (const internal of ['query_sales', 'mv_sales_daily', 'supplier:', 'rollup']) {
      expect(container.textContent).not.toContain(internal)
    }
  })

  it('states once, not twice, that the text could not be verified', () => {
    show({ status: 'validation_failed' })
    // B3: the server inserted the sentence as a caveat and the card rendered it from the
    // status as well, so it appeared in the amber box and again in grey underneath.
    expect(screen.getAllByText(/kunde inte verifieras/)).toHaveLength(1)
  })

  it('drops the prose when validation failed but keeps the card', () => {
    show({ status: 'validation_failed' })
    expect(screen.queryByText(/49 360 103 kronor/)).toBeNull()
    expect(screen.getByText('Försäljning per månad')).toBeDefined()
  })

  it('marks a preview as preliminary and refuses to pin it', () => {
    show({}, { preview: true })
    expect(screen.getByText(/Preliminärt/)).toBeDefined()
    expect(screen.queryByTitle('Spara i Mina vyer')).toBeNull()
  })

  it('offers to pin a final card', () => {
    show({})
    expect(screen.getByTitle('Spara i Mina vyer')).toBeDefined()
  })

  it('always states the period the answer covers', () => {
    // G3: the same question resolves to different windows on different runs, and the card's
    // own subtitle is the only thing on screen that says which one ran.
    show({})
    // Twice over: the card's subtitle and the source chip, which both name the window.
    expect(screen.getAllByText(/jul 2025–jun 2026/).length).toBeGreaterThan(0)
  })

  it('names the figures a query licensed, once the chip is opened', () => {
    show({
      narrative: 'Andelen var 28,5 %.',
      claims: [{ literal: '28,5 %', query_id: 'q_1' }],
      sources: [
        { query_id: 'q_1', tool: 'query_sales', provenance: PROVENANCE, row_count: 12 },
        { query_id: 'q_2', tool: 'query_market_share', provenance: PROVENANCE, row_count: 6 },
      ],
    }, { showSource: true })
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    const panels = screen.getAllByText('Siffror i texten som kommer härifrån')
    expect(panels).toHaveLength(1)
    expect(within(panels[0].parentElement as HTMLElement).getByText('28,5 %')).toBeDefined()
  })

  it('renders a refusal with its suggestions and no chart', () => {
    show({
      status: 'cannot_answer',
      narrative: 'Marginal finns inte i datan.',
      chart: null,
      query_id: null,
      provenance: null,
      suggestions: ['Visa nettoförsäljning istället'],
    })
    expect(screen.getByText('Det här kan jag svara på')).toBeDefined()
    expect(screen.getByText('Visa nettoförsäljning istället')).toBeDefined()
    expect(screen.queryByRole('group', { name: 'Visningsläge' })).toBeNull()
  })
})
