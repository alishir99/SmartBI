/** What the source chip is allowed to say about how a result was narrowed. */

import { describe, expect, it } from 'vitest'
import { describeFilters } from './format'

describe('describeFilters', () => {
  it('names a filter the user can read', () => {
    expect(describeFilters({ region: 'Stockholms län' })).toBe('Region: Stockholms län')
  })

  it('counts id filters instead of printing the id', () => {
    // "Produkt: 8" is a database key on a supplier's screen: it says nothing about what was
    // filtered and reads as an internal leak.
    expect(describeFilters({ product_ids: [8] })).toBe('1 produkt')
    expect(describeFilters({ brand_ids: [1, 2] })).toBe('2 varumärken')
  })

  it('still says that a filter was applied at all', () => {
    // The numbers ARE narrowed by it, so silence would be worse than a count.
    expect(describeFilters({ region: 'Skåne län', product_ids: [8, 9, 10] })).toBe(
      'Region: Skåne län · 3 produkter',
    )
  })

  it('says nothing when nothing was filtered', () => {
    expect(describeFilters({})).toBe('')
    expect(describeFilters({ region: null, product_ids: [] })).toBe('')
  })
})
