/**
 * Turns (ChartSpec + columns + rows) into exactly what Recharts needs.
 *
 * Every decision here is deterministic and lives outside the component, because the
 * model is allowed to choose the *spec* and nothing else: sorting, limiting, series
 * ordering, colour assignment and the axis scale are all computed from the data. Two
 * identical specs over identical rows always draw the identical chart.
 */

import type { ChartSpec, Column, ColumnUnit, ResultRow } from '../types'
import { MAX_SERIES, SERIES_MUTED, seriesColor } from './palette'
import { moneyScale, truncateLabel, type MoneyScale } from '../lib/format'

export type SeriesDescriptor = {
  /** The key to read off each prepared row. */
  key: string
  label: string
  color: string
}

export type PreparedChart = {
  rows: ResultRow[]
  series: SeriesDescriptor[]
  xColumn: Column | null
  /** Unit of the measure axis; drives the axis label and the tick formatter. */
  unit: ColumnUnit | null
  /** Shared money scale so every tick and label on one axis carries one unit. */
  scale: MoneyScale | null
  /** Columns describing the prepared rows — what the tooltip and table view read. */
  columns: Column[]
  /** True when a tail of small categories was folded into "Övrigt". */
  folded: boolean
  /**
   * One descriptor per pie slice, in row order; empty for every other chart type.
   *
   * A pie is the one chart whose colour varies along the *dimension* rather than along
   * the measures. `series` describes the measures, and a pie has exactly one — so
   * colouring slices from it painted every slice `--series-1` and hid the legend behind
   * a "two or more series" rule. Computed here rather than in the component so the wedge
   * and its legend swatch read from one array and cannot drift apart, and so it is
   * testable without rendering.
   */
  slices: SeriesDescriptor[]
}

const OTHER_LABEL = 'Övrigt'

const byKey = (columns: Column[], key: string | null): Column | null =>
  (key ? columns.find((column) => column.key === key) : null) ?? null

const numeric = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : 0

export function prepareChart(
  spec: ChartSpec,
  columns: Column[],
  rows: ResultRow[],
): PreparedChart {
  const xColumn = byKey(columns, spec.x)
  const measures = spec.y.map((key) => byKey(columns, key)).filter((c): c is Column => c !== null)
  const unit = measures[0]?.unit ?? null

  const prepared = spec.series
    ? pivot(spec, columns, rows, xColumn)
    : direct(spec, measures, rows, xColumn)

  const max = maxAbs(prepared.rows, prepared.series)
  return {
    ...prepared,
    xColumn,
    unit,
    scale: unit === 'SEK' ? moneyScale(max) : null,
    slices: spec.type === 'pie' ? sliceDescriptors(prepared.rows, xColumn, prepared.folded) : [],
  }
}

/**
 * Colour and label per slice, following the dimension value. The folded tail keeps the
 * muted slot it has everywhere else — "Övrigt" is a remainder, not a category, and giving
 * it a palette hue makes it read as one.
 */
function sliceDescriptors(
  rows: ResultRow[],
  xColumn: Column | null,
  folded: boolean,
): SeriesDescriptor[] {
  const key = xColumn?.key
  return rows.map((row, index) => {
    const label = key ? String(row[key] ?? '–') : `#${index + 1}`
    return {
      key: label,
      label,
      color: folded && label === OTHER_LABEL ? SERIES_MUTED : seriesColor(index),
    }
  })
}

/** Wide input: every measure in `spec.y` is already its own column. */
function direct(
  spec: ChartSpec,
  measures: Column[],
  rows: ResultRow[],
  xColumn: Column | null,
): Omit<PreparedChart, 'xColumn' | 'unit' | 'scale' | 'slices'> {
  const series = measures.map((column, index) => ({
    key: column.key,
    label: column.label,
    color: seriesColor(index),
  }))

  const ordered = order(rows, spec, xColumn, series[0]?.key ?? null)
  const { rows: limited, folded } = applyLimit(ordered, spec, series, xColumn)

  return {
    rows: limited,
    series,
    columns: [...(xColumn ? [xColumn] : []), ...measures],
    folded,
  }
}

/**
 * Long input: one measure column, one column whose distinct values are the series.
 * Series are ranked by total (not by first appearance) so the legend reads
 * largest-first, and colour follows the entity for the life of the chart.
 */
function pivot(
  spec: ChartSpec,
  columns: Column[],
  rows: ResultRow[],
  xColumn: Column | null,
): Omit<PreparedChart, 'xColumn' | 'unit' | 'scale' | 'slices'> {
  const seriesKey = spec.series as string
  const measureKey = spec.y[0]
  const measure = byKey(columns, measureKey)
  const xKey = spec.x

  const totals = new Map<string, number>()
  for (const row of rows) {
    const name = String(row[seriesKey] ?? '–')
    totals.set(name, (totals.get(name) ?? 0) + numeric(row[measureKey]))
  }

  const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name)
  const kept = ranked.slice(0, MAX_SERIES)
  const folded = ranked.length > MAX_SERIES
  const keptSet = new Set(kept)

  const buckets = new Map<string, ResultRow>()
  const xOrder: string[] = []
  for (const row of rows) {
    const x = xKey ? String(row[xKey] ?? '–') : '–'
    let bucket = buckets.get(x)
    if (!bucket) {
      bucket = xKey ? { [xKey]: row[xKey] ?? null } : {}
      buckets.set(x, bucket)
      xOrder.push(x)
    }
    const name = String(row[seriesKey] ?? '–')
    const target = keptSet.has(name) ? name : OTHER_LABEL
    bucket[target] = numeric(bucket[target]) + numeric(row[measureKey])
  }

  const names = folded ? [...kept, OTHER_LABEL] : kept
  const series = names.map((name, index) => ({
    key: name,
    label: name,
    // "Övrigt" is never a real entity, so it never takes a categorical hue.
    color: name === OTHER_LABEL && folded ? SERIES_MUTED : seriesColor(index),
  }))

  const pivoted = xOrder.map((x) => buckets.get(x) as ResultRow)
  const ordered = order(pivoted, spec, xColumn, series[0]?.key ?? null)

  const unit = measure?.unit ?? null
  return {
    rows: ordered,
    series,
    columns: [
      ...(xColumn ? [xColumn] : []),
      ...names.map((name) => ({ key: name, type: 'number' as const, label: name, unit })),
    ],
    folded,
  }
}

/**
 * A time axis is always chronological — a `sort` on a date x would scramble the
 * reading order, so the spec's sort only applies to categorical axes.
 */
function order(
  rows: ResultRow[],
  spec: ChartSpec,
  xColumn: Column | null,
  measureKey: string | null,
): ResultRow[] {
  const copy = [...rows]
  if (xColumn?.type === 'date') {
    const key = xColumn.key
    return copy.sort((a, b) => String(a[key] ?? '').localeCompare(String(b[key] ?? '')))
  }
  if (!spec.sort || !measureKey) return copy
  const direction = spec.sort === 'asc' ? 1 : -1
  return copy.sort((a, b) => direction * (numeric(a[measureKey]) - numeric(b[measureKey])))
}

/**
 * `limit` truncates a ranked categorical axis. For part-of-whole charts the tail is
 * folded into "Övrigt" instead of dropped, because a pie that does not sum to the
 * whole is a lie.
 */
function applyLimit(
  rows: ResultRow[],
  spec: ChartSpec,
  series: SeriesDescriptor[],
  xColumn: Column | null,
): { rows: ResultRow[]; folded: boolean } {
  const limit = spec.limit
  if (!limit || limit <= 0 || rows.length <= limit || xColumn?.type === 'date') {
    return { rows, folded: false }
  }

  const head = rows.slice(0, limit)
  if (spec.type !== 'pie' || !xColumn) return { rows: head, folded: false }

  const tail = rows.slice(limit)
  const other: ResultRow = { [xColumn.key]: OTHER_LABEL }
  for (const descriptor of series) {
    other[descriptor.key] = tail.reduce((sum, row) => sum + numeric(row[descriptor.key]), 0)
  }
  return { rows: [...head, other], folded: true }
}

function maxAbs(rows: ResultRow[], series: SeriesDescriptor[]): number {
  let max = 0
  for (const row of rows) {
    for (const descriptor of series) {
      const value = Math.abs(numeric(row[descriptor.key]))
      if (value > max) max = value
    }
  }
  return max
}

/** Category labels on a bar axis are shortened, never clipped mid-word. */
export function axisCategoryLabel(value: string, wide: boolean): string {
  return truncateLabel(value, wide ? 30 : 16)
}
