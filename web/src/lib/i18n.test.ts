/**
 * The parts of localisation that can be silently wrong.
 *
 * A missing string is obvious the moment anyone looks at the screen. A number formatted with
 * the wrong locale's separators, or an axis labelled with a magnitude it was not divided by,
 * is a wrong figure that looks like a right one - so that is what these cover.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { STRINGS, columnLabel, plural, t, useLanguageStore } from './i18n'
import { formatCell, formatKpiValue, formatMoneyExact, isCurrency, moneyScale } from './format'
import { project } from './geo'
import type { Column } from '../types'

const use = (lang: 'sv' | 'en') => useLanguageStore.setState({ lang })

beforeEach(() => use('sv'))

describe('the string tables', () => {
  it('answer every key in every language', () => {
    // A gap falls back to Swedish, which on an English screen reads as a bug rather than as a
    // translation gap - so the tables have to stay the same shape.
    const reference = Object.keys(STRINGS.sv).sort()
    expect(Object.keys(STRINGS.en).sort()).toEqual(reference)
  })

  it('fills placeholders and leaves unknown ones alone', () => {
    expect(t('source.rows_count', { count: 42 })).toContain('42')
    // A template referring to a name the caller did not pass keeps the placeholder rather than
    // printing "undefined" at a user.
    expect(t('ask.compared_with', {})).toContain('{period}')
  })

  it('pluralises with the language’s own rules', () => {
    use('en')
    expect(plural(1, 'filter.product_ids')).toBe('1 product')
    expect(plural(2, 'filter.product_ids')).toBe('2 products')
    use('sv')
    expect(plural(1, 'filter.product_ids')).toBe('1 produkt')
    expect(plural(2, 'filter.product_ids')).toBe('2 produkter')
  })
})

describe('column labels', () => {
  it('translate by key, whatever label the server sent', () => {
    // The semantic layer is monolingual on purpose; the key is the stable half of it.
    expect(columnLabel('net_sales_sek', 'Nettoförsäljning')).toBe('Nettoförsäljning')
    use('en')
    expect(columnLabel('net_sales_sek', 'Nettoförsäljning')).toBe('Net sales')
    expect(columnLabel('region', 'Region')).toBe('Region')
  })

  it('translate a derived column from its base plus its suffix', () => {
    use('en')
    expect(columnLabel('net_sales_sek_compare', 'x')).toBe('Net sales (comparison)')
    expect(columnLabel('net_sales_sek_ma', 'x')).toBe('Net sales (moving average)')
  })

  it('fall back to the server’s label for a key they do not know', () => {
    expect(columnLabel('something_the_client_never_heard_of', 'Serverns etikett')).toBe(
      'Serverns etikett',
    )
  })
})

describe('money', () => {
  it('is recognised by its ISO code, not by a hardcoded SEK', () => {
    expect(isCurrency('SEK')).toBe(true)
    expect(isCurrency('EUR')).toBe(true)
    expect(isCurrency('JPY')).toBe(true)
    expect(isCurrency('st')).toBe(false)
    expect(isCurrency('%')).toBe(false)
    expect(isCurrency('p.e.')).toBe(false)
    expect(isCurrency(null)).toBe(false)
  })

  it('formats a currency column by its unit rather than by an assumption', () => {
    const column: Column = { key: 'net_sales_sek', type: 'number', label: 'Netto', unit: 'SEK' }
    // The digits are what matter here; where the locale puts the symbol is the locale's call.
    expect(formatCell(1_234_567, column)).toContain('1')
    expect(formatKpiValue(12_400_000, 'SEK')).toContain('mn')
    expect(formatMoneyExact(23_480_500)).toMatch(/23.480.500/)
  })

  it('gives one scale to a whole axis, with the locale’s own magnitude marker', () => {
    // Not per-value compact notation: that would put "900 k" directly below "1,2 mn" on the
    // same axis.
    expect(moneyScale(12_400_000)).toEqual({ divisor: 1_000_000, unit: 'mn kr', decimals: 1 })
    expect(moneyScale(250_000).divisor).toBe(1_000)
    expect(moneyScale(4_000).divisor).toBe(1)
  })
})

describe('numbers read differently per language', () => {
  it('uses each language’s separators', () => {
    const column: Column = { key: 'units', type: 'number', label: 'Antal', unit: 'st' }
    // sv-SE groups with a space; en groups with a comma. Getting this backwards is how
    // "1,234,567" becomes 1.234.
    expect(formatCell(1234567, column).replace(/\s/g, ' ')).toContain('1 234 567')
    use('en')
    expect(formatCell(1234567, column)).toContain('1,234,567')
  })

  it('states a share change in percentage points in either language', () => {
    expect(formatKpiValue(1.2, 'p.e.')).toContain('p.e.')
    use('en')
    expect(formatKpiValue(1.2, 'p.e.')).toContain('pp')
  })
})

describe('the map projection', () => {
  const points = [
    { region: 'North', lat: 65, lon: 21 },
    { region: 'South', lat: 55, lon: 13 },
  ]

  it('fits whatever coordinates it is given inside the viewBox', () => {
    // No hardcoded country: the same code has to frame Sweden, Spain or three warehouses.
    const projection = project(points, 460, 620, 40)
    for (const point of points) {
      expect(projection.x(point)).toBeGreaterThanOrEqual(0)
      expect(projection.x(point)).toBeLessThanOrEqual(460)
      expect(projection.y(point)).toBeGreaterThanOrEqual(0)
      expect(projection.y(point)).toBeLessThanOrEqual(620)
    }
    // North is north: SVG y grows downward while latitude grows up.
    expect(projection.y(points[0])).toBeLessThan(projection.y(points[1]))
  })

  it('survives a single region, where the span is zero', () => {
    // A zero span divides to Infinity and drops every marker in one pixel - or off-canvas.
    const projection = project([points[0]], 460, 620, 40)
    expect(Number.isFinite(projection.x(points[0]))).toBe(true)
    expect(Number.isFinite(projection.y(points[0]))).toBe(true)
  })
})
