
import { describe, expect, it } from 'vitest'
import type { Column } from '../types'
import { formatCell } from './format'

const date = (key: string): Column => ({ key, type: 'date', label: key })

// Every date bucket comes back as its first day, so the value alone can't say whether
// `2025-07-01` is a month or a day - the column key can.

describe('date grain', () => {
  it('reads a month bucket as a month, not as its first day', () => {
    // The trend axis read "2025-07-01" where it meant "juli 2025".
    expect(formatCell('2025-07-01', date('month'))).toBe('juli 2025')
  })

  it('reads a quarter bucket as a quarter', () => {
    expect(formatCell('2025-07-01', date('quarter'))).toBe('K3 2025')
    expect(formatCell('2026-01-01', date('quarter'))).toBe('K1 2026')
  })

  it('reads a week bucket as an ISO week', () => {
    expect(formatCell('2026-04-02', date('week'))).toContain('v.')
  })

  it('reads a day as a day, without the year', () => {
    // The day grain only ever covers a recent window, and the card's own period line already
    // states which - so the axis says "1 juli", not "2025-07-01".
    expect(formatCell('2025-07-01', date('day'))).toBe('1 juli')
  })

  it('treats a comparison column as the same grain as the column it pairs with', () => {
    expect(formatCell('2024-07-01', date('month_compare'))).toBe('juli 2024')
  })

  it('still reads a bare 2026-01 as a month, whatever the column is called', () => {
    expect(formatCell('2026-01', date('nagot_annat'))).toBe('jan. 2026')
  })
})
