/**
 * The chart contract (§8) in test form. The model is allowed to emit a spec and nothing
 * else, so these tests pin down what the *frontend* decides regardless of what it is
 * handed: order, limit, series ranking, colour assignment and axis scale.
 */

import { describe, expect, it } from 'vitest'
import type { ChartSpec, Column, ResultRow } from '../types'
import { prepareChart } from './prepare'

const spec = (overrides: Partial<ChartSpec> = {}): ChartSpec => ({
  type: 'bar',
  x: 'product',
  y: ['net_sales_sek'],
  series: null,
  sort: 'desc',
  limit: null,
  title: 'Test',
  subtitle: null,
  ...overrides,
})

const PRODUCT: Column = { key: 'product', type: 'text', label: 'Produkt' }
const MONTH: Column = { key: 'month', type: 'date', label: 'Månad' }
const NET: Column = { key: 'net_sales_sek', type: 'number', label: 'Nettoförsäljning', unit: 'SEK' }
const REGION: Column = { key: 'region', type: 'text', label: 'Län' }

const rows = (pairs: Array<[string, number]>, key = 'product'): ResultRow[] =>
  pairs.map(([name, value]) => ({ [key]: name, net_sales_sek: value }))

describe('ordering', () => {
  it('sorts categories by the measure, descending', () => {
    const prepared = prepareChart(
      spec(),
      [PRODUCT, NET],
      rows([
        ['B', 10],
        ['A', 30],
        ['C', 20],
      ]),
    )
    expect(prepared.rows.map((row) => row.product)).toEqual(['A', 'C', 'B'])
  })

  it('sorts ascending when the spec says so', () => {
    const prepared = prepareChart(
      spec({ sort: 'asc' }),
      [PRODUCT, NET],
      rows([
        ['B', 10],
        ['A', 30],
      ]),
    )
    expect(prepared.rows.map((row) => row.product)).toEqual(['B', 'A'])
  })

  it('keeps a date axis chronological even when the spec asks for a sort', () => {
    // A time axis sorted by value would scramble the reading order, so the spec loses.
    const prepared = prepareChart(
      spec({ type: 'line', x: 'month', sort: 'desc' }),
      [MONTH, NET],
      rows(
        [
          ['2026-03', 10],
          ['2026-01', 30],
          ['2026-02', 20],
        ],
        'month',
      ),
    )
    expect(prepared.rows.map((row) => row.month)).toEqual(['2026-01', '2026-02', '2026-03'])
  })
})

describe('limit', () => {
  it('truncates a ranked bar chart to the limit', () => {
    const prepared = prepareChart(
      spec({ limit: 2 }),
      [PRODUCT, NET],
      rows([
        ['A', 30],
        ['B', 20],
        ['C', 10],
      ]),
    )
    expect(prepared.rows).toHaveLength(2)
    expect(prepared.folded).toBe(false)
  })

  it('folds the tail into Övrigt for a pie, so the slices still sum to the whole', () => {
    const prepared = prepareChart(
      spec({ type: 'pie', limit: 2 }),
      [PRODUCT, NET],
      rows([
        ['A', 30],
        ['B', 20],
        ['C', 7],
        ['D', 3],
      ]),
    )
    expect(prepared.rows.map((row) => row.product)).toEqual(['A', 'B', 'Övrigt'])
    expect(prepared.rows[2].net_sales_sek).toBe(10)
    expect(prepared.folded).toBe(true)
  })

  it('never truncates a time axis', () => {
    const prepared = prepareChart(
      spec({ type: 'line', x: 'month', limit: 2 }),
      [MONTH, NET],
      rows(
        [
          ['2026-01', 1],
          ['2026-02', 2],
          ['2026-03', 3],
        ],
        'month',
      ),
    )
    expect(prepared.rows).toHaveLength(3)
  })
})

describe('pivot', () => {
  const longRows: ResultRow[] = [
    { month: '2026-01', region: 'Stockholm', net_sales_sek: 100 },
    { month: '2026-01', region: 'Skåne', net_sales_sek: 400 },
    { month: '2026-02', region: 'Stockholm', net_sales_sek: 200 },
    { month: '2026-02', region: 'Skåne', net_sales_sek: 100 },
  ]

  it('turns long rows into one column per series value', () => {
    const prepared = prepareChart(
      spec({ type: 'line', x: 'month', series: 'region' }),
      [MONTH, REGION, NET],
      longRows,
    )
    expect(prepared.rows).toEqual([
      { month: '2026-01', Stockholm: 100, Skåne: 400 },
      { month: '2026-02', Stockholm: 200, Skåne: 100 },
    ])
  })

  it('ranks series by total, not by first appearance', () => {
    // Skåne totals 500 against Stockholm's 300, so it leads the legend and takes slot 1.
    const prepared = prepareChart(
      spec({ type: 'line', x: 'month', series: 'region' }),
      [MONTH, REGION, NET],
      longRows,
    )
    expect(prepared.series.map((descriptor) => descriptor.label)).toEqual(['Skåne', 'Stockholm'])
    expect(prepared.series[0].color).toBe('var(--series-1)')
  })

  it('folds beyond eight series into a muted Övrigt rather than inventing a ninth hue', () => {
    const many: ResultRow[] = Array.from({ length: 10 }, (_, index) => ({
      month: '2026-01',
      region: `R${index}`,
      net_sales_sek: 100 - index,
    }))
    const prepared = prepareChart(
      spec({ type: 'line', x: 'month', series: 'region' }),
      [MONTH, REGION, NET],
      many,
    )
    expect(prepared.series).toHaveLength(9)
    expect(prepared.series[8].label).toBe('Övrigt')
    expect(prepared.series[8].color).toBe('var(--series-muted)')
    // R8 (92) + R9 (91) — the tail is summed, not dropped.
    expect(prepared.rows[0].Övrigt).toBe(183)
    expect(prepared.folded).toBe(true)
  })
})

describe('axis scale', () => {
  it('picks one money scale for the whole chart from its largest value', () => {
    const prepared = prepareChart(
      spec(),
      [PRODUCT, NET],
      rows([
        ['A', 12_400_000],
        ['B', 1_000],
      ]),
    )
    expect(prepared.scale).toEqual({ divisor: 1_000_000, unit: 'Mkr', decimals: 1 })
  })

  it('leaves non-money measures unscaled', () => {
    const units: Column = { key: 'net_sales_sek', type: 'number', label: 'Antal', unit: 'st' }
    const prepared = prepareChart(spec(), [PRODUCT, units], rows([['A', 4200]]))
    expect(prepared.scale).toBeNull()
    expect(prepared.unit).toBe('st')
  })
})
