/**
 * The sentence a screen reader hears instead of the plot.
 *
 * Recharts emits a bare <svg> with no accessible name, so before this the chart was simply
 * absent from the accessibility tree — not badly described, not there. The DataTable
 * fallback exists and is good, but it sits behind a mouse click on the Diagram/Tabell
 * toggle, which is no help to the person who needs it most.
 *
 * What these tests pin is that the description is built from what was actually *drawn*.
 * Describing the raw rows instead would make it a second, quieter source of truth that can
 * disagree with the picture — the fold into "Övrigt" being the obvious way that happens.
 */

import { describe, expect, it } from 'vitest'
import type { ChartSpec, Column, ResultRow } from '../types'
import { describeChart } from './Chart'
import { prepareChart } from './prepare'

const spec = (overrides: Partial<ChartSpec> = {}): ChartSpec => ({
  type: 'bar',
  x: 'product',
  y: ['net_sales_sek'],
  series: null,
  sort: 'desc',
  limit: null,
  title: 'Försäljning per produkt',
  subtitle: null,
  ...overrides,
})

const PRODUCT: Column = { key: 'product', type: 'text', label: 'Produkt' }
const NET: Column = { key: 'net_sales_sek', type: 'number', label: 'Nettoförsäljning', unit: 'SEK' }

const rows = (pairs: Array<[string, number]>): ResultRow[] =>
  pairs.map(([name, value]) => ({ product: name, net_sales_sek: value }))

const describeOf = (chartSpec: ChartSpec, columns: Column[], data: ResultRow[]): string =>
  describeChart(chartSpec, prepareChart(chartSpec, columns, data))

describe('describeChart', () => {
  it('names the chart type, the title and what is plotted', () => {
    const text = describeOf(spec(), [PRODUCT, NET], rows([['A', 30], ['B', 10]]))

    expect(text).toContain('Stapeldiagram')
    expect(text).toContain('Försäljning per produkt')
    expect(text).toContain('Nettoförsäljning')
    expect(text).toContain('per produkt')
  })

  it('counts the values actually drawn and gets the singular right', () => {
    expect(describeOf(spec(), [PRODUCT, NET], rows([['A', 30], ['B', 10]])))
      .toContain('2 värden')
    expect(describeOf(spec(), [PRODUCT, NET], rows([['A', 30]])))
      .toContain('1 värde')
  })

  it('describes what was drawn, not what was handed in', () => {
    // A limit means the plot shows fewer bars than the caller supplied. A description
    // built from the raw rows would announce a chart nobody can see.
    const text = describeOf(
      spec({ limit: 2 }),
      [PRODUCT, NET],
      rows([['A', 40], ['B', 30], ['C', 20], ['D', 10]]),
    )
    expect(text).toContain('2 värden')
    expect(text).not.toContain('4 värden')
  })

  it('states the fold into Övrigt, because the picture does', () => {
    // Only a limited pie folds — every other chart drops the tail outright, because a pie
    // that does not sum to the whole is a lie and a bar chart missing its tail is not.
    const pie = spec({ type: 'pie', limit: 2 })
    const prepared = prepareChart(pie, [PRODUCT, NET], rows([
      ['A', 40], ['B', 30], ['C', 20], ['D', 10],
    ]))

    // Only meaningful if this fixture actually trips the fold; otherwise the assertion
    // below would pass for the wrong reason.
    expect(prepared.folded).toBe(true)
    expect(describeChart(pie, prepared)).toContain('Övrigt')
  })

  it('points at the toggle that gives the exact numbers', () => {
    // The table replaces the chart rather than sitting under it, so the wording has to
    // name the control. "Table below" would send someone looking for something that is
    // not there.
    expect(describeOf(spec(), [PRODUCT, NET], rows([['A', 1]]))).toContain('Välj Tabell')
  })

  it('describes a pie by its slices, which is where a pie carries meaning', () => {
    const text = describeOf(
      spec({ type: 'pie' }),
      [PRODUCT, NET],
      rows([['A', 30], ['B', 10]]),
    )
    expect(text).toContain('Cirkeldiagram')
    expect(text).toContain('A')
    expect(text).toContain('B')
  })

  it('survives a spec with no title rather than announcing "undefined"', () => {
    expect(describeOf(spec({ title: '' }), [PRODUCT, NET], rows([['A', 1]])))
      .toContain('utan titel')
  })
})
