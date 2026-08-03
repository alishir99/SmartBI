/** Chart colour. */

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
 * Slot for series index `i`. A 9th series is never a generated hue - callers fold the tail into
 * "Övrigt" before reaching here.
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
  /** The comparison period's stroke - read as "context" without needing a legend. */
  compareDash: '5 4',
  /** 2px of surface between touching marks - white does the separating. */
  surfaceGap: 2,
} as const
