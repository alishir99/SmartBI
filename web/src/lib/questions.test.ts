/** The questions a clicked number asks. Wrong wording here asks the agent a wrong question. */

import { describe, expect, it } from 'vitest'
import type { Column, Kpi } from '../types'
import { kpiQuestion, pointQuestion } from './questions'

const kpi = (overrides: Partial<Kpi> = {}): Kpi => ({
  key: 'net_sales_sek',
  label: 'Försäljning',
  value: 49_360_103,
  unit: 'SEK',
  delta_pct: 13.1,
  delta_label: 'vs samma period förra året',
  rank_label: null,
  spark: [],
  ...overrides,
})

describe('kpiQuestion', () => {
  it('turns the chip into a clause a question can end on', () => {
    expect(kpiQuestion(kpi())).toContain('jämfört med samma period förra året?')
    expect(kpiQuestion(kpi())).not.toContain('vs ')
  })

  it('names the direction the number actually moved', () => {
    expect(kpiQuestion(kpi())).toContain('Varför ökade försäljningen')
    expect(kpiQuestion(kpi({ delta_pct: -4.2 }))).toContain('Varför minskade försäljningen')
  })

  it('asks in percentage points about a percentage measure', () => {
    // A share moving 29,5 → 30,7 rose 1,2 p.e.; asking "varför ökade andelen 1,2 %" is a
    // different and wrong question.
    const question = kpiQuestion(
      kpi({ key: 'category_share_pct', label: 'Andel av kategori', unit: '%', delta_pct: 1.2 }),
    )
    expect(question).toContain('andelen av kategorin')
    expect(question).toContain('1,2 procentenheter')
    expect(question).not.toContain('1,2 %')
  })

  it('asks about the level when there is no comparison to ask about', () => {
    const question = kpiQuestion(kpi({ delta_pct: null, delta_label: null }))
    expect(question).toContain('Vad ligger bakom försäljningen')
    expect(question).toContain('den här perioden?')
  })

  it('treats a delta that rounds to nothing as no movement', () => {
    expect(kpiQuestion(kpi({ delta_pct: 0.01 }))).toContain('Vad ligger bakom')
  })
})

describe('pointQuestion', () => {
  const MONTH: Column = { key: 'month', type: 'date', label: 'Månad' }
  const PRODUCT: Column = { key: 'product', type: 'text', label: 'Produkt' }

  it('asks what happened, for a point in time', () => {
    expect(pointQuestion(MONTH, '2025-11')).toBe('Vad hände i nov 2025?')
  })

  it('asks about the thing, for a category', () => {
    expect(pointQuestion(PRODUCT, 'Nordström TV N100')).toBe(
      'Berätta mer om Nordström TV N100.',
    )
  })

  it('falls back rather than asking about an em dash', () => {
    expect(pointQuestion(PRODUCT, '')).toBe('Berätta mer om den här perioden.')
  })
})
