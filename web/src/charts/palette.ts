/**
 * Chart colour. Categorical hues are assigned in a fixed order and never cycled —
 * colour follows the entity, not its rank, so filtering a series out never repaints
 * the survivors.
 *
 * The palette is the dataviz reference categorical order with slot 1 swapped for
 * Apple blue. Both modes were run through the palette validator:
 *   light (surface #ffffff): worst adjacent CVD ΔE 9.1, normal-vision ΔE 19.6 — PASS
 *   dark  (surface #1c1c1e): worst adjacent CVD ΔE 8.4, normal-vision ΔE 19.3 — PASS
 * Three light-mode hues sit below 3:1 on white, so the relief rule applies: charts
 * always ship a legend and a table view.
 *
 * The values are CSS custom properties, which SVG fill/stroke resolve natively —
 * that is what makes the dark-mode swap a single CSS change with no JS involved.
 */

export const SERIES_VARS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
  'var(--series-7)',
  'var(--series-8)',
] as const

/** The de-emphasised benchmark series (e.g. the category average). */
export const SERIES_MUTED = 'var(--series-muted)'

export const MAX_SERIES = SERIES_VARS.length

/**
 * Slot for series index `i`. A 9th series is never a generated hue — callers fold
 * the tail into "Övrigt" before reaching here.
 */
export function seriesColor(index: number): string {
  return SERIES_VARS[Math.min(index, MAX_SERIES - 1)]
}

export const CHART_INK = {
  grid: 'var(--grid)',
  axis: 'var(--axis)',
  axisText: 'var(--axis-text)',
  surface: 'var(--surface)',
  textSecondary: 'var(--text-secondary)',
} as const

/** Mark specs, fixed across every chart in the product. */
export const MARK = {
  barMaxSize: 24,
  barRadius: 4,
  lineWidth: 2,
  dotRadius: 4,
  areaOpacity: 0.1,
  /** 2px of surface between touching marks — white does the separating. */
  surfaceGap: 2,
} as const
