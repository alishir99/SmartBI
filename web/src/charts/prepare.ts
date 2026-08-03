/** Turns (ChartSpec + columns + rows) into exactly what Recharts needs. */

import type { ChartSpec, Column, ColumnUnit, ResultRow } from '../types'
import { MAX_SERIES, SERIES_MUTED, seriesColor } from './palette'
import { moneyScale, truncateLabel, type MoneyScale } from '../lib/format'

export type SeriesDescriptor = {
  /** The key to read off each prepared row. */
  key: string
  label: string
  color: string
  /** A comparison period: context behind the current series, not a competitor to it. */
  muted?: boolean
  /** A derived average: drawn as a line even on a bar chart, because it is a shape, not a bar. */
  line?: boolean
}

/** The server's suffix for a derived moving average, in the same unit as the measure. */
const AVERAGE_SUFFIX = '_ma'

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
  /** Rows the chart is not drawing. Zero unless `spec.limit` cut a ranked categorical axis. */
  hidden: number
  /** One descriptor per pie slice, in row order; empty for every other chart type. */
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

/** Colour and label per slice, following the dimension value. */
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
  // The comparison period does not consume a categorical hue — otherwise "last year" arrives
  // looking like a second brand.
  let hue = 0
  const series = measures.map((column) => {
    const muted = column.key.endsWith('_compare')
    return {
      key: column.key,
      label: column.label,
      color: muted ? SERIES_MUTED : seriesColor(hue++),
      muted,
      line: column.key.endsWith(AVERAGE_SUFFIX),
    }
  })

  const ordered = order(rows, spec, xColumn, series[0]?.key ?? null)
  const { rows: limited, folded, hidden } = applyLimit(ordered, spec, series, xColumn)

  return {
    rows: limited,
    series,
    columns: [...(xColumn ? [xColumn] : []), ...measures],
    folded,
    hidden,
  }
}

/** Long input: one measure column, one column whose distinct values are the series. */
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
    hidden: 0,
  }
}

/**
 * A time axis is always chronological — a `sort` on a date x would scramble the reading order,
 * so the spec's sort only applies to categorical axes.
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

/** `limit` truncates a ranked categorical axis. */
function applyLimit(
  rows: ResultRow[],
  spec: ChartSpec,
  series: SeriesDescriptor[],
  xColumn: Column | null,
): { rows: ResultRow[]; folded: boolean; hidden: number } {
  const limit = spec.limit
  if (!limit || limit <= 0 || rows.length <= limit || xColumn?.type === 'date') {
    return { rows, folded: false, hidden: 0 }
  }

  const head = rows.slice(0, limit)
  // A bar chart cannot fold its tail into "Övrigt" — the sum of the categories it dropped is not
  // a category. So it drops them, and the count is reported instead: rows disappearing unnoticed
  // from the half of the card presented as the trustworthy half is the wrong place to be quiet.
  if (spec.type !== 'pie' || !xColumn) {
    return { rows: head, folded: false, hidden: rows.length - head.length }
  }

  const tail = rows.slice(limit)
  const other: ResultRow = { [xColumn.key]: OTHER_LABEL }
  for (const descriptor of series) {
    other[descriptor.key] = tail.reduce((sum, row) => sum + numeric(row[descriptor.key]), 0)
  }
  return { rows: [...head, other], folded: true, hidden: 0 }
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
