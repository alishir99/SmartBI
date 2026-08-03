/** The KPI sparkline is a shape, so what is tested is that the shape is right. */

import { describe, expect, it } from 'vitest'
import { sparkPoints } from './KpiTile'

const ys = (points: string) => points.split(' ').map((p) => Number(p.split(',')[1]))
const xs = (points: string) => points.split(' ').map((p) => Number(p.split(',')[0]))

describe('sparkPoints', () => {
  it('spreads the points evenly from edge to edge', () => {
    expect(xs(sparkPoints([1, 2, 3, 4, 5]))).toEqual([0, 25, 50, 75, 100])
  })

  it('puts the largest value highest - SVG y grows downward', () => {
    const [low, mid, high] = ys(sparkPoints([1, 5, 9]))
    expect(high).toBeLessThan(mid)
    expect(mid).toBeLessThan(low)
  })

  it('keeps the whole line inside the box', () => {
    for (const y of ys(sparkPoints([0, 1000000, 3, 7]))) {
      expect(y).toBeGreaterThanOrEqual(2)
      expect(y).toBeLessThanOrEqual(22)
    }
  })

  it('draws a flat series on the midline instead of dividing by zero', () => {
    const values = ys(sparkPoints([4, 4, 4]))
    expect(values.every(Number.isFinite)).toBe(true)
    expect(new Set(values).size).toBe(1)
  })
})
