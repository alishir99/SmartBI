/**
 * sv-SE formatting. Every number shown to the user goes through this file.
 *
 * Rules (API_CONTRACT.md § Formatting rules the frontend owns):
 *  - space thousands separator, comma decimal
 *  - money magnitude switching with the unit on the axis:
 *      < 100 tkr  -> kr      (i.e. below 100 000)
 *      < 10 Mkr   -> tkr     (i.e. below 10 000 000)
 *      otherwise  -> Mkr
 *  - percentages: one decimal
 *  - deltas always carry the comparison period as a label
 *  - ISO weeks, Swedish month names
 */

import type { Column, ColumnUnit, DateRange } from '../types'

/** Narrow no-break space — what sv-SE uses between a value and its unit. */
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
 * Pick one scale for a whole chart/tile from the largest absolute value in it,
 * so every tick and label on the same axis shares a unit.
 */
export function moneyScale(maxAbsSek: number): MoneyScale {
  const m = Math.abs(maxAbsSek)
  if (m < 100_000) return { divisor: 1, unit: 'kr', decimals: 0 }
  if (m < 10_000_000) return { divisor: 1_000, unit: 'tkr', decimals: 0 }
  return { divisor: 1_000_000, unit: 'Mkr', decimals: 1 }
}

/** `12,4 Mkr` — magnitude chosen from this value alone. */
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

/** `18,3 %` — always one decimal. */
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
  /** magnitude only, e.g. `8,2 %` — the arrow carries the sign */
  magnitude: string
  /** the comparison period; a delta is never rendered without it */
  label: string
}

/**
 * A delta is only meaningful next to what it is compared against, so this always
 * returns the label too. `delta_label` comes from the API; we fall back to an
 * explicit phrase rather than showing a bare arrow.
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

/** `v. 14 2026` — from a date, or from a `2026-W14` key. */
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

/** `14:32` — clock only, for the source chip. */
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

/** Format a raw cell according to its column definition. */
export function formatCell(value: string | number | null, column: Column): string {
  if (value === null || value === undefined || value === '') return '–'
  if (column.type === 'date') {
    const s = String(value)
    if (/^\d{4}-W\d{1,2}$/.test(s)) return formatIsoWeek(s)
    if (/^\d{4}-\d{2}$/.test(s)) return formatMonth(s)
    return formatDateIso(s)
  }
  if (column.type === 'number' && typeof value === 'number') {
    switch (column.unit) {
      case 'SEK':
        return formatMoneyExact(value)
      case '%':
        return formatPercent(value)
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

/** `Stockholms län · fysisk butik` from provenance.filters_applied. */
export function describeFilters(filters: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, raw] of Object.entries(filters)) {
    if (raw === null || raw === undefined) continue
    const value = Array.isArray(raw) ? raw.join(', ') : String(raw)
    if (!value) continue
    parts.push(`${FILTER_LABELS[key] ?? key}: ${value}`)
  }
  return parts.join(' · ')
}

const FILTER_LABELS: Record<string, string> = {
  region: 'Region',
  channel: 'Kanal',
  category_ids: 'Kategori',
  product_ids: 'Produkt',
  brand_ids: 'Varumärke',
  store_ids: 'Butik',
  category: 'Kategori',
}

/** `mv_sales_daily (rollup)` -> `Förberäknad rollup`. */
export function describeSource(source: string): string {
  if (/rollup|^mv_/i.test(source)) return 'Förberäknad rollup'
  if (/fact_/i.test(source)) return 'Faktatabell (radnivå)'
  return source
}
