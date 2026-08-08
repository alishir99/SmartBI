
import type { ChartSpec, Column, ColumnUnit, ResultRow } from '../types'
import { MAX_SERIES, SERIES_MUTED, seriesColor } from './palette'
import { isCurrency, MISSING, moneyScale, truncateLabel, type MoneyScale } from '../lib/format'
import { columnLabel, t } from '../lib/i18n'

export type SeriesDescriptor = {
  key: string
  label: string
  color: string
  /** A comparison period: context behind the current series, not a competitor to it. */
  muted?: boolean
  /** A derived average: drawn as a line even on a bar chart, because it is a shape, not a bar. */
  line?: boolean
}

const AVERAGE_SUFFIX = '_ma'

export type PreparedChart = {
  rows: ResultRow[]
  series: SeriesDescriptor[]
  xColumn: Column | null
  unit: ColumnUnit | null
  /** Shared money scale so every tick and label on one axis carries one unit. */
  scale: MoneyScale | null
  columns: Column[]
  folded: boolean
  hidden: number
  slices: SeriesDescriptor[]
}

/** Read per call, not frozen at module load - a constant captured at import would stay in
 * whichever language loaded first, but the fold label needs the current one. */
const otherLabel = () => t('card.other')

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
    scale: isCurrency(unit) ? moneyScale(max) : null,
    slices: spec.type === 'pie' ? sliceDescriptors(prepared.rows, xColumn, prepared.folded) : [],
  }
}

function sliceDescriptors(
  rows: ResultRow[],
  xColumn: Column | null,
  folded: boolean,
): SeriesDescriptor[] {
  const key = xColumn?.key
  return rows.map((row, index) => {
    const label = key ? String(row[key] ?? MISSING) : `#${index + 1}`
    return {
      key: label,
      label,
      color: folded && label === otherLabel() ? SERIES_MUTED : seriesColor(index),
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
  // The comparison period does not consume a categorical hue - otherwise "last year" arrives
  // looking like a second brand.
  let hue = 0
  const series = measures.map((column) => {
    const muted = column.key.endsWith('_compare')
    return {
      key: column.key,
      // Translated off the column's key, falling back to whatever label the server sent: the
      // semantic layer is monolingual by design, and the key is the stable half of it.
      label: columnLabel(column.key, column.label),
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
    const name = String(row[seriesKey] ?? MISSING)
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
    const name = String(row[seriesKey] ?? MISSING)
    const target = keptSet.has(name) ? name : otherLabel()
    bucket[target] = numeric(bucket[target]) + numeric(row[measureKey])
  }

  const other = otherLabel()
  const names = folded ? [...kept, other] : kept
  const series = names.map((name, index) => ({
    key: name,
    label: name,
    // The fold bucket is never a real entity, so it never takes a categorical hue.
    color: name === other && folded ? SERIES_MUTED : seriesColor(index),
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

/** A time axis is always chronological - a `sort` on a date x would scramble the reading
 * order, so the spec's sort only applies to categorical axes. */
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
  // A bar chart can't fold its tail into "Övrigt" (the sum isn't a category), so it drops rows
  // and reports the count instead - silently losing rows from the "trustworthy" half is worse.
  if (spec.type !== 'pie' || !xColumn) {
    return { rows: head, folded: false, hidden: rows.length - head.length }
  }

  const tail = rows.slice(limit)
  const other: ResultRow = { [xColumn.key]: otherLabel() }
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
