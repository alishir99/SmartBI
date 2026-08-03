/** sv-SE formatting. */

import type { Column, ColumnUnit, DateRange } from '../types'

/** Narrow no-break space - what sv-SE uses between a value and its unit. */
const NBSP = '\u00A0'

const cache = new Map<string, Intl.NumberFormat>()
function nf(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`
  let f = cache.get(key)
  if (!f) {
    f = new Intl.NumberFormat('sv-SE', {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
      useGrouping: true,
    })
    cache.set(key, f)
  }
  return f
}

/** Plain number, sv-SE. `1 243` / `12,4`. */
export function formatNumber(value: number, decimals = 0): string {
  if (!Number.isFinite(value)) return '–'
  return nf(decimals, decimals).format(value)
}

// --- money ------------------------------------------------------------------

export type MoneyUnit = 'kr' | 'tkr' | 'Mkr'

export type MoneyScale = {
  /** divide raw SEK by this before display */
  divisor: number
  unit: MoneyUnit
  decimals: number
}

/**
 * Pick one scale for a whole chart/tile from the largest absolute value in it, so every tick and
 * label on the same axis shares a unit.
 */
export function moneyScale(maxAbsSek: number): MoneyScale {
  const m = Math.abs(maxAbsSek)
  if (m < 100_000) return { divisor: 1, unit: 'kr', decimals: 0 }
  if (m < 10_000_000) return { divisor: 1_000, unit: 'tkr', decimals: 0 }
  return { divisor: 1_000_000, unit: 'Mkr', decimals: 1 }
}

/** `12,4 Mkr` - magnitude chosen from this value alone. */
export function formatMoney(sek: number): string {
  const s = moneyScale(sek)
  return `${nf(s.decimals, s.decimals).format(sek / s.divisor)}${NBSP}${s.unit}`
}

/** Value only, on a scale decided elsewhere (axis ticks, bar labels). */
export function formatMoneyOnScale(sek: number, scale: MoneyScale): string {
  return nf(scale.decimals, scale.decimals).format(sek / scale.divisor)
}

/** `12,4 Mkr` on a shared scale. */
export function formatMoneyWithUnit(sek: number, scale: MoneyScale): string {
  return `${formatMoneyOnScale(sek, scale)}${NBSP}${scale.unit}`
}

/** Full precision, for tooltips and the source chip. `23 480 500 kr`. */
export function formatMoneyExact(sek: number): string {
  return `${nf(0, 0).format(Math.round(sek))}${NBSP}kr`
}

// --- percent, units ---------------------------------------------------------

/** `18,3 %` - always one decimal. */
export function formatPercent(value: number, decimals = 1): string {
  return `${nf(decimals, decimals).format(value)}${NBSP}%`
}

/** Percentage points, for share deltas. `+0,7 p.e.` */
export function formatPercentPoints(value: number): string {
  return `${signPrefix(value)}${nf(1, 1).format(Math.abs(value))}${NBSP}p.e.`
}

export function formatUnits(value: number): string {
  return `${nf(0, 0).format(value)}${NBSP}st`
}

function signPrefix(value: number): string {
  return value > 0 ? '+' : value < 0 ? '−' : ''
}

// --- deltas -----------------------------------------------------------------

export type Delta = {
  direction: 'up' | 'down' | 'flat'
  /** magnitude only, e.g. `8,2 %` - the arrow carries the sign */
  magnitude: string
  /** the comparison period; a delta is never rendered without it */
  label: string
}

/**
 * A delta is only meaningful next to what it is compared against, so this always returns the
 * label too.
 */
export function formatDelta(
  deltaPct: number | null,
  deltaLabel: string | null,
  unit?: ColumnUnit,
): Delta | null {
  if (deltaPct === null || deltaPct === undefined || !Number.isFinite(deltaPct)) return null
  const direction = deltaPct > 0.05 ? 'up' : deltaPct < -0.05 ? 'down' : 'flat'
  // A change in a percentage measure is stated in percentage points, not percent of a percent.
  const magnitude =
    unit === '%'
      ? `${nf(1, 1).format(Math.abs(deltaPct))}${NBSP}p.e.`
      : `${nf(1, 1).format(Math.abs(deltaPct))}${NBSP}%`
  return { direction, magnitude, label: deltaLabel ?? 'vs föregående period' }
}

// --- dates ------------------------------------------------------------------

export const MONTHS_SHORT = [
  'jan',
  'feb',
  'mar',
  'apr',
  'maj',
  'jun',
  'jul',
  'aug',
  'sep',
  'okt',
  'nov',
  'dec',
]

export const MONTHS_LONG = [
  'januari',
  'februari',
  'mars',
  'april',
  'maj',
  'juni',
  'juli',
  'augusti',
  'september',
  'oktober',
  'november',
  'december',
]

/** Accepts `2026-01`, `2026-01-01` or an ISO timestamp. */
function parseYm(value: string): { year: number; month: number; day: number } | null {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(value)
  if (!m) return null
  return { year: Number(m[1]), month: Number(m[2]), day: m[3] ? Number(m[3]) : 1 }
}

/** `jan 2026`. Used for month axis ticks. */
export function formatMonth(value: string, withYear = true): string {
  const p = parseYm(value)
  if (!p) return value
  const name = MONTHS_SHORT[p.month - 1] ?? String(p.month)
  return withYear ? `${name} ${p.year}` : name
}

/** `24 jun` - a day bucket on an axis, where the year is already in the card's period line. */
export function formatDayShort(value: string): string {
  const p = parseYm(value)
  if (!p) return value
  return `${p.day} ${MONTHS_SHORT[p.month - 1] ?? p.month}`
}

/** `4 januari 2026`. */
export function formatDateLong(value: string): string {
  const p = parseYm(value)
  if (!p) return value
  return `${p.day} ${MONTHS_LONG[p.month - 1]} ${p.year}`
}

/** `2026-01-04`. */
export function formatDateIso(value: string): string {
  const p = parseYm(value)
  if (!p) return value
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`
}

/** ISO-8601 week number (Monday-based, week 1 contains the first Thursday). */
export function isoWeek(date: Date): { year: number; week: number } {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const day = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((d.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7)
  return { year: d.getUTCFullYear(), week }
}

/** `v. 14 2026` - from a date, or from a `2026-W14` key. */
export function formatIsoWeek(value: string): string {
  const w = /^(\d{4})-W(\d{1,2})$/.exec(value)
  if (w) return `v.${NBSP}${Number(w[2])} ${w[1]}`
  const p = parseYm(value)
  if (!p) return value
  const { year, week } = isoWeek(new Date(Date.UTC(p.year, p.month - 1, p.day)))
  return `v.${NBSP}${week} ${year}`
}

/** `jan–jun 2026`, `dec 2025–jun 2026`, `2024–2026`. */
export function formatPeriod(range: DateRange): string {
  const a = parseYm(range.from)
  const b = parseYm(range.to)
  if (!a || !b) return `${range.from}–${range.to}`
  if (a.year === b.year) {
    if (a.month === b.month) return `${MONTHS_SHORT[a.month - 1]} ${a.year}`
    return `${MONTHS_SHORT[a.month - 1]}–${MONTHS_SHORT[b.month - 1]} ${a.year}`
  }
  return `${MONTHS_SHORT[a.month - 1]} ${a.year}–${MONTHS_SHORT[b.month - 1]} ${b.year}`
}

/** `14:32` - clock only, for the source chip. */
export function formatClock(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('sv-SE', { hour: '2-digit', minute: '2-digit' }).format(d)
}

/** `27 juli 2026, 14:32`. */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getDate()} ${MONTHS_LONG[d.getMonth()]} ${d.getFullYear()}, ${formatClock(iso)}`
}

// --- generic dispatch -------------------------------------------------------

/** `K3 2025`. */
export function formatQuarter(value: string): string {
  const p = parseYm(value)
  if (!p) return value
  return `K${Math.floor((p.month - 1) / 3) + 1} ${p.year}`
}

/**
 * Every date bucket comes back as its first day, so `2025-07-01` is a month under a `month`
 * grouping and a genuine day under a `day` one: the value alone cannot say which. The column
 * key can, because it is the dimension key the compiler grouped by, which the API contract
 * fixes. Without this the trend axis reads "2025-07-01" where it means "jul 2025".
 */
const DATE_GRAIN: Record<string, (value: string) => string> = {
  day: formatDayShort,
  month: formatMonth,
  quarter: formatQuarter,
  week: formatIsoWeek,
}

/** Format a raw cell according to its column definition. */
export function formatCell(value: string | number | null, column: Column): string {
  if (value === null || value === undefined || value === '') return '–'
  if (column.type === 'date') {
    const s = String(value)
    if (/^\d{4}-W\d{1,2}$/.test(s)) return formatIsoWeek(s)
    if (/^\d{4}-\d{2}$/.test(s)) return formatMonth(s)
    // `month_compare` is the same grain as `month`.
    const grain = DATE_GRAIN[column.key.replace(/_compare$/, '')]
    return grain ? grain(s) : formatDateIso(s)
  }
  if (column.type === 'number' && typeof value === 'number') {
    switch (column.unit) {
      case 'SEK':
        return formatMoneyExact(value)
      case '%':
        return formatPercent(value)
      case 'p.e.':
        return formatPercentPoints(value)
      case 'st':
        return formatUnits(value)
      default:
        return formatNumber(value, Number.isInteger(value) ? 0 : 1)
    }
  }
  return String(value)
}

/** Value for a KPI tile, by unit. */
export function formatKpiValue(value: number, unit: ColumnUnit): string {
  switch (unit) {
    case 'SEK':
      return formatMoney(value)
    case '%':
      return formatPercent(value)
    case 'p.e.':
      return formatPercentPoints(value)
    case 'st':
      return formatUnits(value)
    default:
      return formatNumber(value)
  }
}

/** Shorten a long category label for an axis without clipping mid-word. */
export function truncateLabel(value: string, max = 26): string {
  if (value.length <= max) return value
  return `${value.slice(0, max - 1).trimEnd()}…`
}

/** `Stockholms län · 1 produkt` from provenance.filters_applied. */
export function describeFilters(filters: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, raw] of Object.entries(filters)) {
    if (raw === null || raw === undefined) continue
    const values = Array.isArray(raw) ? raw : [raw]
    if (values.length === 0) continue

    // An id filter is real - the numbers are narrowed by it and the user has to know - but
    // the id itself is a database key. "Produkt: 8" says nothing to a supplier and reads as
    // an internal leak, so the filter is counted rather than printed.
    const counted = COUNTED_FILTERS[key]
    if (counted) {
      parts.push(values.length === 1 ? `1 ${counted[0]}` : `${values.length} ${counted[1]}`)
      continue
    }

    const value = values.join(', ')
    if (!value) continue
    parts.push(`${FILTER_LABELS[key] ?? key}: ${value}`)
  }
  return parts.join(' · ')
}

/** Singular and plural for the filters that carry ids rather than names. */
const COUNTED_FILTERS: Record<string, [string, string]> = {
  category_ids: ['kategori', 'kategorier'],
  product_ids: ['produkt', 'produkter'],
  brand_ids: ['varumärke', 'varumärken'],
  store_ids: ['butik', 'butiker'],
}

const FILTER_LABELS: Record<string, string> = {
  region: 'Region',
  channel: 'Kanal',
  category: 'Kategori',
}
